"""Structural fingerprint for xlsx package integrity checks.

openpyxl's own save() silently drops zip parts it has no model for (rich-value
images, sensitivity labels, richData). The fingerprint captures package-level
facts read directly from the zip/XML -- not through openpyxl's object model,
which has its own blind spots (e.g. read-only worksheets don't even expose
merged_cells) -- so a before/after compile can prove nothing was lost.
"""

import io
import re
import zipfile
from dataclasses import dataclass

_SHEET_NAME_RE = re.compile(r'<sheet\b[^>]*\bname="([^"]*)"')
_MERGE_COUNT_ATTR_RE = re.compile(r'<mergeCells\s+count="(\d+)"')
_MERGE_CELL_TAG_RE = re.compile(r"<mergeCell\b")
_FORMULA_TAG_RE = re.compile(r"<f\b")


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
        sensitivity_label="docMetadata/LabelInfo.xml" in parts,
    )
