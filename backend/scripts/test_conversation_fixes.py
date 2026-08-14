"""The conversation fixes that a live run cannot reach. No model, no database.

    uv run python scripts/test_conversation_fixes.py

`live_e2e_fixes.py` proves the endpoints enforce the rules; `test_dropped_
assertions.py` proves the compiler's. What is left are the branches that only
open when the model misbehaves -- a duplicated entry, four malformed questions,
a Bedrock outage -- which is exactly the set you cannot arrange by talking to a
healthy API. Each is driven here by handing the parsing layer the payload it
would have received.

Covers:
  * the structural fallback is labelled, so it is not cached as a real plan
  * the question cap counts questions accepted, not entries offered
  * a duplicated `region_id` keeps value and basis from the *same* entry
  * rows whose columns are all unknown are warned about, not silently dropped
  * the Bedrock call log is a bounded window, not a leak
"""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import bedrock  # noqa: E402
from app.ai.bedrock import BedrockError  # noqa: E402
from app.conversation.deriver import derive_values  # noqa: E402
from app.conversation.planner import (  # noqa: E402
    FALLBACK_PLANNER_VERSION,
    QUESTION_CEILING,
    plan_questions,
    question_budget,
)
from app.conversation.values import parse_entries, region_columns  # noqa: E402
from app.ingestion.detect import detect  # noqa: E402

FILES = Path(__file__).resolve().parent.parent.parent / "Files"
SOURCE = FILES / "MOM Sample.xlsx"

passed: list[str] = []


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


def _regions():
    """`(schema, editable regions, their ids)` -- the planner and deriver take ids."""
    schema = detect(SOURCE.read_bytes(), "xlsx")
    editable = [r for r in schema.regions if r.editable and not r.protected]
    return schema, editable, [r.region_id for r in editable]


def _fallback_is_labelled(schema, ids) -> None:
    """A plan built during an outage must not wear the healthy version string."""
    # `BedrockError` specifically: that is what an outage actually raises and
    # what the planner catches. A bare RuntimeError would escape, which is a
    # deliberate distinction and not one this test should paper over.
    with patch(
        "app.conversation.planner.complete_json",
        side_effect=BedrockError("bedrock unreachable"),
    ):
        result = plan_questions(schema, ids)

    assert result.questions, "the fallback produced no questions at all"
    assert result.planner_version == FALLBACK_PLANNER_VERSION, (
        f"a fallback plan is labelled {result.planner_version!r}; it would be "
        "cached and served as a real plan forever"
    )
    assert result.errors, "the fallback recorded no error"
    ok(
        "an outage plan is labelled as a fallback",
        f"{len(result.questions)} question(s), version={result.planner_version}",
    )

    # And the healthy path must NOT wear the fallback label, or every good plan
    # would be treated as a cache miss and re-planned on every session.
    good = {
        "questions": [
            {"question_text": "What is the venue?", "covers_regions": [ids[0]]}
        ]
    }
    with patch("app.conversation.planner.complete_json", return_value=good):
        healthy = plan_questions(schema, ids)
    assert healthy.planner_version != FALLBACK_PLANNER_VERSION, (
        "a healthy plan is labelled as a fallback and would never be cached"
    )
    ok("a healthy plan keeps the real version", healthy.planner_version)


def _cap_counts_accepted(schema, ids) -> None:
    """Four malformed entries must not exhaust the budget for a good fifth."""
    good_text = "What is the venue?"
    payload = {
        "questions": (
            # Four entries the validator rejects, in the shapes it actually
            # sees: bare strings, a missing `question_text`, an unknown region.
            ["not a dict", "also not a dict"]
            + [
                {"question_text": "?", "covers_regions": ["no.such.region"]},
                {"covers_regions": [ids[1]]},  # no question_text
            ]
            # ...then a good one, which the old `[:limit]` slice cut off.
            + [{"question_text": good_text, "covers_regions": [ids[0]]}]
        )
    }
    with patch("app.conversation.planner.complete_json", return_value=payload):
        result = plan_questions(schema, ids)

    assert result.planner_version != FALLBACK_PLANNER_VERSION, (
        "the good fifth entry was discarded and the plan fell back to structural"
    )
    texts = [q.question_text for q in result.questions]
    assert good_text in texts, f"the one valid question was dropped; kept {texts}"
    budget = question_budget([r for r in schema.regions if r.region_id in set(ids)])
    assert len(result.questions) <= budget, (
        f"{len(result.questions)} questions exceeds this document's budget of {budget}"
    )
    assert budget <= QUESTION_CEILING, f"budget {budget} is above the ceiling"
    ok("the cap counts accepted questions", f"kept {texts}, budget {budget}")


