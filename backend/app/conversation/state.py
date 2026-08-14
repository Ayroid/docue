"""Session state: load, mutate, persist. Plan §10's "state lives in Postgres".

This module is the reason the plan skips Semantic Kernel and LangChain. A
framework would hold the conversation in memory; keeping it in
`generation_sessions` makes every run inspectable, resumable and auditable, and
means a server restart mid-demo costs nothing. That is a capability, not a
preference, and it is the answer to the "why no framework?" question the PS
invites.

Everything here is deliberately dull. The interesting decisions are upstream in
the four model stages; this is the part that must simply not lose anything.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.conversation.planner import FALLBACK_PLANNER_VERSION, PlannedQuestion
from app.models.generation_session import GenerationSession
from app.models.question_plan import QuestionPlan

logger = logging.getLogger(__name__)

__all__ = [
    "TURN_ANSWER",
    "TURN_INSTRUCTION",
    "TURN_PREFILL",
    "SessionProgress",
    "answered_count",
    "freeze_ask_plan",
    "load_question_plan",
    "record_turn",
    "save_question_plan",
    "session_questions",
]

# What a turn was. Only an answer advances the interview -- everything else is a
# turn in the transcript and nowhere else, which is what keeps "change the
# heading" from consuming the next question.
TURN_ANSWER = "answer"
TURN_INSTRUCTION = "instruction"
# Notes the user pasted before being asked anything. Distinct from an
# instruction rather than folded into it: both are recorded with no question_id,
# so anything discriminating on that alone cannot tell the opening evidence from
# a mid-interview correction -- and provenance has to.
TURN_PREFILL = "prefill"

# Where the frozen per-session interview lives inside `known_context`.
_ASK_PLAN_KEY = "ask_plan"


@dataclass
class SessionProgress:
    """The derivation counter. `4 answers → 26 of 31 fields`.

    `fields_total` counts regions a conversation could ever fill -- editable and
    unprotected -- not every region in the document. Counting branding and the
    revision block in the denominator would understate the fill rate with
    regions nobody is allowed to touch.
    """

    answered: int
    total_questions: int
    fields_filled: int
    fields_total: int

    def as_dict(self) -> dict[str, int]:
        return {
            "answered": self.answered,
            "total_questions": self.total_questions,
            "fields_filled": self.fields_filled,
            "fields_total": self.fields_total,
        }


def answered_count(session: GenerationSession) -> int:
    """How many planned questions have been answered.

    Not `len(turns)`. Instructions and pasted notes are stored as turns so the
    chat transcript replays in the order it happened, and counting either would
    advance the question pointer -- one aside would silently skip a question and
    the user would never be asked it.

    Counts what *is* an answer rather than excluding what is not, so a turn kind
    added later is non-advancing by default. Turns written before `kind` existed
    carry none and are answers, which is what the default says.
    """
    return sum(
        1 for turn in session.turns or [] if turn.get("kind", TURN_ANSWER) == TURN_ANSWER
    )


def save_question_plan(
    db: Session,
    version_id: uuid.UUID,
    questions: list[PlannedQuestion],
    *,
    planner_version: str,
) -> bool:
    """Cache the plan for this version, replacing any earlier one.

    Replace rather than merge: `uq_question_plans_version_question` makes a
    partial overwrite a constraint violation, and a plan half from one planner
    version and half from another would be worse than either.

    Returns whether this call is the one that wrote the plan. Two sessions
    started against the same version at the same moment both miss the cache and
    both arrive here, and the loser used to surface as a 500 from that unique
    constraint. It is written inside a savepoint so the loser can roll back its
    own insert alone and read the winner's plan instead -- a caller's other
    pending work is untouched either way.
    """
    try:
        with db.begin_nested():
            existing = db.execute(
                select(QuestionPlan).where(QuestionPlan.version_id == version_id)
            ).scalars().all()
            for row in existing:
                db.delete(row)
            db.flush()

            for question in questions:
                db.add(
                    QuestionPlan(
                        id=uuid.uuid4(),
                        version_id=version_id,
                        question_no=question.question_no,
                        question_text=question.question_text,
                        hint=question.hint,
                        example=question.example,
                        covers_regions=list(question.covers_regions),
                        planner_version=planner_version,
                    )
                )
            db.flush()
    except IntegrityError:
        logger.warning(
            "another session cached a plan for version %s first; keeping theirs", version_id
        )
        return False
    return True


def load_question_plan(
    db: Session, version_id: uuid.UUID, *, include_fallback: bool = True
) -> list[PlannedQuestion]:
    """The cached plan for a version, or `[]`.

    A cache hit is what makes the second session against a document cost zero
    planner calls, and what keeps the questions stable when Bedrock is not
    reachable.

    `include_fallback=False` treats a plan written by the structural fallback as
    a miss. That is for `POST /sessions` only: a plan computed while the model
    was unreachable is a degraded product, and serving it from cache forever
    would mean one outage permanently downgrades every future interview on that
    document. An in-flight session must keep the questions it started with, so
    every other call site takes the default and gets the cached plan whatever
    produced it.
    """
    rows = (
        db.execute(
            select(QuestionPlan)
            .where(QuestionPlan.version_id == version_id)
            .order_by(QuestionPlan.question_no)
        )
        .scalars()
        .all()
    )
    if rows and not include_fallback and rows[0].planner_version == FALLBACK_PLANNER_VERSION:
        logger.info(
            "version %s has only a structural-fallback plan; re-planning with the model",
            version_id,
        )
        return []
    return [
        PlannedQuestion(
            question_no=row.question_no,
            question_text=row.question_text,
            hint=row.hint,
            example=row.example,
            covers_regions=list(row.covers_regions or []),
        )
        for row in rows
    ]


def freeze_ask_plan(
    questions: list[PlannedQuestion], prefilled: set[str]
) -> dict[str, Any]:
    """The interview THIS session will run, decided once and never again.

    A question keeps its cached wording and its number. What changes is its
    cluster: regions the user's pasted notes already supplied move out of
    `covers_regions` and into `prefilled_regions`, so the question is now only
    about what is genuinely still missing, and the screen can show what it
    already has.

    **No question is ever dropped, even when the notes supplied every region it
    covered.** Dropping it is the shorter interview and the wrong trade: the
    question that covers a region is the only place a mis-extraction becomes
    visible, so removing it deletes exactly the audit that would have caught it.
    A fully-supplied question is shown with an empty cluster and confirmed in one
    click. Keeping them also means the ask-list is never empty, which is what
    lets the deriver keep firing on the last answer as it always has.

    **The whole payload is frozen, not just the numbers.** `save_question_plan`
    replaces a version's rows wholesale, and `POST /sessions` triggers exactly
    that whenever the cached plan is a structural fallback -- so storing indices
    would let another session shorten this one's list, or change its wording,
    underneath a positional pointer. The per-version cache still earns its keep:
    what it saves is the planner *model call*, not a row read.
    """
    return {
        _ASK_PLAN_KEY: [
            {
                "question_no": q.question_no,
                "question_text": q.question_text,
                "hint": q.hint,
                "example": q.example,
                "covers_regions": [r for r in q.covers_regions if r not in prefilled],
                "prefilled_regions": [r for r in q.covers_regions if r in prefilled],
            }
            for q in questions
        ]
    }


def session_questions(session: GenerationSession, db: Session) -> list[PlannedQuestion]:
    """The questions this session asks, in order, stable for its whole life.

    Deliberately **not** recomputed from `filled_values`. That set grows on every
    turn -- `record_turn` merges both `extracted` and `volunteered` -- and again
    on every review-screen `PATCH /spec/{i}`. `_current` is positional, so a live
    predicate over it would reorder this list mid-interview: answer q2, the list
    becomes [q3, q5], `answered_count` is 1, and `questions[1]` is q5 -- q3 is
    never asked at all.

    Sessions created before the ask plan existed have no frozen payload and fall
    back to the version's cached plan, which is exactly what they ran on.
    """
    rows = (session.known_context or {}).get(_ASK_PLAN_KEY)
    if not isinstance(rows, list):
        return load_question_plan(db, session.base_version_id)

    # Reconstructed field by field, never `PlannedQuestion(**row)`: `as_dict()`
    # emits `question_id`, which is a property rather than a dataclass field, so
    # splatting a round-tripped dict raises TypeError.
    return [
        PlannedQuestion(
            question_no=int(row["question_no"]),
            question_text=row["question_text"],
            hint=row.get("hint"),
            example=row.get("example"),
            covers_regions=list(row.get("covers_regions") or []),
            prefilled_regions=list(row.get("prefilled_regions") or []),
        )
        for row in rows
        if isinstance(row, dict) and "question_no" in row and "question_text" in row
    ]


def record_turn(
    session: GenerationSession,
    *,
    question_id: str,
    question_text: str,
    answer: str,
    extracted: dict[str, Any],
    volunteered: dict[str, Any] | None = None,
    kind: str = TURN_ANSWER,
    skipped: bool = False,
    degraded: bool = False,
) -> None:
    """Append one turn and merge its values into `filled_values`.

    `extracted` is what the question asked for; `volunteered` is what the same
    message supplied about the rest of the document. Both are the user's own
    words and both are written -- they are stored apart so a reloaded chat can
    still show which was which, and so the two counts are separable in a log.

    The raw answer is stored **whether or not extraction worked**. A turn whose
    extractor call failed is not lost -- the user's words are on the record and
    can be re-extracted later, which is a far better outage story than asking
    them the same question twice.

    JSONB columns are reassigned rather than mutated in place: SQLAlchemy does
    not track mutation inside a JSONB value, and an in-place `append` would be
    silently discarded on commit. This has bitten this codebase before.
    """
    volunteered = volunteered or {}
    turns = list(session.turns or [])
    turns.append(
        {
            "kind": kind,
            "question_id": question_id,
            "question_text": question_text,
            "answer": answer,
            "extracted": extracted,
            "volunteered": volunteered,
            "skipped": skipped,
            "degraded": degraded,
        }
    )
    session.turns = turns

    if extracted or volunteered:
        filled = dict(session.filled_values or {})
        # Volunteered first, so a region named in both keeps the value the
        # question was actually about.
        filled.update(volunteered)
        filled.update(extracted)
        session.filled_values = filled

    session.current_step = answered_count(session)
