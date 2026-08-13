"""Stage ④ — the question planner. Plan §10.

At most four questions, each covering a cluster of regions, because the demo
metric is *"four answers filled twenty-six of thirty-one regions"* and a
question-per-field interview would be thirty-one of them.

**Cached per version, not per session** (plan §8's `question_plans`). The
questions to ask about a document are a property of the document, so the second
session against the same version costs zero model calls. That is also the §14
outage story: a plan computed once keeps working when Bedrock does not, which
matters more on a demo day than it does in production.

The deterministic fallback is a real product, not a stub. Regions already carry
`question_group` from detection, so grouping by it and asking for each group's
labels produces a serviceable interview with no model at all -- which is the
plan's hour-14 fallback (§12) available from hour zero.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import PLANNER_SYSTEM, PLANNER_VERSION

logger = logging.getLogger(__name__)

__all__ = ["PlannedQuestion", "QuestionPlanResult", "plan_questions"]

MAX_QUESTIONS = 4

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "maxItems": MAX_QUESTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "question_text": {"type": "string"},
                    "hint": {"type": "string"},
                    "example": {"type": "string"},
                    "covers_regions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question_text", "hint", "example", "covers_regions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


@dataclass
class PlannedQuestion:
    """One question and the region cluster it supplies.

    `covers_regions` is later handed to the extractor as the *only* keys it may
    return, so a question that covers nothing is worse than useless -- it would
    let an answer through with nowhere to put it. Such questions are dropped.
    """

    question_no: int
    question_text: str
    hint: str | None = None
    example: str | None = None
    covers_regions: list[str] = field(default_factory=list)

    @property
    def question_id(self) -> str:
        return f"q{self.question_no}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question_no": self.question_no,
            "question_text": self.question_text,
            "hint": self.hint,
            "example": self.example,
            "covers_regions": list(self.covers_regions),
        }


@dataclass
class QuestionPlanResult:
    questions: list[PlannedQuestion] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    planner_version: str = PLANNER_VERSION

    @property
    def ok(self) -> bool:
        return not self.errors


def _region_payload(region: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "region_id": region.region_id,
        "kind": region.kind,
        "label": region.label or "",
        "required": bool(region.required),
    }
    role = (region.notes or {}).get("semantic_role")
    if role:
        payload["semantic_role"] = role
    if region.value_type:
        payload["value_type"] = region.value_type
    columns = (region.notes or {}).get("columns")
    if columns:
        payload["columns"] = [c["name"] for c in columns if c.get("name")][:20]
    return payload


def _group_key(region: Any) -> tuple[int, str]:
    """A stable grouping for the fallback, from what the schema actually carries.

    Contract C3's `Region` has no `question_group` -- that column exists on
    `document_regions`, filled after detection -- so the grouping comes from the
    locator's container: the sheet for a workbook, the slide for a deck, one
    body for a docx. Regions that live together are asked about together, which
    is the same instinct the model applies with better wording.

    Tables sort last within a container. They are the slowest thing to answer,
    and a user who abandons the interview early should have lost the least.
    """
    locator = region.locator
    container = (
        getattr(locator, "sheet", None)
        or getattr(locator, "slide_index", None)
        or getattr(locator, "part", None)
        or ""
    )
    heavy = region.kind in ("table_loop", "table_data", "repeating_block")
    return (1 if heavy else 0, str(container))


def _fallback(regions: list[Any]) -> list[PlannedQuestion]:
    """Group structurally, capped at four questions.

    The wording is mechanical -- "Please provide: Venue, Date, Attendees" -- but
    the coverage is exactly right, and the extractor still parses a free-form
    answer against the cluster, so the experience degrades far less than the
    phrasing suggests. This is plan §12's hour-14 fallback, available from hour
    zero rather than written under pressure at 3am.
    """
    groups: dict[tuple[int, str], list[Any]] = {}
    for region in regions:
        groups.setdefault(_group_key(region), []).append(region)

    ordered = sorted(groups.items(), key=lambda kv: kv[0])
    questions: list[PlannedQuestion] = []

    # More groups than we are allowed questions: the tail is merged into the
    # last one rather than dropped, because an ugly question still collects the
    # value and a dropped region is a blank in the document.
    if len(ordered) > MAX_QUESTIONS:
        head = ordered[: MAX_QUESTIONS - 1]
        tail: list[Any] = []
        for _, members in ordered[MAX_QUESTIONS - 1 :]:
            tail.extend(members)
        ordered = head + [("rest", tail)]

    for number, (_, members) in enumerate(ordered, start=1):
        labels = [m.label or m.region_id for m in members]
        shown = ", ".join(labels[:6]) + ("…" if len(labels) > 6 else "")
        questions.append(
            PlannedQuestion(
                question_no=number,
                question_text=f"Please provide: {shown}",
                hint="Answer in your own words — everything in one message is fine.",
                example=None,
                covers_regions=[m.region_id for m in members],
            )
        )
    return questions


def plan_questions(
    schema: Any,
    region_ids: list[str],
    *,
    template_meta: dict[str, Any] | None = None,
    intent: str | None = None,
) -> QuestionPlanResult:
    """Plan ≤4 questions over `region_ids`. Never raises.

    `region_ids` is the context agent's `must_ask` + `inferable`: the regions
    worth a user's attention. Everything else was already settled upstream.
    """
    result = QuestionPlanResult()
    by_id = {r.region_id: r for r in schema.regions}
    regions = [by_id[rid] for rid in region_ids if rid in by_id]
    if not regions:
        return result

    known_ids = {r.region_id for r in regions}
    document: dict[str, Any] = {"format": schema.format}
    for key in ("title", "purpose"):
        value = (template_meta or {}).get(key)
        if value:
            document[key] = value
    if intent:
        document["user_intent"] = intent

    user = json.dumps(
        {"document": document, "regions": [_region_payload(r) for r in regions]},
        ensure_ascii=False,
        indent=1,
    )
    try:
        payload = complete_json(
            purpose="plan_questions",
            system=PLANNER_SYSTEM,
            user=user,
            schema=_SCHEMA,
            prompt_version=PLANNER_VERSION,
        )
    except BedrockError as exc:
        logger.warning("question planning failed, using the structural grouping: %s", exc)
        result.errors.append(str(exc))
        result.questions = _fallback(regions)
        return result

    claimed: set[str] = set()
    for item in payload.get("questions", [])[:MAX_QUESTIONS]:
        covers: list[str] = []
        for region_id in item.get("covers_regions", []):
            if region_id not in known_ids:
                result.dropped_ids.append(region_id)
                continue
            # A region claimed by two questions would be asked twice and
            # extracted twice, with the second answer silently winning. First
            # question keeps it.
            if region_id in claimed:
                continue
            claimed.add(region_id)
            covers.append(region_id)
        if not covers:
            continue
        result.questions.append(
            PlannedQuestion(
                question_no=len(result.questions) + 1,
                question_text=item["question_text"],
                hint=item.get("hint") or None,
                example=item.get("example") or None,
                covers_regions=covers,
            )
        )

    result.uncovered = [r.region_id for r in regions if r.region_id not in claimed]

    if not result.questions:
        # The model answered, but nothing survived validation. Same outcome as
        # an outage, same fallback.
        logger.warning("planner returned no usable question; using the structural grouping")
        result.errors.append("planner produced no question naming a known region")
        result.questions = _fallback(regions)
        return result

    if result.uncovered:
        # Not an error. These regions simply go unasked, and the deriver gets a
        # chance at them; whatever it cannot fill stays visibly empty.
        logger.info(
            "%d region(s) covered by no question: %s",
            len(result.uncovered),
            result.uncovered[:8],
        )
    if result.dropped_ids:
        logger.warning(
            "dropped %d unknown region_id(s) from the planner: %s",
            len(result.dropped_ids),
            result.dropped_ids[:8],
        )
    return result
