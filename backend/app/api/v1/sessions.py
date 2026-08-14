"""The fill conversation over HTTP. Plan §6, §10 stages ③-⑦.

The screen that decides the score (`/templates/:id/generate`) talks to exactly
these endpoints. Everything they do above the deterministic boundary is in
`app/conversation/` and `app/planning/`; everything below it is
`compile_and_store`, which shipped before the conversation did and is reused
rather than reimplemented.

**Where each model call happens, and why there.**

* `POST /sessions` runs the context agent and, on a cache miss, the planner.
  That is 2 calls, once per session, and the planner half is cached per version
  so a second session on the same document costs 1.
* `POST /answer` runs the extractor, and only the extractor. Plan §6 budgets
  this turn at 1.5s because the user is watching the preview.
* The deriver runs **once**, on the last answer -- it reasons over the whole
  document and would blow that budget on every turn for no benefit.

**The schema is re-detected from the stored bytes, not read from
`document_regions`.** Same reason the compile path does it: a spec must resolve
against the schema of the exact bytes being compiled, and a stored schema from
an older detector would resolve `region_id`s against coordinates that no longer
describe the file. It costs 30-300ms.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.generate import _fetch, _load, compile_and_store
from app.compiler.from_spec import value_rejection_reason
from app.api.deps import current_user
from app.models.user import User
from app.conversation.context import assemble_context
from app.conversation.deriver import derive_values
from app.conversation.extractor import extract_answer
from app.conversation.planner import PlannedQuestion, plan_questions
from app.conversation.scope import addressable_ids, askable
from app.conversation.state import (
    TURN_INSTRUCTION,
    SessionProgress,
    answered_count,
    load_question_plan,
    record_turn,
    save_question_plan,
)
from app.db.session import get_db
from app.ingestion.detect import detect
from app.models.generation_session import (
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_COMMITTED,
    GenerationSession,
)
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.planning.change_planner import plan_change_spec
from app.schemas.generate import CompileResponse
from app.schemas.session import (
    AnswerIn,
    AnswerOut,
    ChipOut,
    InstructionIn,
    ProgressOut,
    QuestionOut,
    SessionCompileIn,
    SessionCreate,
    SessionCreateOut,
    SessionOut,
    SpecOperationPatch,
    SpecOut,
    TurnOut,
)

logger = logging.getLogger("app.sessions")

router = APIRouter(prefix="/sessions", tags=["generation"])


# ── loading ───────────────────────────────────────────────────────────────


def _session(db: Session, session_id: uuid.UUID) -> GenerationSession:
    session = db.get(GenerationSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def _context_for(
    db: Session, session: GenerationSession
) -> tuple[Template, TemplateVersion, Any]:
    """The template, its version, and a freshly detected schema of the stored bytes."""
    template = db.get(Template, session.template_id)
    version = db.get(TemplateVersion, session.base_version_id)
    if template is None or version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The template or version this session was started from no longer exists.",
        )
    return template, version, detect(_fetch(version), template.format)


def _template_meta(template: Template) -> dict[str, Any]:
    return {
        "title": template.title,
        "purpose": getattr(template, "purpose", None),
        "when_to_use": getattr(template, "when_to_use", None),
        "audience": getattr(template, "audience", None),
    }


def _fields_total(schema: Any) -> int:
    """The denominator of "26 of 31 fields": what the interview sets out to fill.

    `askable`, not `addressable`. A heading is writable on request but is never
    raised by a question and never derived, so counting one would put a field in
    the denominator that no answer can move -- the counter would read worse the
    more headings a document has, for no reason a user could see.
    """
    return len(askable(schema))


def _progress(
    session: GenerationSession, questions: list[PlannedQuestion], schema: Any
) -> SessionProgress:
    derived = (session.derived_values or {}).get("values", {})
    filled = session.filled_values or {}
    return SessionProgress(
        answered=answered_count(session),
        total_questions=len(questions),
        # Union, not sum. The deriver skips regions already in `filled_values`,
        # so the two are disjoint *when it runs* -- but a review-screen edit
        # (`PATCH /spec/{i}`) writes a derived region into `filled_values`
        # afterwards, and adding the lengths then counts it twice and can put
        # the headline counter above `fields_total`.
        fields_filled=len(set(filled) | set(derived)),
        fields_total=_fields_total(schema),
    )


def _skipped_regions(
    session: GenerationSession, questions: list[PlannedQuestion]
) -> set[str]:
    """Regions whose only question the user chose to skip.

    Skipping is a decision, not an omission: `POST /answer` promises those
    regions stay untouched and visibly empty on the review screen, so the user
    can see the gap and fill it themselves. The deriver picks its targets from
    `must_ask` + `inferable` minus whatever is already filled -- and a skipped
    turn fills nothing, so without this set stage ⑥ writes precisely the fields
    the user declined to answer. That is the one thing it must never do.

    Regions the planner also handed to a question that *was* answered are
    excluded: the planner keeps clusters disjoint, so this is defensive, but if
    they ever overlap the answered question is the stronger signal.
    """
    covers = {q.question_id: q.covers_regions for q in questions}
    skipped: set[str] = set()
    answered: set[str] = set()
    for turn in session.turns or []:
        bucket = skipped if turn.get("skipped") else answered
        bucket.update(covers.get(turn.get("question_id"), []))
    return skipped - answered


def _question_out(question: PlannedQuestion) -> QuestionOut:
    return QuestionOut(**question.as_dict())


def _current(
    session: GenerationSession, questions: list[PlannedQuestion]
) -> PlannedQuestion | None:
    answered = answered_count(session)
    return questions[answered] if answered < len(questions) else None


def _labels(schema: Any) -> dict[str, str]:
    return {r.region_id: (r.label or r.region_id) for r in schema.regions}


def _session_out(
    session: GenerationSession,
    template: Template,
    questions: list[PlannedQuestion],
    schema: Any,
    cls: type = SessionOut,
    **extra: Any,
) -> Any:
    current = _current(session, questions)
    return cls(
        session_id=session.id,
        template_id=session.template_id,
        base_version_id=session.base_version_id,
        format=template.format,
        tier=session.tier,
        intent=session.user_intent,
        status=session.status,
        questions=[_question_out(q) for q in questions],
        current_question=_question_out(current) if current else None,
        turns=[TurnOut(**t) for t in (session.turns or [])],
        filled_values=session.filled_values or {},
        derived_values=(session.derived_values or {}).get("values", {}),
        known_context=session.known_context or {},
        progress=ProgressOut(**_progress(session, questions, schema).as_dict()),
        started_at=session.started_at,
        completed_at=session.completed_at,
        **extra,
    )


# ── endpoints ─────────────────────────────────────────────────────────────


@router.post("", response_model=SessionCreateOut, status_code=status.HTTP_201_CREATED)
def start_session(
    request: SessionCreate, db: Session = Depends(get_db)
) -> SessionCreateOut:
    """Triage the document and plan the questions. Plan §10 ③ then ④.

    Both stages degrade rather than fail: with Bedrock unreachable every
    editable region lands in `must_ask` and the planner falls back to its
    structural grouping, which is a longer interview over the same regions.
    """
    template, version = _load(db, request.template_id, request.version_id)
    schema = detect(_fetch(version), template.format)
    meta = _template_meta(template)

    context = assemble_context(
        schema, template_meta=meta, intent=request.intent
    )

    # The plan is a property of the version, so a cache hit here means the
    # second session on this document costs no planner call at all.
    #
    # `include_fallback=False`: a plan written by the structural fallback is
    # deliberately *not* a hit. Caching it like a real one meant a single
    # Bedrock outage permanently downgraded every future interview on this
    # document to "Please provide: Venue, Date, Attendees", with no way back.
    questions = load_question_plan(db, version.id, include_fallback=False)
    planner_errors: list[str] = []
    if not questions:
        plan = plan_questions(
            schema,
            context.must_ask + context.inferable,
            template_meta=meta,
            intent=request.intent,
        )
        questions = plan.questions
        planner_errors = plan.errors
        if questions and not save_question_plan(
            db, version.id, questions, planner_version=plan.planner_version
        ):
            # Another session planned this version in the same instant and won
            # the unique constraint. Theirs is as good as ours and is the one
            # on disk, so this session joins it rather than failing.
            questions = load_question_plan(db, version.id) or questions

    session = GenerationSession(
        id=uuid.uuid4(),
        template_id=template.id,
        base_version_id=version.id,
        tier=request.tier,
        user_intent=request.intent,
        status=STATUS_ACTIVE,
        known_context=context.as_dict(),
        filled_values={},
        derived_values={},
        turns=[],
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    degraded = bool(context.errors or planner_errors)
    summary = (
        f"{len(context.known)} already correct, {len(context.inferable)} derivable, "
        f"{len(questions)} question{'s' if len(questions) != 1 else ''} to ask"
        + (" (planned without the model)" if degraded else "")
    )
    logger.info("session %s started on %s: %s", session.id, template.title, summary)

    return _session_out(
        session, template, questions, schema, cls=SessionCreateOut, plan_summary=summary
    )


def _read_message(
    schema: Any,
    text: str,
    *,
    asked_regions: list[str],
    question_text: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[ChipOut], bool, list[str]]:
    """One user message → `(answered, volunteered, chips, degraded, warnings)`.

    Shared by `POST /answer` and `POST /instruct`, which differ only in whether
    a question was on the table. Both read the message against the **whole**
    addressable document rather than one cluster: a person answering "the venue
    was Room 2, and Priya is chairing the next one" has supplied two things, and
    the second used to be parsed against nothing and dropped without a word. See
    `app.conversation.extractor` for why the wider enum is not a wider hole --
    it still contains only ids the detector found in these bytes, and every gate
    below the deterministic boundary is unchanged.

    The warnings are the other half of "any valid input is accepted": a message
    that lands nowhere says so, out loud, on the turn it happened.
    """
    extraction = extract_answer(
        schema,
        text,
        asked_regions,
        also_regions=addressable_ids(schema),
        question_text=question_text,
    )
    labels = _labels(schema)
    chips = [ChipOut(**c) for c in extraction.chips(labels)]
    degraded = not extraction.ok
    warnings: list[str] = []

    if degraded:
        warnings.append(
            "The extractor was unavailable; your answer was kept and can be re-read later."
        )
    elif not extraction.values and not extraction.volunteered and text.strip():
        # The user typed something real and none of it could be placed. Saying
        # so is the guardrail: silence here is indistinguishable from success,
        # and they would find out at the review screen or not at all.
        warnings.append(
            "None of that could be matched to a field in this document. Try naming the "
            "field you mean, or set it directly on the review screen."
        )

    if extraction.volunteered:
        named = ", ".join(
            labels.get(rid, rid) for rid in list(extraction.volunteered)[:4]
        )
        more = len(extraction.volunteered) - 4
        warnings.append(
            f"Also captured: {named}" + (f" and {more} more" if more > 0 else "") + "."
        )

    return extraction.values, extraction.volunteered, chips, degraded, warnings


@router.post("/{session_id}/answer", response_model=AnswerOut)
def answer(
    session_id: uuid.UUID, request: AnswerIn, db: Session = Depends(get_db)
) -> AnswerOut:
    """Extract one answer. Runs the deriver only when it was the last question.

    A skipped question is recorded as a turn with no values, which is the point:
    the regions it covered stay untouched and *visible* on the review screen,
    rather than being quietly filled with something plausible.
    """
    session = _session(db, session_id)
    if session.status not in (STATUS_ACTIVE,):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This session is {session.status} and no longer takes answers.",
        )

    template, version, schema = _context_for(db, session)
    questions = load_question_plan(db, version.id)
    current = _current(session, questions)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Every question has been answered."
        )
    if request.question_id != current.question_id:
        # Answering out of order would attribute the values to the wrong region
        # cluster, so it is refused rather than reordered.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Expected an answer to {current.question_id}, got {request.question_id}.",
        )

    warnings: list[str] = []
    if request.skip:
        extraction_values: dict[str, Any] = {}
        volunteered: dict[str, Any] = {}
        chips: list[ChipOut] = []
        degraded = False
    else:
        extraction_values, volunteered, chips, degraded, warnings = _read_message(
            schema,
            request.answer,
            asked_regions=current.covers_regions,
            question_text=current.question_text,
        )

    record_turn(
        session,
        question_id=current.question_id,
        question_text=current.question_text,
        answer=request.answer,
        extracted=extraction_values,
        volunteered=volunteered,
        skipped=request.skip,
        degraded=degraded,
    )

    next_question = _current(session, questions)
    derived_out: dict[str, Any] = {}

    if next_question is None:
        # Last turn. The deriver reasons over the whole document, so it runs
        # here rather than on every answer -- see the module docstring.
        context = session.known_context or {}
        # A skipped question's regions are held back from the deriver: this
        # endpoint promises they stay untouched, and they are unfilled by
        # definition, so they would otherwise be its first targets.
        held_back = _skipped_regions(session, questions)
        targets = [
            rid
            for rid in context.get("inferable", []) + context.get("must_ask", [])
            if rid not in (session.filled_values or {}) and rid not in held_back
        ]
        derivation = derive_values(
            schema,
            targets,
            session.filled_values or {},
            turns=session.turns,
            template_meta=_template_meta(template),
            intent=session.user_intent,
        )
        session.derived_values = derivation.as_dict()
        derived_out = {rid: dv.as_dict() for rid, dv in derivation.values.items()}
        if not derivation.ok:
            warnings.append("Derivation was unavailable; only what you typed will be written.")
        if derivation.unjustified:
            warnings.append(
                f"{len(derivation.unjustified)} derived value(s) were discarded for "
                "naming no source in your answers."
            )
        if held_back:
            warnings.append(
                f"{len(held_back)} field(s) from skipped questions were left empty "
                "rather than derived — you can fill them on the review screen."
            )

    db.commit()
    db.refresh(session)

    return AnswerOut(
        session_id=session.id,
        extracted=extraction_values,
        volunteered=volunteered,
        chips=chips,
        derived=derived_out,
        next_question=_question_out(next_question) if next_question else None,
        progress=ProgressOut(**_progress(session, questions, schema).as_dict()),
        degraded=degraded,
        warnings=warnings,
    )


@router.post("/{session_id}/instruct", response_model=AnswerOut)
def instruct(
    session_id: uuid.UUID, request: InstructionIn, db: Session = Depends(get_db)
) -> AnswerOut:
    """Apply a free-form edit to the document. Answers no question.

    *"Change the heading to Q3 Review."* *"The venue should say Room 2."* These
    are not answers -- there may be no question left to answer -- and before this
    route there was nowhere to put them. The interview ran out of questions, the
    session stayed `active`, and `POST /answer` returned a 409 to anyone who
    still had something to say.

    Three properties make it safe to accept an imperative here:

    * **It cannot move the interview.** The turn is recorded as an instruction,
      and `answered_count` skips those, so an aside never consumes a question
      the user has not been asked.
    * **It cannot reach a region the detector did not find.** The extractor's
      enum is `scope.addressable`, and `plan_change_spec` and each compiler's
      pre-flight re-refuse a protected or non-editable target below it. Format
      and package integrity are not this endpoint's promise to keep -- they are
      structural, one layer down, and unchanged by anything said up here.
    * **It outranks derivation, not the reverse.** The value lands in
      `filled_values`, which `plan_change_spec` prefers over anything stage ⑥
      concluded. A user correcting the document has the last word.

    The deriver deliberately does not re-run: it fills what is empty, and an
    instruction is a statement about a region the user is already thinking about.
    """
    session = _session(db, session_id)
    if session.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This session is {session.status} and no longer takes edits.",
        )

    text = (request.instruction or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An instruction cannot be empty.",
        )

    template, version, schema = _context_for(db, session)
    questions = load_question_plan(db, version.id)

    # No asked cluster: every addressable region is equally in play, which is
    # what "obey the instruction" means when nothing was asked.
    values, volunteered, chips, degraded, warnings = _read_message(
        schema, text, asked_regions=[], question_text=None
    )

    record_turn(
        session,
        question_id="",
        question_text="",
        answer=text,
        extracted=values,
        volunteered=volunteered,
        kind=TURN_INSTRUCTION,
        degraded=degraded,
    )
    db.commit()
    db.refresh(session)

    logger.info(
        "session %s instruction set %d region(s) on %s",
        session.id,
        len(values) + len(volunteered),
        template.title,
    )

    # Unchanged by definition -- an instruction does not answer a question -- but
    # returned so the chat screen can re-render from one response shape.
    pending = _current(session, questions)

    return AnswerOut(
        session_id=session.id,
        extracted=values,
        volunteered=volunteered,
        chips=chips,
        derived={},
        next_question=_question_out(pending) if pending else None,
        progress=ProgressOut(**_progress(session, questions, schema).as_dict()),
        degraded=degraded,
        warnings=warnings,
    )


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    """Full state, enough to rebuild the chat screen after a reload."""
    session = _session(db, session_id)
    template, version, schema = _context_for(db, session)
    return _session_out(session, template, load_question_plan(db, version.id), schema)


def _build_spec(
    db: Session,
    session: GenerationSession,
    schema: Any,
    *,
    overrides: dict[str, Any] | None = None,
):
    """Stage ⑦ over this session's state. Deterministic; no model call."""
    question_of_region: dict[str, str] = {}
    for question in load_question_plan(db, session.base_version_id):
        for region_id in question.covers_regions:
            question_of_region[region_id] = question.question_id

    filled = dict(session.filled_values or {})
    if overrides:
        # The review screen's edits are the user's own words and outrank both
        # the extractor and the deriver.
        filled.update(overrides)

    return plan_change_spec(
        schema,
        filled,
        (session.derived_values or {}).get("values", {}),
        base_version_id=session.base_version_id,
        tier=session.tier,
        intent=session.user_intent,
        question_of_region=question_of_region,
    )


