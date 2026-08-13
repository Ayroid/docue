"""Structural primitives for editing one worksheet part as text.

Row insertion is the reason this module exists. Adding a row to a sheet means
renumbering every `<row r>` below it, rewriting every `<c r>` inside those
rows, shifting every `<mergeCell ref>` that sits below the insertion point,
and widening `<dimension ref>` -- all while every other byte of the package
stays exactly as Excel wrote it. None of that is expressible as one regex, and
none of it should go through a library that re-serialises the whole workbook.

Two deliberate choices:

- **Element boundaries are found by `str.find`, not by a regex that scans for
  a closing tag.** Whole-grid styling leaves tens of thousands of
  self-closing `<c/>` elements per sheet; a pattern that looks past the tag
  for `</c>` backtracks across the entire part on each one and hangs.
- **Nothing here parses values.** These helpers move and blank cells; what a
  cell *means* (a string, an Excel date serial) belongs to the ops layer.
"""

import re
from dataclasses import dataclass

from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

_ROW_NUMBER_RE = re.compile(r'\br="(\d+)"')
_CELL_REF_RE = re.compile(r'\br="([A-Z]+)(\d+)"')
_SINGLE_REF_RE = re.compile(r"([A-Z]+)(\d+)")
_STYLE_RE = re.compile(r'\bs="(\d+)"')
_SPANS_RE = re.compile(r'\bspans="[^"]*"')
_SPANS_VALUE_RE = re.compile(r'\bspans="(\d+):(\d+)"')
_SHEETDATA_EMPTY_RE = re.compile(r"<sheetData\s*/>")
_MERGE_BLOCK_RE = re.compile(r"<mergeCells\b[^>]*>.*?</mergeCells>|<mergeCells\b[^>]*/>", re.DOTALL)
_MERGE_REF_RE = re.compile(r'<mergeCell\s+ref="([^"]+)"')
_DIMENSION_RE = re.compile(r'<dimension\s+ref="([^"]+)"\s*/>')
_FORMULA_RE = re.compile(r"<f[ >/]")

# `mergeCells` has a fixed position in the CT_Worksheet sequence. If a sheet
# has no merges yet and we need to add some, the new element has to go after
# whichever of these is present, not just after </sheetData>.
_ELEMENTS_BEFORE_MERGECELLS = (
    "</sheetData>",
    "</sheetCalcPr>",
    "</sheetProtection>",
    "</protectedRanges>",
    "</scenarios>",
    "</autoFilter>",
    "<autoFilter",
    "</sortState>",
    "</dataConsolidate>",
    "</customSheetViews>",
)


@dataclass
class Row:
    """One `<row>` element, kept as text so untouched attributes survive."""

    number: int
    text: str


class SheetSurgeryError(RuntimeError):
    """The sheet contains something this module would silently corrupt."""


# ── refs ──────────────────────────────────────────────────────────────────


def split_ref(ref: str) -> tuple[str, int]:
    match = _SINGLE_REF_RE.fullmatch(ref)
    if match is None:
        raise ValueError(f"not a single-cell ref: {ref!r}")
    return match.group(1), int(match.group(2))


def ref_column(ref: str) -> str:
    return split_ref(ref)[0]


def ref_row(ref: str) -> int:
    return split_ref(ref)[1]


def bounds(ref: str) -> tuple[int, int, int, int]:
    """(min_col, min_row, max_col, max_row) for `A1` or `A1:G3`."""
    return range_boundaries(ref)  # type: ignore[return-value]


def cells_in_range(ref: str) -> list[str]:
    min_col, min_row, max_col, max_row = bounds(ref)
    return [
        f"{get_column_letter(col)}{row}"
        for row in range(min_row, max_row + 1)
        for col in range(min_col, max_col + 1)
    ]


# ── sheetData ─────────────────────────────────────────────────────────────


def read_rows(xml: str) -> list[Row]:
    """Every `<row>` in document order."""
    inner, _, _ = _sheet_data_span(xml)
    rows: list[Row] = []
    position = 0
    while True:
        start = inner.find("<row", position)
        if start == -1:
            return rows
        end = _element_end(inner, start, "row")
        text = inner[start:end]
        number_match = _ROW_NUMBER_RE.search(text[: text.find(">") + 1])
        if number_match is None:
            raise SheetSurgeryError(f"<row> without an r attribute: {text[:60]!r}")
        rows.append(Row(number=int(number_match.group(1)), text=text))
        position = end


def write_rows(xml: str, rows: list[Row]) -> str:
    body = "".join(row.text for row in sorted(rows, key=lambda row: row.number))
    if _SHEETDATA_EMPTY_RE.search(xml):
        return _SHEETDATA_EMPTY_RE.sub(f"<sheetData>{body}</sheetData>", xml, count=1)
    _, start, end = _sheet_data_span(xml)
    return xml[:start] + body + xml[end:]


