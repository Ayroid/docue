"""Contract C1 end to end: a JSON Change Spec compiled for all three formats.

    uv run python scripts/test_change_spec.py

Runs offline against the real corpus. What it proves, in order of how much it
would hurt to get wrong:

1. **The plan's own §3.2 spec parses and round-trips through JSON.** If the
   frozen example doesn't validate, the contract is wrong rather than the
   example.
2. **A model cannot reach a byte it wasn't given.** Every gate is tested by
   trying to get through it: an invented `region_id`, a write aimed at the MOM's
   logo, a value carrying raw XML, a column that doesn't exist. Each is either
   dropped and reported or written as literal text -- never applied, never
   silently swallowed.
3. **The same JSON drives all three compilers.** One spec shape, xlsx/docx/pptx
   behind it, with structural and functional QA passing on each.
4. **A spec cannot be replayed against the wrong bytes.** `base_version_id` is
   checked, because the coordinates in a spec are only meaningful for the schema
   they were planned against.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/docue")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("S3_BUCKET_NAME", "placeholder")

import uuid  # noqa: E402

from _artifact import write_artifact  # noqa: E402

from app.compiler.from_spec import SpecCompileError, compile_spec  # noqa: E402
from app.ingestion.detect import detect  # noqa: E402
from app.schemas.change_spec import SPEC_VERSION, ChangeSpec  # noqa: E402

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"
SCRATCH = Path(__file__).resolve().parent.parent / "scratch"

# Plan §3.2 verbatim enough to be a real test of the frozen shape.
PLAN_SPEC = {
    "spec_version": "1.0",
    "base_version_id": "3f1b9c4e-0000-4000-8000-000000000001",
    "tier": "T3",
    "operations": [
        {
            "op": "set_value",
            "target": {"format": "xlsx", "sheet": "Sheet1", "ref": "E5"},
            "value": "Workshop Session - AP Automation (Cycle 2)",
            "value_type": "string",
            "expected_after": "Workshop Session - AP Automation (Cycle 2)",
            "provenance": "user_answer:q2",
        },
        {
            "op": "set_value",
            "target": {"format": "xlsx", "sheet": "Sheet1", "ref": "B5"},
            "value": "2026-08-14",
            "value_type": "date",
            "provenance": "system:today",
        },
        {
            "op": "replace_region_rows",
            "target": {"region_id": "mom.meeting_summary"},
            "rows": [{"Sl.No.": 1, "Summary": "Agenda: continuing AP automation..."}],
            "row_template_ref": "Sheet1!A11:G11",
            "provenance": "llm_generated",
            "grounded_by": ["version:uuid-of-prior-mom"],
        },
        {
            "op": "clone_table_rows",
            "target": {"region_id": "mom.action_plan"},
            "rows": [
                {
                    "Action": "Share AP header field mapping",
                    "Responsibility": "Ravi",
                    "Target date": "2026-08-22",
                    "Status": "Open",
                }
            ],
            "provenance": "llm_derived:q3",
        },
        {"op": "protect", "target": {"ref": "Sheet1!A1:G2"}, "reason": "branding_richvalue"},
    ],
    "assertions": [
        {"ref": "Sheet1!E5", "must_equal": "Workshop Session - AP Automation (Cycle 2)"},
        {"invariant": "package_parts_preserved", "expect": "all"},
        {"invariant": "merged_ranges", "expect": 27},
    ],
}

# A value that would be markup if it were ever concatenated into XML instead of
# escaped. §10's invariant: "a value containing `<w:p>` is text".
INJECTION = '<w:p/><script>&"</script> 5 < 7'


def check_plan_spec() -> list[str]:
    failures = []
    try:
        spec = ChangeSpec.model_validate(PLAN_SPEC)
    except Exception as exc:  # noqa: BLE001
        return [f"the plan's own §3.2 spec does not validate: {exc}"]

    if spec.operation_count != 5 or len(spec.assertions) != 3:
        failures.append(f"parsed {spec.operation_count} ops / {len(spec.assertions)} assertions")
    if spec.spec_version != SPEC_VERSION:
        failures.append(f"spec_version {spec.spec_version!r}")
    round_tripped = ChangeSpec.model_validate(json.loads(spec.model_dump_json()))
    if round_tripped != spec:
        failures.append("a spec does not survive a JSON round trip unchanged")
    provenance = spec.provenance_counts()
    if set(provenance) != {"user_answer", "system", "llm_generated", "llm_derived"}:
        failures.append(f"provenance not classified as the UI expects: {provenance}")
    print(f"  §3.2 spec: {spec.operation_count} ops, tier={spec.tier}, provenance={provenance}")
    return failures


def check_rejections() -> list[str]:
    """Malformed specs must fail loudly -- that is an emitter bug, not a guess."""
    failures = []
    cases = [
        ({"spec_version": "2.0"}, "an unsupported spec_version"),
        (
            {"operations": [{"op": "set_value", "target": {"region_id": "x"}, "value": 1}]},
            "an operation with no provenance",
        ),
        (
            {"operations": [{"op": "delete_everything", "target": {"region_id": "x"}, "provenance": "p"}]},
            "an op name outside the vocabulary",
        ),
        ({"operations": [{"op": "clear_region", "target": {}, "provenance": "p"}]}, "a target pointing at nothing"),
        (
            {
                "operations": [
                    {"op": "clear_region", "target": {"region_id": "x"}, "provenance": "p", "xml": "<w:p/>"}
                ]
            },
            "an unexpected field smuggled onto an operation",
        ),
    ]
    for payload, description in cases:
        try:
            ChangeSpec.model_validate({"spec_version": "1.0", **payload})
        except Exception:  # noqa: BLE001
            continue
        failures.append(f"accepted {description}")
    print(f"  {len(cases)} malformed specs all rejected")
    return failures


def check_base_version_guard(data: bytes, schema) -> list[str]:
    spec = ChangeSpec.model_validate(
        {
            "spec_version": "1.0",
            "base_version_id": str(uuid.uuid4()),
            "operations": [
                {
                    "op": "set_value",
                    "target": {"region_id": "sheet1.venue"},
                    "value": "YMSLI Faridabad",
                    "provenance": "user_answer:q1",
                }
            ],
        }
    )
    try:
        compile_spec(data, "xlsx", schema, spec, version_id=uuid.uuid4())
    except SpecCompileError as exc:
        if "planned against" not in str(exc):
            return [f"base_version_id mismatch raised the wrong error: {exc}"]
        print("  a spec planned against another version is refused, not replayed")
        return []
    return ["a spec was replayed against bytes it was not planned against"]


def check_xlsx() -> list[str]:
    failures = []
    path = FILES_DIR / "MOM Sample.xlsx"
    data = path.read_bytes()
    schema = detect(data, "xlsx")

    spec = ChangeSpec.model_validate(
        {
            "spec_version": "1.0",
            "tier": "T3",
            "intent": "next MOM for the AP automation workshop",
            "operations": [
                # Addressed by region_id.
                {
                    "op": "set_value",
                    "target": {"region_id": "sheet1.purpose"},
                    "value": "Workshop Session - AP Automation (Cycle 2)",
                    "provenance": "user_answer:q2",
                },
                # Addressed by raw ref, resolved through the schema.
                {
                    "op": "set_value",
                    "target": {"sheet": "Sheet1", "ref": "B5"},
                    "value": "2026-08-20",
                    "value_type": "date",
                    "provenance": "system:today",
                },
                # A value that is markup, not a value.
                {
                    "op": "set_value",
                    "target": {"region_id": "sheet1.venue"},
                    "value": INJECTION,
                    "provenance": "user_answer:q4",
                },
                {
                    "op": "replace_region_rows",
                    "target": {"region_id": "sheet1.meeting_summary"},
                    "rows": [
                        {"serial": i, "content": f"Point {i}: invoice header capture and tolerances."}
                        for i in range(1, 16)
                    ],
                    "provenance": "llm_generated",
                },
                {
                    "op": "clone_table_rows",
                    "target": {"region_id": "sheet1.action_plan_after_current_meeting"},
                    "rows": [
                        {
                            "Sl.No.": 1,
                            "Action": "Share the AP invoice header field mapping",
                            "Responsibility": "Ravi Kumar",
                            "Status": "Open",
                        }
                    ],
                    "column_styles": {
                        "Sl.No.": "7",
                        "Action": "31",
                        "Responsibility": "31",
                        "Status": "31",
                    },
                    "provenance": "llm_derived:q3",
                },
                # Every gate, probed: the logo, a region that doesn't exist, and
                # a column that doesn't exist.
                {
                    "op": "set_value",
                    "target": {"region_id": "sheet1.rich_value_a1"},
                    "value": "HIJACKED",
                    "provenance": "llm_generated",
                },
                {
                    "op": "set_value",
                    "target": {"region_id": "sheet1.invented_by_the_model"},
                    "value": "x",
                    "provenance": "llm_generated",
                },
                {
                    "op": "clone_table_rows",
                    "target": {"region_id": "sheet1.action_plan_after_current_meeting"},
                    "rows": [{"Nonexistent Column": "x"}],
                    "provenance": "llm_generated",
                },
                {"op": "protect", "target": {"ref": "A1:G2"}, "reason": "branding_richvalue"},
            ],
            "assertions": [
                {"invariant": "package_parts_preserved", "expect": "all"},
                {"invariant": "sensitivity_label", "expect": True},
                {"invariant": "rich_value_parts", "expect": 5},
            ],
        }
    )

    result = compile_spec(data, "xlsx", schema, spec)
    print(
        f"  xlsx: {result.applied} primitives applied, {len(result.dropped)} dropped, "
        f"{result.rows_inserted} rows, QA {'PASS' if result.passed else 'FAIL'}, {result.duration_ms}ms"
    )
    for entry in result.dropped:
        print(f"    dropped [{entry.index}] {entry.op} -> {entry.target}: {entry.reason}")

    if not result.passed:
        failures.append(f"xlsx QA failed: {result.report()}")
    dropped_targets = {entry.target for entry in result.dropped}
    for expected in ("sheet1.rich_value_a1", "sheet1.invented_by_the_model"):
        if expected not in dropped_targets:
            failures.append(f"xlsx: {expected} was not dropped -- it reached the compiler")
    if len(result.dropped) != 3:
        failures.append(f"xlsx: expected 3 drops (logo, unknown region, unknown column), got {len(result.dropped)}")
    if not any(a.subject == "sensitivity_label" and a.passed for a in result.spec_assertions):
        failures.append("xlsx: the sensitivity label invariant did not hold")

    # The injected markup must come back as literal text, and the file must still
    # be readable -- the two halves of "values are escaped, always".
    out_schema = detect(result.data, "xlsx")
    venue = next((r for r in out_schema.regions if r.label == "Venue"), None)
    if venue is None:
        failures.append("xlsx: the Venue region vanished from the output")
    elif venue.current_content != INJECTION:
        failures.append(f"xlsx: injected value was not stored verbatim: {venue.current_content!r}")
    else:
        print(f"    markup written as text, verbatim: {venue.current_content!r}")

    print(f"    wrote {write_artifact(SCRATCH / 'MOM_from_spec.xlsx', result.data)}")
    return failures


def check_docx() -> list[str]:
    failures = []
    data = (FILES_DIR / "BRD Sample.docx").read_bytes()
    schema = detect(data, "docx")

    spec = ChangeSpec.model_validate(
        {
            "spec_version": "1.0",
            "tier": "T2",
            "operations": [
                {
                    "op": "set_value",
                    "target": {"region_id": "doc.prepared_by"},
                    "value": "YMSLI Digital Transformation Office",
                    "provenance": "user_answer:q1",
                },
                {
                    "op": "replace_region_rows",
                    "target": {"region_id": "doc.description"},
                    "rows": [
                        "Capital acquisition requests are captured against the approved mapping.",
                        "Duplicate detection uses vendor plus invoice number as the key.",
                        "Non-PO capital invoices route through a separate approval workflow.",
                        "Tax treatment derives from vendor registration and place of supply.",
                    ],
                    "provenance": "llm_generated",
                },
                {
                    "op": "clone_table_rows",
                    "target": {"region_id": "doc.items_summary"},
                    "rows": [
                        {
                            "Item": "10",
                            "Type": "Feature",
                            "Name": "[YNS] 55.10.040 Capture AP invoice header",
                            "Area Path": "YNS-FnO-ANZ-ERP\\55. Acquire To Dispose",
                        }
                    ],
                    "provenance": "llm_derived:q2",
                },
                # The revision block is `history`: system-written on publish, not
                # the generation agent's to fill. It must be refused here.
                {
                    "op": "clone_table_rows",
                    "target": {"region_id": "doc.document_revision"},
                    "rows": [{"Ver.": "9.9"}],
                    "provenance": "llm_generated",
                },
                # An image paragraph.
                {
                    "op": "set_value",
                    "target": {"region_id": "doc.drawing_para1"},
                    "value": "HIJACKED",
                    "provenance": "llm_generated",
                },
            ],
            "assertions": [{"invariant": "package_parts_preserved", "expect": "all"}, {"invariant": "drawings", "expect": 6}],
        }
    )

    result = compile_spec(data, "docx", schema, spec)
    print(
        f"  docx: {result.applied} primitives applied, {len(result.dropped)} dropped, "
        f"{result.rows_inserted} rows, QA {'PASS' if result.passed else 'FAIL'}, {result.duration_ms}ms"
    )
    for entry in result.dropped:
        print(f"    dropped [{entry.index}] {entry.op} -> {entry.target}: {entry.reason}")

    if not result.passed:
        failures.append(f"docx QA failed: {result.report()}")
    dropped_targets = {entry.target for entry in result.dropped}
    for expected in ("doc.document_revision", "doc.drawing_para1"):
        if expected not in dropped_targets:
            failures.append(f"docx: {expected} was not dropped -- it reached the compiler")
    # One row appended to a 9-row table, so the caption must read 10 -- it counts
    # the rows that are actually there rather than echoing what the spec asked for.
    if result.structural_detail.get("captions_refreshed") != ["Items (10) Summary:"]:
        failures.append(
            f"docx: the counting caption was not restated: {result.structural_detail.get('captions_refreshed')}"
        )
    else:
        print(f"    caption restated: {result.structural_detail['captions_refreshed']}")
    if not any(a.subject == "drawings" and a.passed for a in result.spec_assertions):
        failures.append("docx: the 6-drawings invariant did not hold")

    print(f"    wrote {write_artifact(SCRATCH / 'BRD_from_spec.docx', result.data)}")
    return failures


def check_pptx() -> list[str]:
    failures = []
    path = FILES_DIR / "Workshop Readout Template.pptx"
    if not path.exists():
        print("  pptx: SKIPPED -- run scripts/build_workshop_readout_template.py first")
        return []
    data = path.read_bytes()
    schema = detect(data, "pptx")

    title = next((r for r in schema.regions if r.kind == "title" and r.editable), None)
    bullets = next((r for r in schema.regions if r.kind == "repeating_block" and r.editable), None)
    table = next((r for r in schema.regions if r.kind in ("table_loop", "table_data")), None)
    protected = next((r for r in schema.regions if r.protected), None)
    if title is None or bullets is None:
        return ["pptx: the deck has no editable title or bullet region to target"]

    operations = [
        {
            "op": "set_value",
            "target": {"region_id": title.region_id},
            "value": "Workshop Readout - AP Automation Cycle 2",
            "provenance": "user_answer:q1",
        },
        {
            "op": "set_bullets",
            "target": {"region_id": bullets.region_id},
            "items": [
                "Invoice header capture walked through against the D365 form",
                "Duplicate detection keyed on vendor plus invoice number",
                "Non-PO invoices routed through a separate approval workflow",
            ],
            "provenance": "llm_generated",
        },
    ]
    if table is not None:
        columns = [c["name"] for c in table.notes.get("columns", [])][:2]
        if len(columns) == 2:
            operations.append(
                {
                    "op": "replace_region_rows",
                    "target": {"region_id": table.region_id},
                    "rows": [{columns[0]: "1", columns[1]: "Share the AP header mapping"}],
                    "provenance": "llm_derived:q3",
                }
            )
    if protected is not None:
        operations.append(
            {
                "op": "set_value",
                "target": {"region_id": protected.region_id},
                "value": "HIJACKED",
                "provenance": "llm_generated",
            }
        )

    spec = ChangeSpec.model_validate(
        {
            "spec_version": "1.0",
            "tier": "T2",
            "operations": operations,
            "assertions": [
                {"invariant": "package_parts_preserved", "expect": "all"},
                {"invariant": "pictures", "expect": 1},
            ],
        }
    )

    result = compile_spec(data, "pptx", schema, spec)
    print(
        f"  pptx: {result.applied} primitives applied, {len(result.dropped)} dropped, "
        f"QA {'PASS' if result.passed else 'FAIL'}, {result.duration_ms}ms"
    )
    for entry in result.dropped:
        print(f"    dropped [{entry.index}] {entry.op} -> {entry.target}: {entry.reason}")

    if not result.passed:
        failures.append(f"pptx QA failed: {result.report()}")
    if protected is not None and protected.region_id not in {e.target for e in result.dropped}:
        failures.append(f"pptx: {protected.region_id} was not dropped -- it reached the compiler")

    print(f"    wrote {write_artifact(SCRATCH / 'Readout_from_spec.pptx', result.data)}")
    return failures


def check_nothing_applicable(data: bytes, schema) -> list[str]:
    """A spec where every operation is dropped must not produce a file."""
    spec = ChangeSpec.model_validate(
        {
            "spec_version": "1.0",
            "operations": [
                {"op": "set_value", "target": {"region_id": "nope.one"}, "value": 1, "provenance": "llm_generated"},
                {"op": "set_value", "target": {"region_id": "nope.two"}, "value": 2, "provenance": "llm_generated"},
            ],
        }
    )
    try:
        compile_spec(data, "xlsx", schema, spec)
    except SpecCompileError:
        print("  a spec with nothing applicable produces no file, not an empty edit")
        return []
    return ["a spec whose every operation was dropped still produced a file"]


def main() -> int:
    if not FILES_DIR.exists():
        print(f"corpus not found: {FILES_DIR}")
        return 1

    failures: list[str] = []
    print("=" * 96)
    print("contract C1 — the frozen shape")
    print("=" * 96)
    failures += check_plan_spec()
    failures += check_rejections()

    mom = (FILES_DIR / "MOM Sample.xlsx").read_bytes()
    mom_schema = detect(mom, "xlsx")
    failures += check_base_version_guard(mom, mom_schema)
    failures += check_nothing_applicable(mom, mom_schema)

    print()
    print("=" * 96)
    print("one spec shape, three compilers")
    print("=" * 96)
    failures += check_xlsx()
    failures += check_docx()
    failures += check_pptx()

    print()
    print("=" * 96)
    if failures:
        print(f"change spec: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("change spec: PASS -- C1 compiles for all three formats, every gate holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
