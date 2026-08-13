"""pptx end-to-end: derive a filled Workshop Readout from the template.

    uv run python scripts/test_pptx_pipeline.py

Four things are proved here, in order:

1. **The strategy choice is measured, not assumed.** python-pptx's round-trip
   is checked against the real corporate deck and against the template. If it
   ever starts dropping parts, this fails and the pptx compiler has to go
   surgical the way the xlsx one did.
2. **Detection.** Every region kind the deck was built to contain is found:
   title, field, repeating_block (bullets), table_loop, branding (the logo),
   derived (the chart), and speaker notes.
3. **Generation.** Titles, bullet lists of a *different length* to the
   template's, three action rows cloned into a table that had none, and
   speaker notes -- all addressed by region_id.
4. **Preservation.** Structural QA on the invariants (parts, shapes, media,
   chart, embedded workbook), functional QA on every value, and the refusals:
   the logo and the chart cannot be written, and an invented region_id fails.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation  # noqa: E402
from pptx.util import Pt  # noqa: E402

from _artifact import write_artifact  # noqa: E402

from app.compiler import pptx_compiler as pc  # noqa: E402
from app.ingestion.fingerprint import fingerprint_pptx  # noqa: E402
from app.ingestion.pptx_regions import detect_regions_pptx  # noqa: E402
from app.qa.functional import check_pptx_assertions  # noqa: E402
from app.qa.structural import diff_pptx_fingerprints  # noqa: E402

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"
TEMPLATE_PATH = FILES_DIR / "Workshop Readout Template.pptx"
CORPORATE_DECK = FILES_DIR / "YMSLI_Hackathon_2026_Introduction_Session 2(1).pptx"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "scratch" / "Workshop_Readout_derived.pptx"

AGENDA = [
    "Scope: Accounts Payable invoice header capture",
    "Current-state walkthrough and pain points",
    "D365 form demonstration",
    "Decisions taken in this session",
    "Open points carried to cycle 3",
    "Next session: payment run and bank reconciliation",
]

DECISION_BULLETS = [
    "Vendor plus invoice number is confirmed as the duplicate-detection key.",
    "Rationale: mirrors the existing manual control, no master data change needed.",
    "Impact: duplicate blocking can be enabled at go-live.",
    "Owner: Ravi Kumar, confirmed with the tax team on 22 Aug.",
]

ACTION_ROWS = [
    {
        "Sl.No.": "1",
        "Action": "Share AP invoice header field mapping against the D365 form",
        "Responsibility": "Ravi Kumar",
        "Target date": "22-Aug-26",
        "Status": "Open",
    },
    {
        "Sl.No.": "2",
        "Action": "Confirm duplicate-invoice uniqueness key with the tax team",
        "Responsibility": "Anshul Maheshwari",
        "Target date": "27-Aug-26",
        "Status": "Open",
    },
    {
        "Sl.No.": "3",
        "Action": "Decide credit note approval bands and circulate for sign-off",
        "Responsibility": "Shardul Pantawane",
        "Target date": "03-Sep-26",
        "Status": "Open",
    },
]


def check_round_trip() -> list[str]:
    """The measurement the pptx strategy rests on."""
    failures = []
    for path in (CORPORATE_DECK, TEMPLATE_PATH):
        if not path.exists():
            failures.append(f"missing deck: {path}")
            continue
        before = set(zipfile.ZipFile(path).namelist())
        buffer = io.BytesIO()
        Presentation(path).save(buffer)
        after = set(zipfile.ZipFile(buffer).namelist())
        lost = sorted(before - after)
        if lost:
            failures.append(
                f"python-pptx round-trip on {path.name} dropped {lost} -- the pptx "
                "compiler can no longer use the object model"
            )
        fingerprint_before = fingerprint_pptx(path.read_bytes())
        fingerprint_after = fingerprint_pptx(buffer.getvalue())
        if fingerprint_before.sensitivity_label != fingerprint_after.sensitivity_label:
            failures.append(f"{path.name}: sensitivity label lost on round-trip")
        print(
            f"  round-trip {path.name[:44]:<46} {len(before)} parts -> {len(after)}, "
            f"label={fingerprint_after.sensitivity_label}"
        )
    return failures


def check_detection(schema) -> list[str]:
    failures = []
    by_kind = {}
    for region in schema.regions:
        by_kind.setdefault(region.kind, []).append(region)

    for kind, want in (
        ("title", 7),
        ("repeating_block", 4),
        ("table_loop", 1),
        ("branding", 1),
        ("derived", 1),
    ):
        found = len(by_kind.get(kind, []))
        if found != want:
            failures.append(f"{kind}: found {found}, want {want}")

    if any(region.editable for region in by_kind.get("branding", [])):
        failures.append("the logo came out editable")
    if any(region.editable for region in by_kind.get("derived", [])):
        failures.append("the chart came out editable")

    table = (by_kind.get("table_loop") or [None])[0]
    if table is not None:
        names = [column["name"] for column in table.notes["columns"]]
        if names != ["Sl.No.", "Action", "Responsibility", "Target date", "Status"]:
            failures.append(f"action table columns wrong: {names}")
        if table.notes["row_count"] != 0:
            failures.append(f"action table should have no data rows: {table.notes}")
        if table.notes["row_template_row"] != 1:
            failures.append(f"row template should be the empty row: {table.notes}")

    if not any(region.locator.notes for region in schema.regions):
        failures.append("speaker notes not detected as a region")
    return failures


def check_refusals(schema, original: bytes) -> list[str]:
    failures = []
    protected = pc.protected_shapes_from_schema(schema)
    if len(protected) < 2:
        failures.append(f"expected the logo and chart to be protected, got {protected}")

    logo = next(r for r in schema.regions if r.kind == "branding")
    chart = next(r for r in schema.regions if r.kind == "derived")

    for region in (logo, chart):
        try:
            pc.set_text(schema, region.region_id, "overwritten")
            failures.append(f"set_text built an op for {region.kind} region")
        except pc.RegionNotEditableError:
            pass

    # A raw op aimed at the logo must not survive pre-flight either.
    try:
        pc.compile_pptx_spec(
            original,
            [pc.SetTextOp(logo.locator.slide_part, logo.locator.shape_id, "x")],
            protected=protected,
        )
        failures.append("writing the logo shape was allowed")
    except pc.ProtectedShapeError:
        pass

    try:
        pc.set_text(schema, "slide1.not_a_real_region", "x")
        failures.append("unknown region_id was accepted")
    except pc.UnknownRegionError:
        pass

    try:
        pc.set_table_rows(schema, "slide6.table_sl_no", [{"Nonexistent": "x"}])
        failures.append("unknown column name was accepted")
    except pc.UnknownRegionError:
        pass

    # Bullets are not the same shape as a single-value field.
    title = next(r for r in schema.regions if r.kind == "title")
    try:
        pc.set_bullets(schema, title.region_id, ["a", "b"])
        failures.append("set_bullets accepted a title region")
    except pc.RegionNotEditableError:
        pass
    return failures


def check_formatting(data: bytes, schema) -> list[str]:
    """Cloned paragraphs and rows must inherit formatting, not reset it.

    Two mechanisms, checked separately because they live in different places in
    the XML. This deck styles most text at *paragraph* level (`<a:pPr>` holds an
    `<a:defRPr sz>`), which survives because every new paragraph and table row
    is a deepcopy of an existing one. The subtitle is styled at *run* level
    (`<a:rPr sz i>`), which survives only because overwriting text keeps the
    first run rather than replacing the text body.
    """
    failures = []
    presentation = Presentation(io.BytesIO(data))
    slides = {
        str(slide.part.partname).lstrip("/"): slide for slide in presentation.slides
    }

    def shape_for(region_id: str):
        region = next(r for r in schema.regions if r.region_id == region_id)
        return next(
            s
            for s in slides[region.locator.slide_part].shapes
            if s.shape_id == region.locator.shape_id
        )

    # -- paragraph-level: cloned bullets --------------------------------
    agenda = shape_for("slide2.content_placeholder_2")
    sizes = {paragraph.font.size for paragraph in agenda.text_frame.paragraphs}
    if sizes != {Pt(18)}:
        failures.append(f"agenda bullets lost their 18pt paragraph size: {sizes}")
    if len(agenda.text_frame.paragraphs) != len(AGENDA):
        failures.append(
            f"agenda has {len(agenda.text_frame.paragraphs)} paragraphs, want {len(AGENDA)}"
        )

    # -- run-level: overwritten subtitle --------------------------------
    subtitle = shape_for("slide1.subtitle_2")
    runs = subtitle.text_frame.paragraphs[0].runs
    if len(runs) != 1:
        failures.append(f"subtitle should hold one run, has {len(runs)}")
    elif runs[0].font.size != Pt(16) or not runs[0].font.italic:
        failures.append(
            f"subtitle lost its run formatting: size={runs[0].font.size} "
            f"italic={runs[0].font.italic}"
        )

    # -- paragraph-level: cloned table rows -----------------------------
    table_region = next(r for r in schema.regions if r.kind == "table_loop")
    table = shape_for(table_region.region_id).table
    if len(table.rows) != 1 + len(ACTION_ROWS):
        failures.append(f"table has {len(table.rows)} rows, want {1 + len(ACTION_ROWS)}")
    header = [table.cell(0, column).text for column in range(len(table.columns))]
    if header != ["Sl.No.", "Action", "Responsibility", "Target date", "Status"]:
        failures.append(f"table header was overwritten: {header}")
    if not table.cell(0, 0).text_frame.paragraphs[0].font.bold:
        failures.append("table header lost its bold")
    data_sizes = {
        table.cell(row, column).text_frame.paragraphs[0].font.size
        for row in range(1, len(table.rows))
        for column in range(len(table.columns))
    }
    if data_sizes != {Pt(14)}:
        failures.append(f"cloned table rows lost their 14pt size: {data_sizes}")
    return failures


def main() -> int:
    if not TEMPLATE_PATH.exists():
        print(f"template not found: {TEMPLATE_PATH}")
        print("run: uv run python scripts/build_workshop_readout_template.py")
        return 1

    print("python-pptx round-trip measurement:")
    failures = check_round_trip()

    original = TEMPLATE_PATH.read_bytes()
    schema = detect_regions_pptx(original)
    before = fingerprint_pptx(original)
    print(
        f"\ntemplate: {len(before.package_parts)} parts, {before.slides} slides, "
        f"{before.shapes} shapes, {before.pictures} picture, {before.charts} chart, "
        f"{before.embedded_workbooks} embedded workbook"
    )
    print(
        f"detected: {len(schema.regions)} regions "
        f"({len(schema.writable())} writable) {schema.counts_by_kind()}"
    )
    failures += check_detection(schema)
    failures += check_refusals(schema, original)

    spec = [
        pc.set_text(schema, "slide1.title", "Workshop Readout - AP Invoice Header Capture"),
        pc.set_text(
            schema,
            "slide1.subtitle_2",
            "Accounts Payable - Cycle 2  |  YMSLI / YMESG  |  20-Aug-2026",
        ),
        pc.set_text(schema, "slide1.speaker_notes", "Circulated to both entities on 21-Aug-2026."),
        pc.set_bullets(schema, "slide2.content_placeholder_2", AGENDA),
        pc.set_text(schema, "slide3.title", "Decision: Invoice uniqueness key"),
        pc.set_bullets(schema, "slide3.content_placeholder_2", DECISION_BULLETS),
        pc.set_table_rows(schema, "slide6.table_sl_no", ACTION_ROWS),
    ]
    result = pc.compile_pptx_spec(
        original, spec, protected=pc.protected_shapes_from_schema(schema)
    )
    after = fingerprint_pptx(result.data)
    print(
        f"compiled: {result.operations_applied} ops, {result.rows_added} table rows added, "
        f"{result.paragraphs_written} bullets written, {len(result.assertions)} assertions"
    )

    try:
        structural = diff_pptx_fingerprints(
            before, after, expected_row_delta=result.rows_added
        )
        print(
            f"structural QA: PASS -- parts {len(before.package_parts)}->"
            f"{len(after.package_parts)}, shapes {after.shapes}, picture {after.pictures}, "
            f"chart {after.charts}, embedded workbook {after.embedded_workbooks}, "
            f"table rows {structural.table_rows_before}->{structural.table_rows_after}, "
            f"text runs {structural.text_runs_before}->{structural.text_runs_after}"
        )
    except Exception as exc:  # noqa: BLE001 - report, don't mask
        failures.append(f"structural QA: {exc}")

    try:
        functional = check_pptx_assertions(result.data, result.assertions)
        print(f"functional QA: PASS -- {len(functional.checks)} values verified")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"functional QA: {exc}")

    failures += check_formatting(result.data, schema)

    # The derived deck must still be readable as a template by the detector.
    derived_schema = detect_regions_pptx(result.data)
    derived_table = next(
        (r for r in derived_schema.regions if r.kind in ("table_loop", "table_data")), None
    )
    if derived_table is None or derived_table.kind != "table_data":
        failures.append(
            f"filled action table should re-read as table_data, got "
            f"{derived_table.kind if derived_table else None}"
        )
    elif derived_table.notes["row_count"] != len(ACTION_ROWS):
        failures.append(
            f"derived table row_count={derived_table.notes['row_count']}, "
            f"want {len(ACTION_ROWS)}"
        )

    print(f"\nwrote {write_artifact(OUTPUT_PATH, result.data)}")

    if failures:
        print(f"\npptx pipeline: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\npptx pipeline: PASS -- open the deck to confirm the logo, chart and table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
