"""The conversation chain end to end, over all three formats. No model calls.

    uv run python scripts/test_conversation.py

Plan §10 stages ③-⑦, driven on the **deterministic path only**: the structural
question grouping stands in for the planner, a scripted answer stands in for the
user, and the change planner is code to begin with. That is a deliberate choice
for a suite that has to be trustworthy -- a test whose result depends on a
Bedrock call is a test that goes red on someone's flaky Wi-Fi and stops being
believed. What the LLM stages add is *wording and triage*; what this proves is
that everything downstream of them turns values into a correct file.

It is also the fallback ladder from §12 under test. Every assertion here holds
with Bedrock switched off entirely, which is the claim "degrade, don't die"
actually means.

Four things are checked per format:

  1. the chain produces a question plan covering only editable regions
  2. the planner emits an operation for every supplied value, and skips nothing
  3. the compile passes structural and functional QA
  4. **zero package parts are lost** -- the claim the whole project rests on

Then the negative cases, because a guarantee nobody tested is a hope: a value
aimed at the logo, and a value naming a region that does not exist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _artifact import write_artifact  # noqa: E402

from app.compiler.from_spec import compile_spec  # noqa: E402
from app.conversation.context import _askable  # noqa: E402
from app.conversation.planner import _fallback  # noqa: E402
from app.conversation.values import region_columns  # noqa: E402
from app.ingestion.detect import detect  # noqa: E402
from app.planning.change_planner import plan_change_spec  # noqa: E402
from app.schemas.change_spec import ChangeSpec, SetValueOp, Target  # noqa: E402

FILES = Path(__file__).resolve().parent.parent.parent / "Files"
SCRATCH = Path(__file__).resolve().parent.parent / "scratch"

CASES = [
    ("MOM Sample.xlsx", "xlsx", "MOM_session_derived.xlsx"),
    ("BRD Sample.docx", "docx", "BRD_session_derived.docx"),
    ("Workshop Readout Template.pptx", "pptx", "Readout_session_derived.pptx"),
]

# What a user "said". Keyed by region kind rather than by region, so the same
# script drives a 8-region workbook and a 61-region document without listing
# either -- and so a detector change that renames regions does not break it.
ANSWERS = {
    "scalar": "AP Automation Cycle 2 — Fixed Assets",
    "date": "2026-08-22",
    "rows": [
        {"content": "Agenda: continuing the Acquire-to-Dispose process."},
        {"content": "Invoice header validation rules agreed."},
    ],
    "table_cell": "Share AP header field mapping",
}


def _scripted_values(askable: list) -> dict:
    """Stand in for stages ⑤ and ⑥: a value for every region a user could fill."""
    values: dict = {}
    for region in askable:
        if region.kind in ("field", "field_empty", "title"):
            values[region.region_id] = (
                ANSWERS["date"] if region.value_type == "date" else ANSWERS["scalar"]
            )
        elif region.kind in ("table_loop", "table_data"):
            columns = region_columns(region)
            if columns:
                values[region.region_id] = [{columns[0]: ANSWERS["table_cell"]}]
        elif region.kind == "repeating_block":
            values[region.region_id] = ANSWERS["rows"]
    return values


def _check_format(filename: str, fmt: str, artifact: str) -> None:
    path = FILES / filename
    data = path.read_bytes()
    schema = detect(data, fmt)

    askable = _askable(schema)
    assert askable, f"{fmt}: no askable region -- the conversation would have nothing to do"

    # ③/④ A conversation must never offer a region the compiler would refuse.
    for region in askable:
        assert region.editable and not region.protected, (
            f"{fmt}: {region.region_id} reached the question plan but is "
            f"editable={region.editable} protected={region.protected}"
        )

    questions = _fallback(askable)
    assert questions, f"{fmt}: the fallback planner produced no question"
    assert len(questions) <= 4, f"{fmt}: {len(questions)} questions, plan §10 caps it at 4"

    covered = [rid for q in questions for rid in q.covers_regions]
    assert len(covered) == len(set(covered)), f"{fmt}: a region is covered by two questions"
    assert set(covered) == {r.region_id for r in askable}, (
        f"{fmt}: the plan covers {len(set(covered))} of {len(askable)} askable regions"
    )

    # ⑦ Values in, Change Spec out.
    values = _scripted_values(askable)
    planned = plan_change_spec(schema, values, base_version_id=None, tier="T3")
    assert not planned.skipped, f"{fmt}: planner skipped {planned.skipped}"

    writes = [op for op in planned.spec.operations if op.op != "protect"]
    assert len(writes) == len(values), (
        f"{fmt}: {len(values)} values produced {len(writes)} write operations"
    )
    assert any(op.op == "protect" for op in planned.spec.operations) or not any(
        r.protected for r in schema.regions
    ), f"{fmt}: protected regions exist but the spec declares none"
    assert any(
        getattr(a, "invariant", None) == "package_parts_preserved"
        for a in planned.spec.assertions
    ), f"{fmt}: the spec does not assert package_parts_preserved"
    for op in writes:
        assert op.provenance, f"{fmt}: {op.op} carries no provenance"

    # The deterministic boundary.
    result = compile_spec(data, fmt, schema, planned.spec)

    assert not result.dropped, (
        f"{fmt}: {len(result.dropped)} operation(s) dropped: "
        + "; ".join(f"{d.target}: {d.reason}" for d in result.dropped[:3])
    )
    assert result.structural_passed, f"{fmt}: structural QA failed"
    assert result.functional_passed, f"{fmt}: functional QA failed"
    failed = [a for a in result.spec_assertions if not a.passed]
    assert not failed, (
        f"{fmt}: {len(failed)} assertion(s) failed: "
        + "; ".join(f"{a.subject} expected {a.expected!r} got {a.actual!r}" for a in failed[:3])
    )
    assert result.passed, f"{fmt}: overall QA failed"

    # The one that matters most.
    lost = result.structural_detail["lost_parts"]
    assert not lost, f"{fmt}: package parts LOST: {lost}"

    written = write_artifact(SCRATCH / artifact, result.data)
    print(
        f"  {fmt:5} {len(schema.regions):3} regions, {len(askable):3} askable, "
        f"{len(questions)} question(s), {len(writes):3} writes, "
        f"{result.applied:3} applied, {result.rows_inserted} row(s), "
        f"0 lost parts, {result.packaging}, {result.duration_ms}ms -> {written.name}"
    )


def _check_guarantees() -> None:
    """The barrier in the negative. A guarantee nobody tested is a hope."""
    data = (FILES / "MOM Sample.xlsx").read_bytes()
    schema = detect(data, "xlsx")

    branding = next((r for r in schema.regions if r.protected), None)
    assert branding is not None, "the MOM has no protected region -- detection changed?"

    # The planner refuses a protected region outright, before the compiler sees it.
    planned = plan_change_spec(schema, {branding.region_id: "OVERWRITE THE LOGO"})
    assert not [op for op in planned.spec.operations if op.op != "protect"], (
        "the planner built a write operation against a protected region"
    )
    assert planned.skipped and planned.skipped[0]["region_id"] == branding.region_id
    print(f"  protected region refused at plan time: {branding.region_id}")

    # A region that does not exist is dropped by the compiler, not guessed at --
    # and the legitimate operation beside it still lands. A text region, because
    # a date one would reject the string for a different and correct reason.
    text_region = next(
        r
        for r in schema.regions
        if r.editable and r.kind in ("field", "field_empty") and r.value_type != "date"
    )
    hostile = ChangeSpec(
        tier="T1",
        operations=[
            SetValueOp(
                op="set_value",
                target=Target(region_id="sheet1.does_not_exist"),
                value="x",
                provenance="test",
            ),
            SetValueOp(
                op="set_value",
                target=Target(region_id=text_region.region_id),
                value="Legitimate value",
                provenance="test",
            ),
        ],
    )
    result = compile_spec(data, "xlsx", schema, hostile)
    assert len(result.dropped) == 1, f"expected 1 drop, got {len(result.dropped)}"
    assert result.dropped[0].target == "sheet1.does_not_exist"
    assert result.applied >= 1, "the legitimate operation was lost with the hostile one"
    print(f"  unknown region dropped, not guessed: {result.dropped[0].reason[:60]}")


def main() -> int:
    missing = [c[0] for c in CASES if not (FILES / c[0]).exists()]
    if missing:
        print(f"SKIP: corpus file(s) not on this machine: {', '.join(missing)}")
        print(f"      expected in {FILES}")
        return 0

    print("Conversation chain, deterministic path (no model calls):")
    for filename, fmt, artifact in CASES:
        _check_format(filename, fmt, artifact)

    print("\nGuarantees:")
    _check_guarantees()

    print("\nOK - three formats derived from a scripted conversation, 0 parts lost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
