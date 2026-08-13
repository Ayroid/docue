"""LLM pass A: the semantic layer over a structural schema (plan §10 ①).

The detector already knows *what shape* every region is and *whether it is safe
to write*. Neither of those is asked of the model here, and that is the whole
design: structure decides mechanics, the model decides meaning, and the two
never trade places. A model that could reclassify `kind` could turn the logo
into a field.

Three properties hold, and each is enforced in code rather than asked for in
the prompt -- a prompt is a request, and this is a document nobody gets to
corrupt:

1. **Unknown `region_id`s are dropped, not guessed.** Plan §3.2's injection
   barrier. The model is given ids and may only return ids; anything else is
   discarded and counted.
2. **Classification can only narrow write permission, never widen it.** A
   region the detector marked `protected` or non-editable stays that way no
   matter what comes back. The model *can* take editability away
   (`should_not_write`), because "this looks like a form identifier" is exactly
   the judgement structure can't make.
3. **Failure leaves the structural schema standing.** No exception escapes to
   the caller; regions simply keep their deterministic labels. The plan's
   fallback for this stage is "mark the region unknown and leave it untouched",
   and 98.6% structural recall means the floor is already high.

Typed against `object` for the schema, like `protected_targets_from_schema` in
the compilers: this reads `.regions` and the fields contract C3 freezes, so it
works on the xlsx, docx and pptx schemas without importing any of them.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import CLASSIFIER_SYSTEM, CLASSIFIER_VERSION

logger = logging.getLogger(__name__)

__all__ = ["ClassificationResult", "RegionLabel", "classify_regions"]

# One request per this many regions. The corpus tops out at 61 (the BRD), which
# fits in a single call -- the batch exists so a 300-region document degrades
# into several calls instead of one truncated one.
BATCH_SIZE = 40

_VALUE_TYPES = ["string", "number", "date", "mixed", "none"]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string"},
                    "semantic_role": {"type": "string"},
                    "label": {"type": "string"},
                    "value_type": {"type": "string", "enum": _VALUE_TYPES},
                    "required": {"type": "boolean"},
                    "should_not_write": {"type": "boolean"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "region_id",
                    "semantic_role",
                    "label",
                    "value_type",
                    "required",
                    "should_not_write",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["regions"],
    "additionalProperties": False,
}


@dataclass
class RegionLabel:
    """What the model added to one region. Maps onto `document_regions` columns."""

    region_id: str
    semantic_role: str
    label: str
    value_type: str
    required: bool
    should_not_write: bool
    confidence: float


@dataclass
class ClassificationResult:
    labels: dict[str, RegionLabel] = field(default_factory=dict)
    dropped_ids: list[str] = field(default_factory=list)
    refused_writes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def apply_to(self, schema: Any) -> int:
        """Write the labels onto the schema's regions, in place.

        Returns how many regions were touched. `editable` is only ever moved
        towards False -- see the module docstring.
        """
        touched = 0
        for region in schema.regions:
            label = self.labels.get(region.region_id)
            if label is None:
                continue
            region.notes["semantic_role"] = label.semantic_role
            region.notes["llm_confidence"] = label.confidence
            region.notes["classified_by"] = CLASSIFIER_VERSION
            if label.label:
                region.label = label.label
            if label.value_type != "none":
                region.value_type = label.value_type
            region.required = label.required
            if label.should_not_write and region.editable:
                region.editable = False
                region.notes["not_writable_reason"] = f"llm: {label.semantic_role}"
            touched += 1
        return touched


def _region_payload(region: Any) -> dict[str, Any]:
    """What the model sees of one region.

    Deliberately not the whole region: `notes` carries compiler bookkeeping
    (cell refs, template rows, count templates) that is noise for a semantic
    judgement and would crowd out the content. Column names go in because a
    table's header row is the strongest signal of what the table is for.
    """
    locator = region.locator
    payload = {
        "region_id": region.region_id,
        "kind": region.kind,
        "label": region.label,
        "where": getattr(locator, "ref", "") or "",
        "editable": region.editable,
    }
    content = (region.current_content or "").strip()
    if content:
        payload["current_content"] = content[:400]
    columns = region.notes.get("columns")
    if columns:
        payload["columns"] = [c["name"] for c in columns if c.get("name")][:20]
    for key in ("item_count", "row_count", "label_prefix"):
        if region.notes.get(key) is not None:
            payload[key] = region.notes[key]
    return payload


def _document_payload(schema: Any) -> dict[str, Any]:
    notes = getattr(schema, "notes", {}) or {}
    payload: dict[str, Any] = {"format": schema.format}
    for key in ("house_pattern", "in_doc_version", "form_id"):
        if notes.get(key):
            payload[key] = notes[key]
    sheets = getattr(schema, "sheets", None)
    if sheets:
        payload["sheets"] = [{"name": s.name, "role": s.role} for s in sheets]
    slides = getattr(schema, "slides", None)
    if slides:
        payload["slides"] = [{"index": s.index, "title": s.title} for s in slides]
    return payload


def classify_regions(
    schema: Any, *, filename: str | None = None, batch_size: int = BATCH_SIZE
) -> ClassificationResult:
    """Label every region of a detected schema. Never raises.

    The caller gets a result either way; `ok` says whether the model
    contributed. Ingestion is expected to call `apply_to` regardless -- an
    empty result applies nothing and the structural schema stands.
    """
    result = ClassificationResult()
    regions = list(schema.regions)
    if not regions:
        return result

    known_ids = {region.region_id for region in regions}
    document = _document_payload(schema)
    if filename:
        document["filename"] = filename

    for start in range(0, len(regions), batch_size):
        batch = regions[start : start + batch_size]
        user = json.dumps(
            {"document": document, "regions": [_region_payload(r) for r in batch]},
            ensure_ascii=False,
            indent=1,
        )
        try:
            payload = complete_json(
                purpose="classify_regions",
                system=CLASSIFIER_SYSTEM,
                user=user,
                schema=_SCHEMA,
                prompt_version=CLASSIFIER_VERSION,
            )
        except BedrockError as exc:
            # Explicitly swallowed: the structural schema is a usable product on
            # its own, and half a document classified is worse than none.
            logger.warning("region classification batch failed: %s", exc)
            result.errors.append(str(exc))
            continue

        for item in payload.get("regions", []):
            # Nested item shape is not reliably enforced by the forced tool --
            # see `app/ai/bedrock.py::complete_json`, where a schema declaring
            # objects returned bare strings against real Bedrock. A malformed
            # entry leaves its region with the structural label it already had,
            # which is this stage's documented failure mode anyway.
            if not isinstance(item, dict):
                result.errors.append("classifier returned a malformed entry")
                continue
            region_id = item.get("region_id")
            if not isinstance(region_id, str) or region_id not in known_ids:
                # The injection barrier doing its job -- log it, never resolve it
                # to "the closest match".
                result.dropped_ids.append(str(region_id))
                continue
            try:
                label = RegionLabel(
                    region_id=region_id,
                    semantic_role=str(item["semantic_role"]),
                    label=str(item["label"]),
                    value_type=str(item["value_type"]),
                    required=bool(item["required"]),
                    should_not_write=bool(item["should_not_write"]),
                    confidence=float(item["confidence"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                result.errors.append(f"classifier entry for {region_id} was unusable: {exc}")
                continue
            result.labels[region_id] = label
            if label.should_not_write:
                result.refused_writes.append(region_id)

    if result.dropped_ids:
        logger.warning(
            "dropped %d unknown region_id(s) from the classifier: %s",
            len(result.dropped_ids),
            result.dropped_ids[:8],
        )
    return result
