"""Structural fingerprints for package integrity checks.

openpyxl's own save() silently drops zip parts it has no model for (rich-value
images, sensitivity labels, richData). The fingerprint captures package-level
facts read directly from the zip/XML -- not through openpyxl's object model,
which has its own blind spots (e.g. read-only worksheets don't even expose
merged_cells) -- so a before/after compile can prove nothing was lost.

pptx gets the same treatment for the same reason, even though python-pptx was
measured to round-trip losslessly: the guarantee is worth checking on every
compile rather than trusting once. Note which pptx counts are invariants and
which legitimately move -- shapes, media, charts and the label must never
change, while text runs and table cells change whenever content does.
"""

import io
import re
import zipfile
from dataclasses import dataclass

_SHEET_NAME_RE = re.compile(r'<sheet\b[^>]*\bname="([^"]*)"')
_MERGE_COUNT_ATTR_RE = re.compile(r'<mergeCells\s+count="(\d+)"')
_MERGE_CELL_TAG_RE = re.compile(r"<mergeCell\b")
_FORMULA_TAG_RE = re.compile(r"<f\b")

_SLIDE_PART_RE = re.compile(r"^ppt/slides/slide\d+\.xml$")
_TEXT_RUN_RE = re.compile(r"<a:t>")
_TABLE_RE = re.compile(r"<a:tbl>")
_TABLE_ROW_RE = re.compile(r"<a:tr\b")
_TABLE_CELL_RE = re.compile(r"<a:tc\b")
_PICTURE_RE = re.compile(r"<p:pic\b")
_SHAPE_RE = re.compile(r"<p:(sp|pic|graphicFrame|grpSp|cxnSp)\b")
_LABEL_PART = "docMetadata/LabelInfo.xml"


@dataclass
class Fingerprint:
    package_parts: list[str]
    sheets: list[str]
    merged_ranges: int
    formula_cells: int
    drawings: int
    rich_value_parts: int
    media_files: int
    sensitivity_label: bool


def fingerprint_xlsx(data: bytes) -> Fingerprint:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = sorted(archive.namelist())

        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        sheets = _SHEET_NAME_RE.findall(workbook_xml)

        merged_ranges = 0
        formula_cells = 0
        for part in parts:
            if not (part.startswith("xl/worksheets/") and part.endswith(".xml")):
                continue
            sheet_xml = archive.read(part).decode("utf-8")
            merge_attr_match = _MERGE_COUNT_ATTR_RE.search(sheet_xml)
            merged_ranges += (
                int(merge_attr_match.group(1))
                if merge_attr_match
                else len(_MERGE_CELL_TAG_RE.findall(sheet_xml))
            )
            formula_cells += len(_FORMULA_TAG_RE.findall(sheet_xml))

    return Fingerprint(
        package_parts=parts,
        sheets=sheets,
        merged_ranges=merged_ranges,
        formula_cells=formula_cells,
        drawings=sum(1 for p in parts if p.startswith("xl/drawings/") and p.endswith(".xml")),
        rich_value_parts=sum(1 for p in parts if p.startswith("xl/richData/")),
        media_files=sum(1 for p in parts if p.startswith("xl/media/")),
        sensitivity_label=_LABEL_PART in parts,
    )


@dataclass
class PptxFingerprint:
    package_parts: list[str]
    slides: int
    slide_layouts: int
    slide_masters: int
    notes_slides: int
    shapes: int  # sp | pic | graphicFrame | grpSp | cxnSp, across slides
    text_runs: int  # <a:t> elements -- moves with content, by design
    tables: int
    table_rows: int
    table_cells: int
    pictures: int
    charts: int
    embedded_workbooks: int  # a chart carries its data in its own xlsx part
    media_files: int
    sensitivity_label: bool


def fingerprint_pptx(data: bytes) -> PptxFingerprint:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = sorted(archive.namelist())

        shapes = text_runs = tables = table_rows = table_cells = pictures = 0
        for part in parts:
            if not _SLIDE_PART_RE.match(part):
                continue
            slide_xml = archive.read(part).decode("utf-8")
            shapes += len(_SHAPE_RE.findall(slide_xml))
            text_runs += len(_TEXT_RUN_RE.findall(slide_xml))
            tables += len(_TABLE_RE.findall(slide_xml))
            table_rows += len(_TABLE_ROW_RE.findall(slide_xml))
            table_cells += len(_TABLE_CELL_RE.findall(slide_xml))
            pictures += len(_PICTURE_RE.findall(slide_xml))

    return PptxFingerprint(
        package_parts=parts,
        slides=sum(1 for p in parts if _SLIDE_PART_RE.match(p)),
        slide_layouts=sum(
            1 for p in parts if p.startswith("ppt/slideLayouts/slideLayout")
        ),
        slide_masters=sum(
            1 for p in parts if p.startswith("ppt/slideMasters/slideMaster")
        ),
        notes_slides=sum(
            1 for p in parts if p.startswith("ppt/notesSlides/notesSlide")
        ),
        shapes=shapes,
        text_runs=text_runs,
        tables=tables,
        table_rows=table_rows,
        table_cells=table_cells,
        pictures=pictures,
        charts=sum(
            1 for p in parts if p.startswith("ppt/charts/chart") and p.endswith(".xml")
        ),
        embedded_workbooks=sum(1 for p in parts if p.startswith("ppt/embeddings/")),
        media_files=sum(1 for p in parts if p.startswith("ppt/media/")),
        sensitivity_label=_LABEL_PART in parts,
    )
