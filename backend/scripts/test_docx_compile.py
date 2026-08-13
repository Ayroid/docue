"""T3 end-to-end: derive a new BRD from the real one. Read-only on the source.

    uv run python scripts/test_docx_compile.py

The plan's Tier-3 case (§3.1) on the docx side, driven entirely by `region_id`
and never by a hand-typed paragraph index:

  * a field rewritten, keeping its label verbatim
  * a prose block **grown** from 3 items to 5, which pushes every paragraph
    below it down by two
  * a list block **shrunk** from 8 items to 3, which pulls everything below it
    up by five
  * two rows appended to the work-item table
  * one row appended to the in-document revision block -- plan §1.3's
    write-back, so the version history travels with the file

All five addressed in *original* coordinates in one spec.

Then it proves the result four ways: structural QA (nothing lost, and the
paragraph/row/cell counts moved by exactly the declared amount), functional QA
(every value present at its final address), a second region-detection pass over
the output, and a package comparison showing which parts came through
byte-for-byte.

It also checks the guarantees hold in the negative: writing over an image,
editing a non-editable region, naming a region that doesn't exist, naming a
column that doesn't exist, rewriting a paragraph whose text lives inside a
hyperlink, and cloning the revision block's short row all fail.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import docx  # noqa: E402
from lxml import etree  # noqa: E402

from _artifact import write_artifact  # noqa: E402

from app.compiler import docx_compiler as dc  # noqa: E402
from app.ingestion.fingerprint_docx import fingerprint_docx  # noqa: E402
from app.ingestion.regions_docx import detect_regions_docx  # noqa: E402
from app.qa.functional_docx import check_docx_assertions  # noqa: E402
from app.qa.structural_docx import diff_docx_fingerprints  # noqa: E402

SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "Files" / "BRD Sample.docx"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "scratch" / "BRD_T3_derived.docx"

PREPARED_BY = "doc.prepared_by"
GROWN_BLOCK = "doc.description"  # paras 83-85, 3 prose items
SHRUNK_BLOCK = "doc.acceptance_criteria_4"  # paras 227-234, 8 numbered items
WORK_ITEMS = "doc.items_9_summary"  # table 1, 9 data rows
REVISION_BLOCK = "doc.document_revision"  # table 0, the house pattern

DESCRIPTION_ITEMS = [
    "As a Financial Accounting SME, I want capital acquisition requests captured "
    "against the approved AP header field mapping, so that every acquisition is "
    "traceable to an approved request.",
    "The process covers the Accounts Payable automation thread from cycle 1, "
    "extended to invoice header capture for capital items.",
    "Duplicate invoice detection treats vendor plus invoice number as the "
    "uniqueness key, and the same key governs capital acquisition invoices.",
    "Non-PO capital invoices route through a separate approval workflow with cost "
    "centre coding at line level.",
    "Tax determination for capital acquisitions derives GST treatment from vendor "
    "registration and place of supply.",
]

ACCEPTANCE_ITEMS = [
    "Users should be able to generate an acquisition proposal per asset or in batch.",
    "Approvers should be able to review, approve or reject with comments.",
    "Only approved capital acquisition requests should proceed to asset creation.",
]

WORK_ITEM_ROWS = [
    {
        "Item": "10",
        "Type": "Feature",
        "Name": "[YNS] 55.10.040 Capture AP invoice header for capital items",
        "Area Path": "YNS-FnO-ANZ-ERP\\55. Acquire To Dispose",
    },
    {
        "Item": "11",
        "Type": "User Story",
        "Name": "Duplicate invoice detection on vendor plus invoice number",
        "Area Path": "YNS-FnO-ANZ-ERP\\55. Acquire To Dispose",
    },
]

REVISION_ROW = {
    "Ver.": "2.0",
    "Date": "13/08/2026",
    "Updated by": "TemplateHub",
    "Revision summary": "AP automation cycle 2",
    "Description": "Derived from Ver. 1.0 for invoice header capture",
}


def build_spec(schema) -> list:
    """Every target named by region_id -- no paragraph index is typed by hand."""
    return [
        dc.set_field(schema, PREPARED_BY, "YMSLI Digital Transformation Office"),
        dc.replace_region_rows(schema, GROWN_BLOCK, DESCRIPTION_ITEMS),
        dc.replace_region_rows(schema, SHRUNK_BLOCK, ACCEPTANCE_ITEMS),
        dc.add_table_rows(schema, WORK_ITEMS, WORK_ITEM_ROWS),
        dc.append_history_row(schema, REVISION_BLOCK, REVISION_ROW),
    ]


def check_guarantees(schema, original: bytes) -> list[str]:
    """The refusals matter as much as the writes."""
    failures = []
    protected = dc.protected_targets_from_schema(schema)
    drawing_regions = [r for r in schema.regions if r.kind == "branding"]
    if not drawing_regions:
        failures.append("no protected region covers an image paragraph")
    if not any(t.para_index is not None for t in protected):
        failures.append("no protected target covers a paragraph")

    # A raw op aimed at an image paragraph must not survive pre-flight.
    image_para = drawing_regions[0].locator.para_index if drawing_regions else 1
    try:
        dc.compile_change_spec(
            original,
            [dc.SetTextOp(para_index=image_para, text="overwritten")],
            protected=protected,
        )
        failures.append(f"writing image paragraph {image_para} was allowed")
    except dc.ProtectedWriteError:
        pass

    # The bridge won't even build an op for a non-editable region.
    title = next((r for r in schema.regions if r.kind == "title"), None)
    if title is not None:
        try:
            dc.set_field(schema, title.region_id, "overwritten")
            failures.append("set_field built an op for a title region")
        except dc.RegionNotEditableError:
            pass

    # An invented region_id is refused rather than guessed at.
    try:
        dc.set_field(schema, "doc.not_a_real_region", "x")
        failures.append("unknown region_id was accepted")
    except dc.UnknownRegionError:
        pass

    # An unknown column inside a real region is refused too.
    try:
        dc.add_table_rows(schema, WORK_ITEMS, [{"Nonexistent Column": "x"}])
        failures.append("unknown column name was accepted")
    except dc.UnknownRegionError:
        pass

    # Plan §1.2 ⑤'s sibling trap: text inside a <w:hyperlink> is invisible to
    # Paragraph.runs, so a run-level rewrite would garble it *and* leave the
    # hyperlink count unchanged, passing structural QA. Must fail in the compiler.
    document = docx.Document(io.BytesIO(original))
    hyperlink_para = next(
        (
            index
            for index, paragraph in enumerate(document.paragraphs)
            if "".join(run.text for run in paragraph.runs) != paragraph.text
        ),
        None,
    )
    if hyperlink_para is None:
        failures.append("no hyperlink-bearing paragraph found to test the guard")
    else:
        try:
            dc.compile_change_spec(
                original, [dc.SetTextOp(para_index=hyperlink_para, text="overwritten")]
            )
            failures.append(
                f"rewriting hyperlink paragraph {hyperlink_para} was allowed"
            )
        except dc.CompilerError as exc:
            if "hyperlink" not in str(exc):
                failures.append(f"hyperlink refusal should name the cause: {exc}")

    # The ragged-row landmine: the revision block's populated row carries five
    # of nine cells, so cloning *it* silently drops the approval columns.
    revision = schema.by_id(REVISION_BLOCK)
    if revision is None:
        failures.append(f"{REVISION_BLOCK} not detected")
    else:
        if revision.notes["cells_per_row"] != [9, 5, 9]:
            failures.append(
                f"revision block cell counts {revision.notes['cells_per_row']}, want [9, 5, 9]"
            )
        try:
            dc.compile_change_spec(
                original,
                [
                    dc.CloneTableRowsOp(
                        table_index=revision.locator.table_index,
                        at_row=3,
                        rows=[{8: "Approved by someone"}],
                        row_template_row=1,  # the short row
                    )
                ],
            )
            failures.append("cloning the 5-cell row and writing cell 8 was allowed")
        except dc.CompilerError as exc:
            if "template_row" not in str(exc):
                failures.append(f"short-row error should point at template_row: {exc}")

    return failures


def check_output_geometry(schema, data: bytes) -> list[str]:
    """Where things ended up, computed independently of the compiler."""
    failures = []
    output = detect_regions_docx(data)

    # The grown block: 3 items -> 5, still a repeating_block, still captioned.
    grown = output.by_id(GROWN_BLOCK)
    if grown is None:
        failures.append(f"{GROWN_BLOCK} no longer detected in the output")
    else:
        if grown.notes["item_count"] != len(DESCRIPTION_ITEMS):
            failures.append(
                f"grown block item_count={grown.notes['item_count']}, "
                f"want {len(DESCRIPTION_ITEMS)}"
            )
        if grown.locator.para_span != [83, 87]:
            failures.append(f"grown block at {grown.locator.para_span}, want [83, 87]")

    # The shrunk block moved up by 5 - 8 = -3 net of the +2 above it.
    shrunk = [
        r
        for r in output.regions
        if r.kind == "repeating_block" and r.label == "Acceptance Criteria"
    ]
    if not shrunk:
        failures.append("no Acceptance Criteria block in the output")
    else:
        last = shrunk[-1]
        if last.notes["item_count"] != len(ACCEPTANCE_ITEMS):
            failures.append(
                f"shrunk block item_count={last.notes['item_count']}, "
                f"want {len(ACCEPTANCE_ITEMS)}"
            )

    # No empty list items left behind by the shrink.
    document = docx.Document(io.BytesIO(data))
    blank_numbered = [
        index
        for index, paragraph in enumerate(document.paragraphs)
        if not paragraph.text.strip()
        and paragraph._p.pPr is not None
        and paragraph._p.pPr.numPr is not None
    ]
    if blank_numbered:
        failures.append(
            f"{len(blank_numbered)} empty numbered list item(s) left behind: "
            f"{blank_numbered[:8]} -- these render as stray bullets in Word"
        )

    # The work-item table gained two rows and reads as a populated table.
    work_items = output.by_id(WORK_ITEMS)
    if work_items is None:
        failures.append(f"{WORK_ITEMS} no longer detected")
    elif work_items.notes["row_count"] != 9 + len(WORK_ITEM_ROWS):
        failures.append(
            f"work-item table row_count={work_items.notes['row_count']}, "
            f"want {9 + len(WORK_ITEM_ROWS)}"
        )

    # The revision block now declares Ver. 2.0 -- read back out of the document.
    revision = output.by_id(REVISION_BLOCK)
    if revision is None:
        failures.append(f"{REVISION_BLOCK} no longer detected")
    else:
        if revision.notes.get("in_doc_version") != "2.0":
            failures.append(
                f"in-document version reads {revision.notes.get('in_doc_version')!r}, want '2.0'"
            )
        if output.notes.get("in_doc_version") != "2.0":
            failures.append("schema-level in_doc_version not updated")

    # Every image still classified as branding, none of it editable.
    branding = [r for r in output.regions if r.kind == "branding"]
    if len(branding) != 6:
        failures.append(f"{len(branding)} branding regions in the output, want 6")

    return failures


def check_package(original: bytes, data: bytes) -> tuple[list[str], str]:
    """Which parts came through untouched -- the package-integrity claim."""
    failures = []
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(
        io.BytesIO(data)
    ) as result:
        source_names = sorted(source.namelist())
        result_names = sorted(result.namelist())
        if source_names != result_names:
            failures.append(
                f"part list changed: lost {sorted(set(source_names) - set(result_names))}, "
                f"added {sorted(set(result_names) - set(source_names))}"
            )
        identical = [n for n in result_names if source.read(n) == result.read(n)]
        media = [n for n in result_names if n.startswith("word/media/")]
        if any(source.read(n) != result.read(n) for n in media):
            failures.append("a media file is not byte-identical to the original")
        for name in result_names:
            if name.endswith((".xml", ".rels")):
                try:
                    etree.fromstring(result.read(name))
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{name} is not well-formed XML: {exc}")
        summary = (
            f"{len(identical)}/{len(result_names)} parts byte-identical, "
            f"{len(media)} media files byte-identical, all XML well-formed"
        )
    return failures, summary


def main() -> int:
    if not SAMPLE_PATH.exists():
        print(f"sample not found: {SAMPLE_PATH}")
        return 1

    original = SAMPLE_PATH.read_bytes()
    schema = detect_regions_docx(original)
    before = fingerprint_docx(original)
    print(
        f"source: {len(before.package_parts)} parts, {before.body_paragraphs} body "
        f"paragraphs, {before.drawings} drawings ({before.inline_drawings} inline / "
        f"{before.anchored_drawings} anchored), {before.hyperlinks} hyperlinks, "
        f"{len(schema.regions)} regions ({len(schema.writable())} writable)"
    )
    print(
        f"        python-docx inline_shapes reports "
        f"{len(docx.Document(io.BytesIO(original)).inline_shapes)} of "
        f"{before.drawings} drawings -- why the fingerprint counts <w:drawing>"
    )

    failures = check_guarantees(schema, original)

    spec = build_spec(schema)
    result = dc.compile_change_spec(
        original, spec, protected=dc.protected_targets_from_schema(schema)
    )
    after = fingerprint_docx(result.data)
    print(
        f"compiled: {len(spec)} ops -> {result.operations_applied} primitives, "
        f"{result.rows_inserted} rows inserted, {result.paragraphs_inserted} paragraphs "
        f"inserted, {result.paragraphs_removed} removed, "
        f"{len(result.assertions)} assertions, packaging={result.packaging}"
    )

    # Derived independently of the compiler: +2 paragraphs from growing the
    # description block 3->5, -5 from shrinking acceptance criteria 8->3,
    # +2 work-item rows of 4 cells, +1 revision row of 9 cells.
    expected_body_delta = 2 - 5
    expected_rows = len(WORK_ITEM_ROWS) + 1
    expected_cells = len(WORK_ITEM_ROWS) * 4 + 9
    declared = result.expected_delta
    if declared.body_paragraphs != expected_body_delta:
        failures.append(
            f"declared body paragraph delta {declared.body_paragraphs:+d}, "
            f"want {expected_body_delta:+d}"
        )
    if declared.table_rows != expected_rows:
        failures.append(f"declared row delta {declared.table_rows}, want {expected_rows}")
    if declared.table_cells != expected_cells:
        failures.append(
            f"declared cell delta {declared.table_cells}, want {expected_cells}"
        )

    try:
        structural = diff_docx_fingerprints(before, after, expected=declared)
        print(
            f"structural QA: PASS -- parts lost {structural.lost_parts}, "
            f"preserved {structural.preserved}, body paragraphs "
            f"{before.body_paragraphs}->{after.body_paragraphs}, rows "
            f"{before.table_rows}->{after.table_rows}"
        )
    except Exception as exc:  # noqa: BLE001 - report, don't mask
        failures.append(f"structural QA: {exc}")

    try:
        functional = check_docx_assertions(result.data, result.assertions)
        print(f"functional QA: PASS -- {len(functional.checks)} values verified in place")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"functional QA: {exc}")

    package_failures, package_summary = check_package(original, result.data)
    failures += package_failures
    print(f"package    QA: {package_summary}")

    failures += check_output_geometry(schema, result.data)

    # The library packaging path has to stay correct too -- it is the fallback
    # when an edit legitimately needs a package-level change.
    try:
        library = dc.compile_change_spec(
            original,
            build_spec(schema),
            protected=dc.protected_targets_from_schema(schema),
            repackage=False,
        )
        diff_docx_fingerprints(
            before, fingerprint_docx(library.data), expected=library.expected_delta
        )
        with zipfile.ZipFile(io.BytesIO(library.data)) as archive, zipfile.ZipFile(
            io.BytesIO(original)
        ) as source:
            kept = sum(
                1 for n in archive.namelist() if archive.read(n) == source.read(n)
            )
        print(
            f"library QA: PASS -- packaging={library.packaging}, "
            f"{kept}/{len(before.package_parts)} parts byte-identical "
            f"(surgical keeps more, which is the point)"
        )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"library packaging: {exc}")

    print()
    print("landmarks in the derived document:")
    output = docx.Document(io.BytesIO(result.data))
    for label, index in (
        ("prepared by (label kept)", 16),
        ("description item 1 (rewritten)", 83),
        ("description item 5 (inserted)", 87),
    ):
        print(f"  {label:<34} para {index}: {output.paragraphs[index].text[:58]!r}")
    print(f"  {'revision block Ver. 2.0':<34} {[c.text for c in output.tables[0].rows[2].cells][:5]}")
    print(f"  {'work item row 10 (appended)':<34} {[c.text for c in output.tables[1].rows[10].cells][:3]}")

    print(f"\nwrote {write_artifact(OUTPUT_PATH, result.data)}")

    if failures:
        print(f"\ndocx compile: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        "\ndocx compile: PASS -- open the file in real Word to confirm all 5 images, "
        "the revision block and the list formatting"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
