"""A dropped operation must not fail the whole document. No model calls.

    uv run python scripts/test_dropped_assertions.py

The bug this pins down: the change planner emits one `must_equal` per
`set_value`, and the compiler drops an operation whose value cannot go into its
region. Those two facts together used to guarantee a contradiction -- the
dropped operation never ran, so its assertion read the untouched original and
failed, and one badly-typed value out of eight failed the QA gate for the entire
file. `dropped` existed precisely so that a region we cannot write is left alone
and *shown*; the assertion replay was quietly overriding it.

So: an assertion whose operation was dropped is not evaluated. The narrowness of
that is the thing worth testing, and `_narrow` below is the reason this file is
not just a happy-path check -- a fix that skipped assertions in general would
pass every other case here while silently disarming the only mechanism that
catches "the document compiled but we didn't actually change the venue".

Paired with it, the other half of the same defect: `value_rejection_reason`,
which lets the review screen refuse a badly-typed edit at the door rather than
accept it with a 200 and drop it two endpoints later.

xlsx only, deliberately -- it is the one format where the compiler enforces
value types at all, because a workbook date is a serial number and a string
reaching the converter raises. Word and PowerPoint store text as given.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.compiler.from_spec import compile_spec, value_rejection_reason  # noqa: E402
from app.ingestion.detect import detect  # noqa: E402
from app.planning.change_planner import plan_change_spec  # noqa: E402
from app.schemas.change_spec import (  # noqa: E402
    ChangeSpec,
    SetValueOp,
    Target,
    ValueAssertion,
)

FILES = Path(__file__).resolve().parent.parent.parent / "Files"
SOURCE = FILES / "MOM Sample.xlsx"

# Prose aimed at a date cell. The exact shape of the review-screen edit that
# turned up in live testing, and the reason any of this was found.
BAD_DATE = "Edited on review"
GOOD_DATE = "2026-08-22"
GOOD_TEXT = "Conference Room 4"


def _load() -> tuple[bytes, object, object, object]:
    data = SOURCE.read_bytes()
    schema = detect(data, "xlsx")
    date_region = next(
        r for r in schema.regions if r.editable and r.value_type == "date"
    )
    text_region = next(
        r
        for r in schema.regions
        if r.editable and r.kind == "field" and r.value_type == "string"
    )
    return data, schema, date_region, text_region


def _rejection_at_the_door(schema, date_region, text_region) -> None:
    """What `PATCH /spec/{op_index}` now asks before it accepts a value."""
    reason = value_rejection_reason("xlsx", date_region, BAD_DATE)
    assert reason, f"{BAD_DATE!r} into {date_region.region_id} was not refused"
    assert "date" in reason.lower(), f"the refusal does not explain itself: {reason!r}"
    print(f"  refused at the door: {reason[:64]}...")

    assert value_rejection_reason("xlsx", date_region, GOOD_DATE) is None, (
        f"{GOOD_DATE!r} is a date and must be accepted into a date region"
    )
    assert value_rejection_reason("xlsx", text_region, GOOD_TEXT) is None, (
        "a string into a string region must be accepted"
    )
    # Rows are judged per cell when the table is built, against its own header.
    assert value_rejection_reason("xlsx", date_region, [{"x": "y"}]) is None, (
        "rows must not be judged against the scalar region's value_type"
    )
    # docx/pptx store the text as given; the rule must not leak to them.
    assert value_rejection_reason("docx", date_region, BAD_DATE) is None, (
        "the xlsx-only value rule leaked into docx"
    )
    print("  good date, good text, rows and non-xlsx all accepted")


def _drop_does_not_fail_the_document(data, schema, date_region, text_region) -> None:
    """One bad value drops one operation. The other seven still land."""
    values = {date_region.region_id: BAD_DATE, text_region.region_id: GOOD_TEXT}
    planned = plan_change_spec(schema, values, base_version_id=None, tier="T3")

    # The planner does not type-check -- it emits both writes and, critically,
    # a `must_equal` for each. That is the collision under test.
    assert not planned.skipped, f"the planner skipped {planned.skipped}"
    refs = {a.ref for a in planned.spec.assertions if isinstance(a, ValueAssertion)}
    assert getattr(date_region.locator, "ref", None) in refs, (
        "no assertion was emitted for the bad value -- this test proves nothing"
    )

    result = compile_spec(data, "xlsx", schema, planned.spec)

    assert len(result.dropped) == 1, (
        f"expected exactly 1 drop, got {len(result.dropped)}: "
        + "; ".join(f"{d.target}: {d.reason}" for d in result.dropped)
    )
    assert result.dropped[0].target == date_region.region_id, (
        f"the wrong operation was dropped: {result.dropped[0].target}"
    )
    assert result.applied >= 1, "the good operation was lost with the bad one"

    failed = [a for a in result.spec_assertions if not a.passed]
    assert not failed, (
        f"{len(failed)} assertion(s) failed despite their operation being dropped: "
        + "; ".join(f"{a.subject} expected {a.expected!r} got {a.actual!r}" for a in failed)
    )
    assert result.passed, "QA gate still failed the document over a dropped operation"
    assert not result.structural_detail["lost_parts"], "package parts lost"

    # The drop is reported, not hidden. That distinction is the whole fix.
    print(
        f"  1 dropped ({result.dropped[0].target}), {result.applied} applied, "
        f"QA passed, {len(result.spec_assertions)} assertion(s) evaluated"
    )


def _narrow(data, schema, text_region) -> None:
    """The guard: a *live* operation's assertion must still be able to fail.

    Without this, a fix that skipped every assertion would pass this whole file.
    """
    hostile = ChangeSpec(
        tier="T1",
        operations=[
            SetValueOp(
                op="set_value",
                target=Target(region_id=text_region.region_id),
                value=GOOD_TEXT,
                provenance="test",
            )
        ],
        assertions=[
            ValueAssertion(
                ref=getattr(text_region.locator, "ref"),
                must_equal="something the compiler never wrote",
                sheet=getattr(text_region.locator, "sheet", None),
            )
        ],
    )
    result = compile_spec(data, "xlsx", schema, hostile)
    assert not result.dropped, f"nothing should have been dropped: {result.dropped}"
    failed = [a for a in result.spec_assertions if not a.passed]
    assert failed, (
        "a wrong assertion on an operation that DID run was not caught -- the "
        "dropped-operation skip is too broad and has disarmed the QA gate"
    )
    print(f"  live assertion still fails when wrong: {failed[0].subject}")


def _clean_run(data, schema, date_region, text_region) -> None:
    """The ordinary path stays ordinary: nothing dropped, everything checked."""
    values = {date_region.region_id: GOOD_DATE, text_region.region_id: GOOD_TEXT}
    planned = plan_change_spec(schema, values, base_version_id=None, tier="T3")
    result = compile_spec(data, "xlsx", schema, planned.spec)

    assert not result.dropped, (
        "a valid value was dropped: "
        + "; ".join(f"{d.target}: {d.reason}" for d in result.dropped)
    )
    value_checks = [a for a in result.spec_assertions if a.kind == "value"]
    assert len(value_checks) >= 2, (
        f"only {len(value_checks)} value assertion(s) evaluated on a clean run -- "
        "the skip is firing when nothing was dropped"
    )
    assert all(a.passed for a in result.spec_assertions), "a clean run failed QA"
    assert result.passed, "a clean run failed the QA gate"
    print(f"  clean run: 0 dropped, {len(value_checks)} value assertion(s), all passed")


def main() -> int:
    if not SOURCE.exists():
        print(f"SKIP: corpus file not on this machine: {SOURCE.name}")
        print(f"      expected in {FILES}")
        return 0

    data, schema, date_region, text_region = _load()
    print(f"Dropped-operation assertions, {SOURCE.name}:")
    print(f"  date region {date_region.region_id}, text region {text_region.region_id}")

    print("\nValue rejection at the API boundary:")
    _rejection_at_the_door(schema, date_region, text_region)

    print("\nA dropped operation does not fail the document:")
    _drop_does_not_fail_the_document(data, schema, date_region, text_region)

    print("\nThe skip is narrow:")
    _narrow(data, schema, text_region)

    print("\nThe clean path is unchanged:")
    _clean_run(data, schema, date_region, text_region)

    print("\nOK - a bad value costs one region, not the whole file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
