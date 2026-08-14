"""Stage ③ — the context agent. Plan §10.

*"This is what makes it 4 questions instead of 31."*

The stage sorts regions into four buckets and **never produces a value**. That
split is the whole safety argument: a mistake here costs an unnecessary question
or an unfilled field, never a wrong figure in a client document. The model that
decides *whether to ask* is structurally incapable of deciding *what the answer
is* -- that is stage ⑤'s job, from something the user actually typed.

The `known` bucket therefore means "the document already carries the right
content, leave it alone", not "we know the value". No value crosses this
boundary, so there is nothing here to hallucinate.

**Deferred:** plan §9's RAG-2 lineage grounding. The context is the base
version's own region content plus the template's metadata; retrieving prior
versions in the same lineage is a later phase. Where that matters is `inferable`
-- with lineage, "action items still open from last session" becomes inferable;
without it, it is `must_ask` or nothing. The bucket is honest either way.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import CONTEXT_SYSTEM, CONTEXT_VERSION
from app.conversation.scope import askable

logger = logging.getLogger(__name__)

__all__ = ["ContextResult", "assemble_context"]

BUCKETS = ("known", "inferable", "must_ask", "not_applicable")

# The same batching reason as the classifier: the corpus tops out at 61 regions,
# which fits one call, but a 300-region document should degrade into several
# calls rather than one truncated one.
BATCH_SIZE = 40

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string"},
                    "bucket": {"type": "string", "enum": list(BUCKETS)},
                    "reason": {"type": "string"},
                },
                "required": ["region_id", "bucket", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["regions"],
    "additionalProperties": False,
}


@dataclass
class ContextResult:
    """Every editable region, in exactly one bucket.

    `must_ask` is the fail-safe: a region the model omitted, or named wrongly,
    or that came back while the call was failing, ends up here. An extra
    question is a mild cost; a silently skipped region is a blank nobody chose.
    """

    known: list[str] = field(default_factory=list)
    inferable: list[str] = field(default_factory=list)
    must_ask: list[str] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    dropped_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def bucket_of(self, region_id: str) -> str | None:
        for name in BUCKETS:
            if region_id in getattr(self, name):
                return name
        return None

    def as_dict(self) -> dict[str, Any]:
        """What lands in `generation_sessions.known_context`."""
        return {
            "known": self.known,
            "inferable": self.inferable,
            "must_ask": self.must_ask,
            "not_applicable": self.not_applicable,
            "reasons": self.reasons,
            "dropped_ids": self.dropped_ids,
            "context_version": CONTEXT_VERSION,
            "degraded": bool(self.errors),
        }


def _askable(schema: Any) -> list[Any]:
    """The regions the interview may raise. See `app.conversation.scope`.

    Non-editable regions are excluded here rather than filtered later, and that
    is not just an optimisation: showing the model a protected region invites it
    to reason about writing one. Branding, formulas, the Instruction sheet and
    anything unclassified never enter the conversation's vocabulary.

    Headings are excluded too, one step further out: they are writable, but only
    when a user says to change one. Bucketing a heading here would put it in
    front of the planner and the deriver, and "invent a title because the
    document has one" is precisely the outcome that costs nothing to prevent.
    """
    return askable(schema)


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
    content = (region.current_content or "").strip()
    if content:
        # Truncated hard: the point is "does this already look filled in?", and
        # a 4,000-character block of minutes crowds out every other region.
        payload["current_content"] = content[:300]
    columns = (region.notes or {}).get("columns")
    if columns:
        payload["columns"] = [c["name"] for c in columns if c.get("name")][:20]
    return payload


def assemble_context(
    schema: Any,
    *,
    template_meta: dict[str, Any] | None = None,
    intent: str | None = None,
    today: date | None = None,
    batch_size: int = BATCH_SIZE,
) -> ContextResult:
    """Partition the askable regions. Never raises.

    On any failure every askable region lands in `must_ask`, which is exactly
    the plan's fallback ladder (§12): the conversation gets longer and stays
    correct.
    """
    result = ContextResult()
    regions = _askable(schema)
    if not regions:
        return result

    known_ids = {r.region_id for r in regions}
    document: dict[str, Any] = {
        "format": schema.format,
        "today": (today or date.today()).isoformat(),
    }
    for key in ("form_id", "house_pattern", "in_doc_version"):
        value = (getattr(schema, "notes", {}) or {}).get(key)
        if value:
            document[key] = value
    for key in ("title", "purpose", "when_to_use", "audience"):
        value = (template_meta or {}).get(key)
        if value:
            document[key] = value
    if intent:
        document["user_intent"] = intent

    seen: set[str] = set()
    for start in range(0, len(regions), batch_size):
        batch = regions[start : start + batch_size]
        user = json.dumps(
            {"document": document, "regions": [_region_payload(r) for r in batch]},
            ensure_ascii=False,
            indent=1,
        )
        try:
            payload = complete_json(
                purpose="assemble_context",
                system=CONTEXT_SYSTEM,
                user=user,
                schema=_SCHEMA,
                prompt_version=CONTEXT_VERSION,
            )
        except BedrockError as exc:
            logger.warning("context batch failed: %s", exc)
            result.errors.append(str(exc))
            continue

        for item in payload.get("regions", []):
            # Nested item shape is not reliably enforced by the forced tool --
            # see `app/ai/bedrock.py::complete_json`. A malformed entry leaves
            # its region unclassified, which the sweep below turns into
            # `must_ask`: the safe direction.
            if not isinstance(item, dict):
                result.errors.append("context agent returned a malformed entry")
                continue
            region_id = item.get("region_id")
            if not isinstance(region_id, str) or region_id not in known_ids:
                # The injection barrier. Logged, never resolved to a near-match.
                result.dropped_ids.append(str(region_id))
                continue
            if region_id in seen:
                continue
            bucket = item.get("bucket")
            if bucket not in BUCKETS:
                result.errors.append(f"context agent returned bucket {bucket!r}")
                continue
            seen.add(region_id)
            getattr(result, bucket).append(region_id)
            reason = item.get("reason")
            if reason:
                result.reasons[region_id] = str(reason)[:200]

    # Anything the model did not place -- omitted, misnamed, or lost to a failed
    # batch -- is asked about. The fail-safe direction is always more questions.
    for region in regions:
        if region.region_id not in seen:
            result.must_ask.append(region.region_id)
            result.reasons.setdefault(region.region_id, "not classified; asking to be safe")

    if result.dropped_ids:
        logger.warning(
            "dropped %d unknown region_id(s) from the context agent: %s",
            len(result.dropped_ids),
            result.dropped_ids[:8],
        )
    logger.info(
        "context: %d known, %d inferable, %d must_ask, %d n/a%s",
        len(result.known),
        len(result.inferable),
        len(result.must_ask),
        len(result.not_applicable),
        " (degraded)" if result.errors else "",
    )
    return result
