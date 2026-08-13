"""Stage ⑥ — the deriver. Plan §10: *4 answers + context → 26 values*.

The headline metric lives here, and so does the sharpest failure mode in the
system: everything this stage emits is content **nobody typed**. A fabricated
name or date in a document that goes to a client is the failure a Finance judge
will probe, and it is worse than an empty field by a margin that is not close.

Three defences, in order of how much they actually do:

1. **`basis` is required on every value.** The model must name what in the
   supplied data a value came from. This is not decoration -- an entry whose
   basis is empty is dropped here, which makes "I cannot justify this" the
   cheapest path for a model that would otherwise invent something plausible.
2. **`null` is a first-class answer.** The schema takes `value: null` and the
   parser keeps it, so "I considered this region and nothing follows" is
   expressible. Without that, the only way to say nothing is to say something.
3. **Provenance is stamped per value**, so the review screen badges every
   derived field as derived and the user sees exactly which ones no human wrote.

The prose/factual split lives in the prompt because it is a judgement, not a
type: a purpose statement may be *written* from the answers, a date may only be
*restated* from them. Nothing structural distinguishes the two, which is exactly
why a mandatory review screen (plan §14) is not optional.

**Runs once**, when the last question is answered or the spec is first
requested -- never per turn. Plan §6 budgets an answer turn at 1.5s and this
stage reasons over the whole document.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import DERIVER_SYSTEM, DERIVER_VERSION
from app.conversation.values import parse_entries, region_columns, value_entry_schema

logger = logging.getLogger(__name__)

__all__ = ["DerivationResult", "DerivedValue", "derive_values"]

# Everything this stage produces carries this provenance root, so the review
# screen can badge it without inspecting the value.
PROVENANCE = "llm_derived"


@dataclass
class DerivedValue:
    value: Any
    basis: str
    confidence: float
    provenance: str = PROVENANCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "basis": self.basis,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


@dataclass
class DerivationResult:
    """What followed from the answers, and what deliberately did not.

    `considered_empty` is the honest half and is reported, not hidden: these are
    regions the model looked at and had nothing for. The review screen shows
    them as untouched, which is the outcome plan §14 asks for -- an obvious gap
    beats a plausible wrong value.
    """

    values: dict[str, DerivedValue] = field(default_factory=dict)
    considered_empty: list[str] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)
    unjustified: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        """What lands in `generation_sessions.derived_values`."""
        return {
            "values": {rid: dv.as_dict() for rid, dv in self.values.items()},
            "considered_empty": self.considered_empty,
            "unjustified": self.unjustified,
            "dropped_ids": self.dropped_ids,
            "deriver_version": DERIVER_VERSION,
            "degraded": bool(self.errors),
        }


def _region_payload(region: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "region_id": region.region_id,
        "kind": region.kind,
        "label": region.label or "",
    }
    role = (region.notes or {}).get("semantic_role")
    if role:
        payload["semantic_role"] = role
    if region.value_type:
        payload["value_type"] = region.value_type
    content = (region.current_content or "").strip()
    if content:
        # The existing content is shown as register guidance -- what this region
        # normally reads like -- not as a value to copy.
        payload["current_content"] = content[:300]
    columns = region_columns(region)
    if columns:
        payload["columns"] = columns[:20]
    return payload


def derive_values(
    schema: Any,
    target_region_ids: list[str],
    filled_values: dict[str, Any],
    *,
    turns: list[dict[str, Any]] | None = None,
    template_meta: dict[str, Any] | None = None,
    intent: str | None = None,
    today: date | None = None,
) -> DerivationResult:
    """Fill `target_region_ids` from what the user already supplied. Never raises.

    On failure nothing is derived and `ok` is false -- the document is then
    exactly what the user typed, which is a smaller product and a correct one.
    """
    result = DerivationResult()
    by_id = {r.region_id: r for r in schema.regions}
    targets = [
        by_id[rid]
        for rid in target_region_ids
        # Already supplied by an answer: deriving over it would let a model
        # overwrite something the user typed, which is never right.
        if rid in by_id and rid not in filled_values
    ]
    if not targets:
        return result

    # What the user actually said, labelled. Sent as data, delimiter-wrapped by
    # being JSON values rather than interpolated into the instruction text.
    supplied = [
        {
            "region_id": region_id,
            "label": (by_id[region_id].label if region_id in by_id else region_id) or region_id,
            "value": value,
        }
        for region_id, value in filled_values.items()
    ]

    document: dict[str, Any] = {
        "format": schema.format,
        "today": (today or date.today()).isoformat(),
    }
    for key in ("title", "purpose", "audience"):
        value = (template_meta or {}).get(key)
        if value:
            document[key] = value
    if intent:
        document["user_intent"] = intent

    user = json.dumps(
        {
            "document": document,
            "answers": [
                {"question": t.get("question_text", ""), "answer": t.get("answer", "")}
                for t in (turns or [])
            ],
            "supplied_values": supplied,
            "regions_to_fill": [_region_payload(r) for r in targets],
        },
        ensure_ascii=False,
        indent=1,
    )

    schema_json = value_entry_schema(
        [r.region_id for r in targets],
        extra_properties={
            "basis": {
                "type": "string",
                "description": "What in the supplied data this came from. Required.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    )
    # The deriver is the one caller that must be able to say "nothing follows",
    # so an explicit null is legal here and nowhere else.
    schema_json["properties"]["entries"]["items"]["properties"]["value"] = {
        "type": ["string", "null"]
    }

    try:
        payload = complete_json(
            purpose="derive_values",
            system=DERIVER_SYSTEM,
            user=user,
            schema=schema_json,
            prompt_version=DERIVER_VERSION,
        )
    except BedrockError as exc:
        logger.warning("derivation failed; keeping only what the user typed: %s", exc)
        result.errors.append(str(exc))
        return result

    columns = {r.region_id: cols for r in targets if (cols := region_columns(r))}
    parsed, result.dropped_ids = parse_entries(
        payload, {r.region_id for r in targets}, columns, keep_null=True
    )

    # Same defensive read as everywhere else in this package: nested item shape
    # is not guaranteed (see `app/ai/bedrock.py::complete_json`). An entry with
    # no readable basis loses its value below, which is the intended direction.
    entries = [e for e in payload.get("entries", []) if isinstance(e, dict)]
    basis_by_id = {e.get("region_id"): str(e.get("basis") or "").strip() for e in entries}
    confidence_by_id = {e.get("region_id"): e.get("confidence") for e in entries}

    for region_id, value in parsed.items():
        if value is None:
            result.considered_empty.append(region_id)
            continue
        basis = basis_by_id.get(region_id, "")
        if not basis:
            # No justification, no value. Making this the cheap path is the
            # point: a model with nothing to cite should return null, and one
            # that invents anyway loses the value here rather than in the file.
            result.unjustified.append(region_id)
            continue
        raw = confidence_by_id.get(region_id)
        try:
            confidence = min(1.0, max(0.0, float(raw)))
        except (TypeError, ValueError):
            confidence = 0.0
        result.values[region_id] = DerivedValue(
            value=value, basis=basis[:300], confidence=confidence
        )

    if result.unjustified:
        logger.warning(
            "dropped %d derived value(s) with no basis: %s",
            len(result.unjustified),
            result.unjustified[:8],
        )
    logger.info(
        "derived %d value(s) over %d target region(s); %d left empty%s",
        len(result.values),
        len(targets),
        len(result.considered_empty),
        " (degraded)" if result.errors else "",
    )
    return result