def _sheet_data_span(xml: str) -> tuple[str, int, int]:
    """(inner text, inner start, inner end) of `<sheetData>`."""
    if _SHEETDATA_EMPTY_RE.search(xml):
        return "", 0, 0
    open_start = xml.find("<sheetData")
    if open_start == -1:
        raise SheetSurgeryError("worksheet has no <sheetData>")
    inner_start = xml.find(">", open_start) + 1
    inner_end = xml.find("</sheetData>", inner_start)
    if inner_end == -1:
        raise SheetSurgeryError("unterminated <sheetData>")
    return xml[inner_start:inner_end], inner_start, inner_end


def _element_end(text: str, start: int, tag: str) -> int:
    """End offset of the element beginning at `start`, self-closing or not."""
    open_end = text.find(">", start)
    if open_end == -1:
        raise SheetSurgeryError(f"unterminated <{tag}>")
    if text[open_end - 1] == "/":
        return open_end + 1
    close = text.find(f"</{tag}>", open_end)
    if close == -1:
        raise SheetSurgeryError(f"unterminated <{tag}>")
    return close + len(tag) + 3


# ── rows and cells ────────────────────────────────────────────────────────


def read_cells(row_text: str) -> list[str]:
    """Every `<c>` element of a row, in document order."""
    cells: list[str] = []
    position = row_text.find(">") + 1  # skip the <row> open tag
    while True:
        start = row_text.find("<c", position)
        if start == -1:
            return cells
        end = _element_end(row_text, start, "c")
        cells.append(row_text[start:end])
        position = end


def row_open_tag(row_text: str) -> str:
    return row_text[: row_text.find(">") + 1]


def assemble_row(open_tag: str, cells: list[str]) -> str:
    body = "".join(cells)
    if open_tag.endswith("/>"):
        open_tag = open_tag[:-2] + ">"
    return f"{open_tag}{body}</row>"


def cell_ref(cell_text: str) -> str:
    match = _CELL_REF_RE.search(cell_text[: cell_text.find(">") + 1])
    if match is None:
        raise SheetSurgeryError(f"<c> without an r attribute: {cell_text[:60]!r}")
    return f"{match.group(1)}{match.group(2)}"


def cell_style(cell_text: str) -> str | None:
    match = _STYLE_RE.search(cell_text[: cell_text.find(">") + 1])
    return match.group(1) if match else None


def blank_cell(cell_text: str) -> str:
    """Drop a cell's value and type, keep its ref and style index."""
    ref = cell_ref(cell_text)
    style = cell_style(cell_text)
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{style_attr}/>'


def set_cell(row_text: str, cell_xml: str) -> str:
    """Replace the cell at this ref, or insert it in column order."""
    target_ref = cell_ref(cell_xml)
    target_col = column_index_from_string(ref_column(target_ref))
    cells = read_cells(row_text)

    for index, existing in enumerate(cells):
        existing_col = column_index_from_string(ref_column(cell_ref(existing)))
        if existing_col == target_col:
            cells[index] = cell_xml
            break
        if existing_col > target_col:
            cells.insert(index, cell_xml)
            break
    else:
        cells.append(cell_xml)

    return assemble_row(row_open_tag(row_text), cells)


def shift_row(row: Row, delta: int) -> Row:
    """Move a row and every cell in it down by `delta`."""
    if delta == 0:
        return row
    return retarget_row(row, row.number + delta)


def retarget_row(row: Row, number: int) -> Row:
    open_tag = _ROW_NUMBER_RE.sub(f'r="{number}"', row_open_tag(row.text), count=1)
    cells = [
        _CELL_REF_RE.sub(lambda m: f'r="{m.group(1)}{number}"', cell, count=1)
        for cell in read_cells(row.text)
    ]
    return Row(number=number, text=assemble_row(open_tag, cells))


def blank_row(row: Row) -> Row:
    """Same row, same styles, no values -- the shape a cloned row starts from."""
    cells = [blank_cell(cell) for cell in read_cells(row.text)]
    return Row(number=row.number, text=assemble_row(row_open_tag(row.text), cells))


def restyle_cell(cell_text: str, style: str) -> str:
    open_end = cell_text.find(">") + 1
    head, tail = cell_text[:open_end], cell_text[open_end:]
    if _STYLE_RE.search(head):
        head = _STYLE_RE.sub(f's="{style}"', head, count=1)
    else:
        suffix = "/>" if head.endswith("/>") else ">"
        head = f'{head[: -len(suffix)]} s="{style}"{suffix}'
    return head + tail


