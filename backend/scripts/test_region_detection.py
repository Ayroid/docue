"""Region-detector report for the real sample corpus. Read-only on the sources.

Run this after touching app/ingestion/regions.py:

    uv run python scripts/test_region_detection.py

It prints every detected region per sheet so a human can eyeball recall, then
asserts the handful of facts the plan calls out by name (MOM row 27 is a
table_loop, `A1` is branding, the Sl.No. jump is flagged, and nothing on the
Instruction sheet is writable).
"""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402

from app.ingestion.regions import DocumentSchema, detect_regions_xlsx  # noqa: E402

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"
SAMPLES = ["MOM Sample.xlsx", "BFL Sample.xlsx", "POC List sample.xlsx"]


def _short(text: str | None, width: int = 34) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def report(name: str, schema: DocumentSchema, elapsed_ms: float) -> None:
    print("=" * 96)
    print(f"{name}   detector={schema.detector_version}   {elapsed_ms:.0f}ms")
    for sheet in schema.sheets:
        suffix = f"  {sheet.notes}" if sheet.notes else ""
        print(
            f"\n  sheet {sheet.name!r}  role={sheet.role}  used={sheet.used_range}{suffix}"
        )
        if not sheet.regions:
            print("    (no populated cells)")
        for region in sheet.regions:
            flags = "".join(
                ("E" if region.editable else "-", "P" if region.protected else "-")
            )
            extra = ""
            if region.kind in ("table_loop", "table_data", "history"):
                cols = [c["name"] for c in region.notes.get("columns", [])]
                extra = f"  rows={region.notes.get('row_count')} cols={_short(', '.join(cols), 46)}"
            elif region.kind == "repeating_block":
                extra = (
                    f"  rows={region.notes['row_count']}"
                    f" serial={region.notes['serial_column']}"
                    f" content={region.notes['content_column']}"
                    f" gaps={region.notes['serial_gaps']}"
                )
            print(
                f"    {flags} {region.kind:<15} {region.locator.ref:<12}"
                f" {_short(region.label):<35} {_short(region.current_content, 28)}{extra}"
            )
    print(f"\n  totals: {schema.counts_by_kind()}")
    print(f"  writable regions: {len(schema.writable())} / {len(schema.regions)}")


def check_mom(schema: DocumentSchema) -> list[str]:
    """The MOM assertions are the ones the plan names explicitly."""
    failures = []
    by_kind: dict[str, list] = {}
    for region in schema.regions:
        by_kind.setdefault(region.kind, []).append(region)

    branding = by_kind.get("branding", [])
    if not any(r.locator.ref.startswith("A1") for r in branding):
        failures.append("A1 in-cell logo not detected as branding")
    if any(r.editable for r in branding):
        failures.append("branding region is editable")

    loops = [r for r in by_kind.get("table_loop", []) if r.locator.ref.startswith("A27")]
    if not loops:
        failures.append("row 27 Action Plan not detected as table_loop")
    else:
        loop = loops[0]
        names = [c["name"] for c in loop.notes["columns"]]
        if "Responsibility" not in names or len(names) != 7:
            failures.append(f"Action Plan columns wrong: {names}")
        if loop.label != "Action Plan after Current Meeting":
            failures.append(f"Action Plan caption not attached: {loop.label!r}")

    blocks = by_kind.get("repeating_block", [])
    if not blocks:
        failures.append("rows 11-24 meeting summary not detected as repeating_block")
    else:
        block = blocks[0]
        if block.notes["row_count"] != 14:
            failures.append(f"meeting summary row_count={block.notes['row_count']}, want 14")
        if block.notes["serial_gaps"] != [[13, 16]]:
            failures.append(f"Sl.No. 13->16 jump not flagged: {block.notes['serial_gaps']}")

    fields = {r.label: r for r in by_kind.get("field", [])}
    if "Date" not in fields:
        failures.append("A5 Date -> B5 not detected as field")
    elif fields["Date"].value_type != "date":
        failures.append(f"Date field value_type={fields['Date'].value_type}, want date")

    empties = {r.label for r in by_kind.get("field_empty", [])}
    for label in ("Attendees(YMSLI)", "Attendees(YMESG)"):
        if label not in empties:
            failures.append(f"{label} not detected as field_empty")

    titles = {r.label for r in by_kind.get("title", [])}
    if "Form ID:YMSLI-F-MOM" not in titles:
        failures.append(f"D3 form id not detected as title: {titles}")

    return failures


def check_house_pattern(name: str, schema: DocumentSchema) -> list[str]:
    """BFL and POC share YMSLI's Cover / History / Instruction pattern."""
    failures = []
    roles = {sheet.role for sheet in schema.sheets}
    for role in ("cover", "history", "instruction" if "BFL" in name else "cover"):
        if role not in roles:
            failures.append(f"{name}: no sheet detected with role {role!r}")

    for sheet in schema.sheets:
        if sheet.role == "instruction" and any(r.editable for r in sheet.regions):
            failures.append(f"{name}: Instruction sheet has editable regions")
        if sheet.role == "history":
            history = [r for r in sheet.regions if r.kind == "history"]
            if not history:
                failures.append(f"{name}: revision block not detected on {sheet.name!r}")
            elif history[0].notes.get("row_count") != 1:
                failures.append(
                    f"{name}: revision block row_count={history[0].notes.get('row_count')}, want 1"
                )

    data_tables = [r for r in schema.regions if r.kind == "table_data"]
    if not any(r.notes.get("row_count", 0) >= 20 for r in data_tables):
        failures.append(f"{name}: main data table not detected (row counts too low)")

    return failures


def check_derived() -> list[str]:
    """No sample workbook contains a formula, and `derived` is one of the two
    kinds the compiler must never write through. Synthesise the case rather
    than ship the branch untested."""
    failures = []
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Total"
    sheet["B1"] = "=SUM(C1:C5)"
    buffer = io.BytesIO()
    workbook.save(buffer)

    schema = detect_regions_xlsx(buffer.getvalue())
    derived = [r for r in schema.regions if r.kind == "derived"]
    if not derived:
        failures.append("synthetic: formula cell B1 not detected as derived")
    elif derived[0].locator.ref != "B1" or derived[0].editable or not derived[0].protected:
        failures.append(f"synthetic: derived region wrong -- {derived[0]}")
    if any(r.editable for r in schema.regions):
        failures.append("synthetic: a region around a formula came out editable")
    return failures


def main() -> int:
    failures: list[str] = []
    for name in SAMPLES:
        path = FILES_DIR / name
        if not path.exists():
            print(f"missing sample: {path}")
            return 1
        data = path.read_bytes()
        started = time.perf_counter()
        schema = detect_regions_xlsx(data)
        elapsed_ms = (time.perf_counter() - started) * 1000
        report(name, schema, elapsed_ms)
        if name.startswith("MOM"):
            failures += [f"MOM: {f}" for f in check_mom(schema)]
        else:
            failures += check_house_pattern(name, schema)

    failures += check_derived()

    print("=" * 96)
    if failures:
        print(f"region detection: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("region detection: PASS -- all corpus assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
