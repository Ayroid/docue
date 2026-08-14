"""Stage ⑤ — the answer extractor. Plan §10.

One free-form message in, `{region_id: value}` out. This is the stage that lets
a user answer

    "Cycle 2 of the AP automation workshop, we agreed to make attachments
     mandatory for revaluation and disposal, Ravi's sharing the header field
     mapping by Friday, and Priya's setting up the next session."

instead of filling four boxes.

**Scoped to the document, not to the question.** The enum handed to the model is
every region the user is allowed to reach (`scope.addressable`), split in the
prompt into the cluster the question asked about and the rest of the document.
It used to be `question.covers_regions` alone, which had a cost that only shows
up in use: everything else a person said in the same breath was parsed, matched
to nothing, and dropped in silence. Asking about the venue and being told "and
Priya is chairing the next one" threw the second half away, and the user found
out on the review screen or not at all.

Two things follow from the wider enum, and both are the point:

* **Volunteered values are kept.** They come back separately from the answered
  cluster so the caller can badge them -- the user sees *"also captured: Next
  meeting chair → Priya"* rather than having to trust it.
* **An instruction is a value.** "Change the heading to Q3 Review" names a
  region and supplies its content, which is all this stage has ever done. What
  makes that safe is not narrowness here, it is that the enum only ever contains
  ids the detector found in these bytes, and `plan_change_spec` and the
  compilers each refuse a non-editable or protected target again downstream.

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

# How much of a region's existing content the model is shown, so it can resolve
# "change Conference Room 4 to Room 2" onto the region that holds it. Truncated
# hard for the same reason the context agent truncates: one 4,000-character
# block of minutes would crowd out every other region in the document.
CONTENT_PREVIEW = 140

# A ceiling on the enum. The corpus tops out at 61 regions so this is not
# reachable today; it exists so a 900-region workbook degrades to "the question's
# cluster plus the first N" rather than to one enormous unusable call.
MAX_ADDRESSABLE = 150


@dataclass
class ExtractionResult:
    """What one message supplied.

    `values` may legitimately be smaller than the cluster -- a user who answers
    three of four things has supplied three values. The fourth is absent, which
    the review screen shows as an untouched region rather than filling.

    `volunteered` is everything the message supplied that the question did not
    ask for. It is kept apart from `values` only so the caller can say so; both
    are the user's own words and both are written.
    """

    values: dict[str, Any] = field(default_factory=dict)
    volunteered: dict[str, Any] = field(default_factory=dict)
    dropped_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def all_values(self) -> dict[str, Any]:
        """Everything the message supplied, asked-for or not.

        The answered cluster wins a collision, which cannot currently happen --
        the two dicts are built from disjoint id sets -- but stating it here
        means a future change to that split fails safe.
        """
        return {**self.volunteered, **self.values}

    def chips(self, labels: dict[str, str]) -> list[dict[str, str]]:
        """`[{key, value, source}]` for the chip row under the user's message.

        Table values are summarised by row count rather than serialised: three
        action rows are `3 rows`, because the chip row is a confirmation glance,
        not the review screen.

        `source` distinguishes what the question asked for from what the user
        volunteered. Rendering the two identically would mean a value that
        landed somewhere they were not looking is indistinguishable from one
        they were watching for -- and a wrong guess about which region an aside
        belonged to would be invisible until the document was built.
        """
        out: list[dict[str, str]] = []
        for source, values in (("answer", self.values), ("volunteered", self.volunteered)):
            for region_id, value in values.items():
                if isinstance(value, list):
                    shown = f"{len(value)} row{'s' if len(value) != 1 else ''}"
                else:
                    text = str(value)
                    shown = text if len(text) <= 60 else text[:57] + "…"
                out.append(
                    {
                        "key": labels.get(region_id, region_id),
                        "value": shown,
                        "source": source,
                    }
                )
        return out


def _region_payload(region: Any, *, with_content: bool = False) -> dict[str, Any]:
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
    if with_content:
        content = (region.current_content or "").strip()
        if content:
            # What the region holds today. This is what lets "change Conference
            # Room 4 to Room 2" resolve onto a region whose *label* says nothing
            # about Conference Room 4 -- which is the normal case when the base
            # document is an already-filled copy rather than a blank form.
            payload["current_content"] = content[:CONTENT_PREVIEW]
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
    also_regions: list[str] | None = None,
    question_text: str | None = None,
    today: date | None = None,
) -> ExtractionResult:
    """Pull values out of `answer`. Never raises.

    `covers_regions` is what the question asked about; `also_regions` is the
    rest of the document the user is allowed to reach. Values for the first land
    in `values`, values for the second in `volunteered`. Both are written by the
    caller -- the split is for reporting, not for filtering.

    On failure the result is empty and `ok` is false. The caller still records
    the turn -- the user's words are kept whether or not a model was available
    to read them, so the answer can be re-extracted later rather than re-asked.
    """
    result = ExtractionResult()
    text = (answer or "").strip()
    if not text:
        return result

    by_id = {r.region_id: r for r in schema.regions}
    asked = [by_id[rid] for rid in covers_regions if rid in by_id]
    asked_ids = {r.region_id for r in asked}

    rest: list[Any] = []
    for region_id in also_regions or []:
        region = by_id.get(region_id)
        if region is not None and region_id not in asked_ids:
            rest.append(region)

    budget = max(0, MAX_ADDRESSABLE - len(asked))
    if len(rest) > budget:
        # Reported, not silent. A truncated vocabulary means a value the user
        # supplied may have nowhere to go, and a log line is the only place that
        # is visible from.
        logger.warning(
            "%d addressable region(s) exceeds the %d cap; %d were not offered "
            "to the extractor this turn",
            len(rest) + len(asked),
            MAX_ADDRESSABLE,
            len(rest) - budget,
        )
        rest = rest[:budget]

    regions = asked + rest
    if not regions:
        return result

    user = json.dumps(
        {
            "question": question_text or "",
            "answer": text,
            "today": (today or date.today()).isoformat(),
            "asked_about": [_region_payload(r) for r in asked],
            "rest_of_document": [_region_payload(r, with_content=True) for r in rest],
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

    values, result.dropped_ids = parse_entries(
        payload, {r.region_id for r in regions}, _columns_by_region(regions)
    )
    for region_id, value in values.items():
        if region_id in asked_ids:
            result.values[region_id] = value
        else:
            result.volunteered[region_id] = value

    logger.info(
        "extracted %d/%d asked region(s) and %d volunteered from a %d-character answer",
        len(result.values),
        len(asked),
        len(result.volunteered),
        len(text),
    )
    return result