@router.get("/{session_id}/spec", response_model=SpecOut)
def get_spec(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SpecOut:
    """The Change Specification this session would compile.

    Built on demand rather than stored: it is a pure function of the session's
    values, so a stored copy could only ever go stale against an edited answer.
    The stored copy is written by `compile_and_store`, at the moment it is
    actually applied to bytes -- which is the version worth auditing.
    """
    session = _session(db, session_id)
    _, _, schema = _context_for(db, session)
    planned = _build_spec(db, session, schema)
    return SpecOut(
        session_id=session.id,
        base_version_id=session.base_version_id,
        spec=planned.spec,
        operation_count=planned.operation_count,
        provenance_counts=planned.spec.provenance_counts(),
        skipped=planned.skipped,
    )


@router.patch("/{session_id}/spec/{op_index}", response_model=SpecOut)
def patch_spec_operation(
    session_id: uuid.UUID,
    op_index: int,
    request: SpecOperationPatch,
    db: Session = Depends(get_db),
) -> SpecOut:
    """Edit one operation's value from the review screen.

    The edit is stored against the **region**, not the operation index, and the
    spec is rebuilt from it. Storing it positionally would break the moment any
    other answer changed and renumbered the operations.

    Only the value moves. Re-pointing an operation at a different region is not
    offered here -- that is precisely what the injection barrier exists to stop,
    and a review screen is not a reason to open a second door to it.
    """
    session = _session(db, session_id)
    _, _, schema = _context_for(db, session)
    planned = _build_spec(db, session, schema)

    operations = planned.spec.operations
    if op_index < 0 or op_index >= len(operations):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"This spec has {len(operations)} operations; there is no #{op_index}.",
        )
    operation = operations[op_index]
    if getattr(operation, "op", None) == "protect":
        # `plan_change_spec` appends one `protect` op per protected region to
        # this same list, so they are addressable by index like any other. They
        # carry no value: an edit aimed at one used to be accepted with a 200,
        # write a protected region_id into `filled_values`, and then be dropped
        # by the planner on the rebuild -- silently doing nothing, forever.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That operation is a protection declaration, not an edit. It has no "
            "value to change, and the region it names is never written.",
        )
    target = operation.target.region_id
    if not target:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That operation does not name a region and cannot be edited.",
        )

    region = next((r for r in schema.regions if r.region_id == target), None)
    if region is None or not region.editable or region.protected:
        # The same refusal `plan_change_spec` makes, made at the door instead:
        # a session resumed against a re-detected version can name a region that
        # has since become protected, and the answer is no here rather than a
        # value quietly parked in `filled_values` that never compiles.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{target} is not an editable region in this version and cannot be set.",
        )

    value = request.rows if request.rows is not None else request.value
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide a `value` or `rows`.",
        )

    rejection = value_rejection_reason(schema.format, region, value)
    if rejection:
        # Refused with the compiler's own words rather than accepted and dropped
        # at compile time. Typing prose into a date cell used to be a 200 here,
        # a dropped operation at commit, and -- because the planner had already
        # written a `must_equal` for it -- a failed QA gate that blocked the
        # whole document with no indication of which field caused it.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"That value cannot go into {region.label or target}: {rejection}",
        )

    filled = dict(session.filled_values or {})
    filled[target] = value
    session.filled_values = filled
    db.commit()
    db.refresh(session)

    rebuilt = _build_spec(db, session, schema)
    return SpecOut(
        session_id=session.id,
        base_version_id=session.base_version_id,
        spec=rebuilt.spec,
        operation_count=rebuilt.operation_count,
        provenance_counts=rebuilt.spec.provenance_counts(),
        skipped=rebuilt.skipped,
    )