def _budget_follows_the_document(schema, regions) -> None:
    """The interview length must come from the document, not from a constant.

    It was `MAX_QUESTIONS = 4` for every document ever loaded, which is right
    for the MOM and wrong either side of it. These assertions are about the
    *shape* of the function rather than its exact output, so tuning
    `FIELDS_PER_QUESTION` does not break them -- what must not come back is a
    budget that ignores its input.
    """

    class R:
        def __init__(self, kind):
            self.kind = kind

    assert question_budget([]) == 0, "no regions must mean no questions"
    assert question_budget([R("field")]) == 1, "one field must be one question"

    small = question_budget([R("field")] * 2)
    large = question_budget([R("field")] * 40)
    assert small < large, (
        f"a 2-field form and a 40-field workbook both got {small} questions -- "
        "the budget is not reading the document"
    )
    assert large <= QUESTION_CEILING, f"{large} is above the ceiling {QUESTION_CEILING}"

    # A table is its own question; folding it in beside three fields is how you
    # get an action-item list answered as an afterthought.
    assert question_budget([R("field")] * 3 + [R("table_loop")]) > question_budget(
        [R("field")] * 3
    ), "adding a table did not buy a question"

    real = question_budget(regions)
    assert 1 <= real <= QUESTION_CEILING, f"this document's budget is {real}"
    ok(
        "the question budget follows the document",
        f"2 fields -> {small}, 40 fields -> {large}, this document -> {real}",
    )


def _duplicate_entry_keeps_its_own_basis(schema, ids) -> None:
    """Entry one's value must not inherit entry two's justification."""
    target = ids[0]
    payload = {
        "entries": [
            {
                "region_id": target,
                "value": "First value",
                "basis": "FIRST BASIS",
                "confidence": 0.9,
            },
            {
                "region_id": target,
                "value": "Second value",
                "basis": "SECOND BASIS",
                "confidence": 0.1,
            },
        ]
    }
    with patch("app.conversation.deriver.complete_json", return_value=payload):
        result = derive_values(schema, [target], {})

    if target not in result.values:
        # Dropped for an unrelated reason (e.g. a missing basis). The pairing
        # claim is then untestable rather than proven, and saying so is the point.
        raise AssertionError(
            f"{target} was not derived at all, so the value/basis pairing could "
            f"not be checked -- this test would otherwise pass vacuously. "
            f"unjustified={result.unjustified} dropped={result.dropped_ids} "
            f"empty={result.considered_empty} errors={result.errors}"
        )

    derived = result.values[target]
    value, basis = derived.value, derived.basis
    assert value == "First value", f"first-entry-wins broken on the value: {value!r}"
    assert "FIRST" in str(basis).upper(), (
        f"value came from entry 1 but basis came from entry 2: {value!r} / {basis!r} -- "
        "an invented value would inherit a real citation"
    )
    ok("a duplicated region_id keeps value and basis together", f"{value!r} / {basis!r}")


def _unknown_columns_are_warned(regions, caplog_level=logging.WARNING) -> None:
    """Rows that lose every cell must leave a trace."""
    table = next(
        (r for r in regions if r.kind in ("table_loop", "table_data")), None
    )
    assert table is not None, "no table region in the MOM to test against"

    payload = {
        "entries": [
            {"region_id": table.region_id, "rows": [{"NoSuchColumn": "value"}]}
        ]
    }
    logger = logging.getLogger("app.conversation.values")
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture(level=caplog_level)
    logger.addHandler(handler)
    try:
        values, _dropped = parse_entries(
            payload,
            {r.region_id for r in regions},
            {table.region_id: region_columns(table)},
        )
    finally:
        logger.removeHandler(handler)

    assert table.region_id not in values, (
        "a row with no recognised column was written anyway"
    )
    assert any(table.region_id in m for m in records), (
        f"the region vanished with no warning; logged: {records}"
    )
    ok("all-unknown columns are warned about", records[0][:60] + "...")


def _call_log_is_bounded() -> None:
    """The rolling window must not grow for the life of the process."""
    from app.ai.bedrock import _MAX_REMEMBERED_CALLS, LLMCall, _calls

    before = len(_calls)
    for _ in range(_MAX_REMEMBERED_CALLS + 250):
        _calls.append(
            LLMCall(
                purpose="probe",
                model_id="m",
                prompt_version="v",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=0.0,
                ok=True,
            )
        )
    after = len(_calls)

    assert after <= _MAX_REMEMBERED_CALLS, (
        f"the call log grew to {after}, past its {_MAX_REMEMBERED_CALLS} cap"
    )
    assert isinstance(bedrock.last_calls(), list), "last_calls() must return a list"
    ok(
        "the Bedrock call log is bounded",
        f"{before} -> {after} after {_MAX_REMEMBERED_CALLS + 250} appends",
    )


def main() -> int:
    if not SOURCE.exists():
        print(f"SKIP: corpus file not on this machine: {SOURCE.name}")
        return 0

    schema, regions, ids = _regions()
    print(f"Conversation fixes, {SOURCE.name} ({len(regions)} editable regions):\n")

    print("Planner:")
    _fallback_is_labelled(schema, ids)
    _cap_counts_accepted(schema, ids)
    _budget_follows_the_document(schema, regions)

    print("\nDeriver:")
    _duplicate_entry_keeps_its_own_basis(schema, ids)

    print("\nValues:")
    _unknown_columns_are_warned(regions)

    print("\nBedrock:")
    _call_log_is_bounded()

    print(f"\nOK - {len(passed)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
