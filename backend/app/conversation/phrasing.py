"""Say the next question the way a person would, given what is already known.

The planner decides *what* the interview covers, once per document, cached per
version. That is the right shape: coverage is a property of the template, and
the plan is what keeps the interview to the three or four questions the PS asks
for. What it cannot be is *responsive* -- it was written before the user said
anything, and it is served identically to everyone.

So the plan keeps deciding the cluster, and this stage decides the sentence, one
question at a time, at the moment it is put. It sees what the notes and the
earlier answers already supplied and what the user last said, and rewrites
accordingly:

    planned:  "When and where was this meeting, what was its purpose, and who
               prepared these minutes?"
    asked:    "I have the date and venue from your notes. What was the purpose,
               and who's writing these up?"

That is the whole difference between an interview and a conversation, and it
costs one small model call on a turn the user is already waiting through.

**It cannot change what a question covers.** `covers_regions` is set by the
planner and narrowed by the notes; this stage returns a string and nothing else.
A rewrite that wandered onto another region would be a question whose answer has
nowhere to go -- so the opportunity is simply not offered. Same reason the
extractor gets an enum rather than a promise.

Fails to the planned wording, always. A question phrased by the planner is a
worse sentence, not a broken interview, so an outage here costs tone.
"""

import json
import logging
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import PHRASING_SYSTEM, PHRASING_VERSION

logger = logging.getLogger(__name__)

__all__ = ["rephrase"]

# Short by construction. The output is one sentence and a hint; anything longer
# is the model writing an essay at the user, which is the failure mode this
# stage introduces if it is left unbounded.
MAX_TOKENS = 400

# How much of a known value the model is shown. Enough to say "I have Conference
# Room 7" and not enough for a page of minutes to crowd out the question.
VALUE_PREVIEW = 60

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question_text": {"type": "string"},
        "hint": {"type": "string"},
    },
    "required": ["question_text"],
    "additionalProperties": False,
}


def _known(schema: Any, filled: dict[str, Any], region_ids: list[str]) -> list[dict[str, str]]:
    labels = {r.region_id: (r.label or r.region_id) for r in schema.regions}
    out: list[dict[str, str]] = []
    for region_id in region_ids:
        if region_id not in filled:
            continue
        value = filled[region_id]
        shown = (
            f"{len(value)} row(s) already captured"
            if isinstance(value, list)
            else str(value)[:VALUE_PREVIEW]
        )
        out.append({"field": labels.get(region_id, region_id), "value": shown})
    return out


def rephrase(
    schema: Any,
    question: Any,
    *,
    filled: dict[str, Any],
    turns: list[dict[str, Any]] | None = None,
    template_meta: dict[str, Any] | None = None,
) -> tuple[str, str | None] | None:
    """`(question_text, hint)` for this moment, or None to keep the planned one.

    Never raises. None means "use what the planner wrote", which is also what
    every failure returns.
    """
    still_asking = [r for r in question.covers_regions]
    already = _known(schema, filled, list(question.prefilled_regions) + list(filled))

    # Nothing known and nothing supplied: the planned wording was written for
    # exactly this situation and a model call would only paraphrase it.
    if not already:
        return None

    labels = {r.region_id: (r.label or r.region_id) for r in schema.regions}
    last_said = ""
    for turn in reversed(turns or []):
        if turn.get("answer"):
            last_said = str(turn["answer"])[:400]
            break

    user = json.dumps(
        {
            "document": {
                "title": (template_meta or {}).get("title") or "",
                "purpose": (template_meta or {}).get("purpose") or "",
            },
            "planned_question": question.question_text,
            "planned_hint": question.hint or "",
            "still_needed": [labels.get(r, r) for r in still_asking],
            "already_known": already[:12],
            "user_last_said": last_said,
        },
        ensure_ascii=False,
        indent=1,
    )

    try:
        payload = complete_json(
            purpose="phrase_question",
            system=PHRASING_SYSTEM,
            user=user,
            schema=_SCHEMA,
            prompt_version=PHRASING_VERSION,
            max_tokens=MAX_TOKENS,
        )
    except BedrockError as exc:
        logger.info("phrasing unavailable, keeping the planned wording: %s", exc)
        return None

    text = str(payload.get("question_text") or "").strip()
    if not text:
        return None
    hint = str(payload.get("hint") or "").strip() or None

    # A rewrite that lost the question mark, or ran to a paragraph, is not a
    # question -- keep the planner's, which is at least always one.
    if len(text) > 400:
        logger.info("phrasing returned %d characters; keeping the planned wording", len(text))
        return None

    return text, hint