@router.post("/{session_id}/compile", response_model=CompileResponse)
def compile_session(
    session_id: uuid.UUID,
    request: SessionCompileIn,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CompileResponse:
    """Compile this session's spec. `dry_run` returns QA and keeps nothing.

    A thin wrapper over `compile_and_store` by design: the bytes path shipped
    and was tested before the conversation existed, and a second implementation
    would eventually disagree with it about whether QA is a gate.

    **A dry run keeps nothing, and that now includes the session's status.** It
    used to move `active` to `compiled` on a pass, which was wrong twice over.
    The review screen fires a dry run on mount and is reachable after a single
    answer, so previewing mid-interview locked the session out of `POST /answer`
    with a 409; and re-opening it after a real commit downgraded `committed`
    back to `compiled` while `completed_at` stayed set, leaving a row that
    contradicted itself. Every dry run is already on `qa_runs` with
    `dry_run=true`, which is the better record of it anyway.
    """
    session = _session(db, session_id)
    if session.status == STATUS_ABANDONED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session was abandoned and cannot be compiled.",
        )
    if not request.dry_run and session.status == STATUS_COMMITTED:
        # Not idempotency for its own sake: without this a second commit mints a
        # second version off the same answers, and a double-click is enough.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session has already been committed. Start a new one to produce "
            "another version.",
        )

    template, version, schema = _context_for(db, session)
    planned = _build_spec(db, session, schema, overrides=request.overrides)

    if not planned.spec.operations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has produced no operation to apply yet.",
        )

    response = compile_and_store(
        db,
        template,
        version,
        planned.spec,
        dry_run=request.dry_run,
        publish=request.publish,
        # **The conversation produces a document unless asked otherwise.**
        # Filling a form's fields makes a document, not a better form, and the
        # default has to be the common case: most sessions are one person making
        # one thing for themselves. `submit_as_version` is the review screen's
        # "make this the template" and is what puts it in front of doc control.
        as_version=request.submit_as_version,
        title=session.user_intent,
        session_id=session.id,
        user=user,
        background_tasks=background_tasks,
    )

    if not request.dry_run and response.overall == "pass":
        session.status = STATUS_COMMITTED
        session.completed_at = datetime.now(timezone.utc)
        db.commit()

    return response


@router.post("/{session_id}/commit", response_model=CompileResponse)
def commit_session(
    session_id: uuid.UUID,
    request: SessionCompileIn,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CompileResponse:
    """Compile for real and keep the result as a new version.

    Identical to `/compile` with `dry_run: false`, exposed separately because
    plan §6 names both and because "commit" reading as a commit at the call site
    is worth one route.
    """
    return compile_session(
        session_id,
        SessionCompileIn(
            dry_run=False,
            submit_as_version=request.submit_as_version,
            publish=request.publish,
            overrides=request.overrides,
        ),
        background_tasks,
        user,
        db,
    )


@router.post("/{session_id}/abandon", response_model=SessionOut)
def abandon_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    """Walk away. The session is kept, not deleted -- an abandoned interview is
    evidence about the question plan, and deleting it would throw that away."""
    session = _session(db, session_id)
    session.status = STATUS_ABANDONED
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)

    template, version, schema = _context_for(db, session)
    return _session_out(session, template, load_question_plan(db, version.id), schema)