def row_spans(row_text: str) -> tuple[int, int] | None:
    match = _SPANS_VALUE_RE.search(row_open_tag(row_text))
    return (int(match.group(1)), int(match.group(2))) if match else None


def covered_by_spans(row_text: str, column: str) -> bool:
    """Does the row's existing `spans` already cover this column?

    Worth asking before rewriting the attribute. `spans` is advisory, and the
    MOM declares `spans="1:13"` on rows holding only columns A-G -- recomputing
    it on every edit would rewrite bytes Excel wrote and we have no reason to
    touch.
    """
    spans = row_spans(row_text)
    if spans is None:
        return False
    index = column_index_from_string(column)
    return spans[0] <= index <= spans[1]


def set_row_spans(row: Row) -> Row:
    """Recompute `spans` from the cells actually present."""
    cells = read_cells(row.text)
    if not cells:
        return row
    columns = [column_index_from_string(ref_column(cell_ref(cell))) for cell in cells]
    spans = f'spans="{min(columns)}:{max(columns)}"'
    open_tag = row_open_tag(row.text)
    if _SPANS_RE.search(open_tag):
        open_tag = _SPANS_RE.sub(spans, open_tag, count=1)
    else:
        suffix = "/>" if open_tag.endswith("/>") else ">"
        open_tag = f"{open_tag[: -len(suffix)]} {spans}{suffix}"
    return Row(number=row.number, text=assemble_row(open_tag, cells))


def row_has_formula(row: Row) -> bool:
    return bool(_FORMULA_RE.search(row.text))


def cell_has_formula(cell_text: str) -> bool:
    return bool(_FORMULA_RE.search(cell_text))


# ── merges ────────────────────────────────────────────────────────────────


def read_merges(xml: str) -> list[str]:
    block = _MERGE_BLOCK_RE.search(xml)
    return _MERGE_REF_RE.findall(block.group(0)) if block else []


def write_merges(xml: str, refs: list[str]) -> str:
    ordered = sorted(refs, key=lambda ref: bounds(ref)[1::-1])
    block = _MERGE_BLOCK_RE.search(xml)
    if not ordered:
        return xml[: block.start()] + xml[block.end() :] if block else xml

    body = "".join(f'<mergeCell ref="{ref}"/>' for ref in ordered)
    element = f'<mergeCells count="{len(ordered)}">{body}</mergeCells>'
    if block:
        return xml[: block.start()] + element + xml[block.end() :]

    for marker in _ELEMENTS_BEFORE_MERGECELLS:
        position = xml.rfind(marker)
        if position != -1:
            insert_at = (
                position + len(marker)
                if marker.startswith("</")
                else xml.find(">", position) + 1
            )
            return xml[:insert_at] + element + xml[insert_at:]
    raise SheetSurgeryError("nowhere valid to put <mergeCells>")


def shift_merges(refs: list[str], at_row: int, delta: int) -> list[str]:
    """Move merges that start at or below `at_row` down by `delta`.

    A merge straddling the insertion point is grown rather than moved, which
    is what Excel does when you insert a row inside a vertically merged cell.
    """
    shifted = []
    for ref in refs:
        min_col, min_row, max_col, max_row = bounds(ref)
        if min_row >= at_row:
            min_row += delta
            max_row += delta
        elif max_row >= at_row:
            max_row += delta
        shifted.append(
            f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"
        )
    return shifted


def merges_within_row(refs: list[str], row_number: int) -> list[tuple[int, int]]:
    """(min_col, max_col) for every merge contained in one row."""
    spans = []
    for ref in refs:
        min_col, min_row, max_col, max_row = bounds(ref)
        if min_row == max_row == row_number:
            spans.append((min_col, max_col))
    return spans


def merge_ref(min_col: int, max_col: int, row_number: int) -> str:
    return (
        f"{get_column_letter(min_col)}{row_number}:{get_column_letter(max_col)}{row_number}"
    )


# ── dimension ─────────────────────────────────────────────────────────────


def extend_dimension(xml: str, max_row: int, max_col: int | None = None) -> str:
    match = _DIMENSION_RE.search(xml)
    if match is None:
        return xml
    min_col, min_row, current_max_col, current_max_row = bounds(match.group(1))
    new_max_col = max(current_max_col, max_col or 0)
    new_max_row = max(current_max_row, max_row)
    ref = (
        f"{get_column_letter(min_col)}{min_row}:"
        f"{get_column_letter(new_max_col)}{new_max_row}"
    )
    return xml[: match.start()] + f'<dimension ref="{ref}"/>' + xml[match.end() :]
