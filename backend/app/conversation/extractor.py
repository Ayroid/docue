"""Stage ⑤ — the answer extractor. Plan §10.

One free-form answer in, `{region_id: value}` out, with the keys constrained to
the cluster the question covered. This is the stage that lets a user answer

    "Cycle 2 of the AP automation workshop, we agreed to make attachments
     mandatory for revaluation and disposal, Ravi's sharing the header field
     mapping by Friday, and Priya's setting up the next session."

instead of filling four boxes.

**Constrained to the question's cluster, not to the whole document.** The enum
handed to the model is `question.covers_regions`, so an answer about the venue
cannot land in the approval block even if the model decides it should. That is a
narrower barrier than contract C5 requires and it costs nothing: the planner
already decided which regions this question was for.

Runs once per turn, on the interactive path, and it is the only model call
between the user pressing send and the preview updating -- plan §6 budgets that
turn at 1.5s. The deriver deliberately does *not* run here.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import EXTRACTOR_SYSTEM, EXTRACTOR_VERSION
from app.conversation.values import parse_entries, region_columns, value_entry_schema

logger = logging.getLogger(__name__)

__all__ = ["ExtractionResult", "extract_answer"]


@dataclass
class ExtractionResult:
    """What one answer supplied.

    `values` may legitimately be smaller than the cluster -- a user who answers
    three of four things has supplied three values. The fourth is absent, which
    the review screen shows as an untouched region rather than filling.
    """

    values: dict[str, Any] = field(default_factory=dict)
    dropped_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def chips(self, labels: dict[str, str]) -> list[dict[str, str]]:
        """`[{key, value}]` for the chip row under the user's message.

        Table values are summarised by row count rather than serialised: three
        action rows are `3 rows`, because the chip row is a confirmation glance,
        not the review screen.
        """
        out: list[dict[str, str]] = []
        for region_id, value in self.values.items():
            if isinstance(value, list):
                shown = f"{len(value)} row{'s' if len(value) != 1 else ''}"
            else:
                text = str(value)
                shown = text if len(text) <= 60 else text[:57] + "…"
            out.append({"key": labels.get(region_id, region_id), "value": shown})
        return out


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
    columns = region_columns(region)
    if columns:
        payload["columns"] = columns[:20]
    return payload


def _columns_by_region(regions: list[Any]) -> dict[str, list[str]]:
    return {r.region_id: cols for r in regions if (cols := region_columns(r))}


def extract_answer(
    schema: Any,
    answer: str,
    covers_regions: list[str],
    *,
    question_text: str | None = None,
    today: date | None = None,
) -> ExtractionResult:
    """Pull values for `covers_regions` out of `answer`. Never raises.

    On failure the result is empty and `ok` is false. The caller still records
    the turn -- the user's words are kept whether or not a model was available
    to read them, so the answer can be re-extracted later rather than re-asked.
    """
    result = ExtractionResult()
    text = (answer or "").strip()
    if not text or not covers_regions:
        return result

    by_id = {r.region_id: r for r in schema.regions}
    regions = [by_id[rid] for rid in covers_regions if rid in by_id]
    if not regions:
        return result

    user = json.dumps(
        {
            "question": question_text or "",
            "answer": text,
            "today": (today or date.today()).isoformat(),
            "regions": [_region_payload(r) for r in regions],
        },
        ensure_ascii=False,
        indent=1,
    )
    try:
        payload = complete_json(
            purpose="extract_answer",
            system=EXTRACTOR_SYSTEM,
            user=user,
            schema=value_entry_schema([r.region_id for r in regions]),
            prompt_version=EXTRACTOR_VERSION,
        )
    except BedrockError as exc:
        logger.warning("answer extraction failed; keeping the raw turn: %s", exc)
        result.errors.append(str(exc))
        return result

    result.values, result.dropped_ids = parse_entries(
        payload, {r.region_id for r in regions}, _columns_by_region(regions)
    )
    logger.info(
        "extracted %d/%d region(s) from a %d-character answer",
        len(result.values),
        len(regions),
        len(text),
    )
    return result
