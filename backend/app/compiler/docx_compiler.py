"""docx compiler: run-level edits through python-docx, surgically repackaged.

Different strategy per format, justified by measurement. `xlsx_surgical.py`
rewrites worksheet XML inside the zip by hand because openpyxl provably
destroys the MOM -- nine package parts including the logo. docx is the opposite
case: measured on `BRD Sample.docx`, a python-docx round-trip loses nothing (34
parts in, 34 out, 6 drawings and 14 hyperlinks intact), so the edits go through
the library and stay readable.

Three properties hold across a whole spec, matching the xlsx compiler:

- **Every locator is in original-document coordinates.** A spec that rewrites
  paragraph 83 and also grows a block at paragraph 112 doesn't have to know
  which of the two moves. Text writes are applied before insertions, and
  insertions are applied bottom-up, so the `para_index` a caller read off the
  region schema is the one that works.
- **The result reports where things landed.** `CompileResult.assertions` gives
  final coordinates and expected values, which is plan §11's functional QA pass
  with no extra bookkeeping.
- **Formatting is inherited, never invented.** New rows and paragraphs are
  `deepcopy`s of ones already in the document, so they carry the real borders,
  shading, row heights and numbering. Nothing is synthesised.

And two refusals that are specific to Word:

- **A paragraph whose text is not wholly owned by its plain runs is never
  written.** In the BRD, 14 paragraphs keep text inside `<w:hyperlink>`
  elements that `Paragraph.runs` does not return; three have no runs at all.
  Rewriting run 0 and clearing the rest would leave the hyperlink's text in
  place beside the new text, and because the `<w:hyperlink>` element survives
  the structural fingerprint would still count 14 and pass. So this is checked
  in the compiler, not left to QA.
- **A row or paragraph containing a drawing or a hyperlink is never cloned.**
  Copying it would duplicate the reference and inflate the drawing count -- a
  second logo on the page.

Packaging: python-docx re-serialises every part it parsed, so by default the
result is reassembled from the *original* zip with only `word/document.xml`
replaced. That gives docx the same part-level guarantee the xlsx compiler has
-- media, customXml, docProps, headers, styles and any sensitivity label come
through byte-for-byte -- and it is refused outright if the edit would have
needed a package-level change (a new part or a new relationship), because that
is the one case where copying the old parts would silently drop something.
"""

import copy
import io
import zipfile
from dataclasses import dataclass, field
from typing import Any, Literal, Union

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.ingestion.fingerprint_docx import parse_relationships

# Shared exception types, imported rather than redefined: a caller wrapping a
# compile catches the same errors whichever format it handed in. These names
# are part of the frozen interface from plan §3.2.
from app.compiler.protect import ProtectedWriteError
from app.compiler.region_ops import RegionNotEditableError, UnknownRegionError
from app.compiler.xlsx_surgical import CompilerError

ValueType = Literal["string", "number", "date"]

BODY_PART = "word/document.xml"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

__all__ = [
    "BODY_PART",
    "CloneTableRowsOp",
    "ClearRegionOp",
    "CompileResult",
    "CompilerError",
    "DocxAssertion",
    "Operation",
    "ProtectOp",
    "ProtectedTarget",
    "ProtectedWriteError",
    "RegionNotEditableError",
    "ReplaceBlockItemsOp",
    "ReplaceTableRowsOp",
    "SetTextOp",
    "UnknownRegionError",
    "add_table_rows",
    "append_history_row",
    "clear_region",
    "compile_change_spec",
    "apply_change_spec",
    "preflight_docx",
    "protected_targets_from_schema",
    "replace_region_rows",
    "set_field",
    "set_text",
]


# ── operations ────────────────────────────────────────────────────────────


@dataclass
class SetTextOp:
    """Replace one paragraph's text, keeping its first run's formatting.

    `text` is the *whole* final paragraph text. A field region carries its
    label prefix (`'Prepared by: '`) in the schema, and `set_field` puts it
    back in front of the new value, so the wording around a value is
    reproduced verbatim rather than re-typed.
    """

    para_index: int
    text: str
    value_type: ValueType = "string"
    part: str = BODY_PART


@dataclass
class ClearRegionOp:
    """Blank a region's text, keeping runs, rows and formatting in place.

    Blanks rather than deletes, for the same reason the xlsx compiler does: an
    empty styled row is a recoverable state where a removed one isn't.
    """

    para_index: int | None = None
    para_span: tuple[int, int] | None = None  # inclusive
    table_index: int | None = None
    row_span: tuple[int, int] | None = None  # inclusive data rows
    part: str = BODY_PART


@dataclass
class CloneTableRowsOp:
    """Insert table rows, cloning an existing row's cells and styling.

    `rows` are keyed by cell index. `row_template_row` supplies the cells --
    which matters more than it sounds: the BRD's revision block has nine grid
    columns but its populated row carries only five `<w:tc>`, so cloning *that*
    row would produce five-cell rows and drop the approval columns. The region
    schema records the widest data row as `template_row` for exactly this.
    """

    table_index: int
    at_row: int
    rows: list[dict[int, Any]]
    row_template_row: int
    value_types: dict[int, ValueType] = field(default_factory=dict)
    part: str = BODY_PART


@dataclass
class ReplaceTableRowsOp:
    """Rewrite a table's data rows: fill what exists, then grow or blank."""

    table_index: int
    first_row: int
    last_row: int  # inclusive
    rows: list[dict[int, Any]]
    row_template_row: int | None = None
    value_types: dict[int, ValueType] = field(default_factory=dict)
    part: str = BODY_PART


@dataclass
class ReplaceBlockItemsOp:
    """Rewrite a paragraph block's items: fill what exists, then grow or blank.

    The docx counterpart of `replace_region_rows` on the xlsx side. Growth
    clones the block's last paragraph, so a new list item keeps the numbering
    and indentation of the ones above it.
    """

    para_span: tuple[int, int]  # inclusive
    items: list[str]
    part: str = BODY_PART


@dataclass
class ProtectOp:
    """A declaration, not an edit: no other op may write inside this region."""

    para_index: int | None = None
    para_span: tuple[int, int] | None = None
    table_index: int | None = None
    row_span: tuple[int, int] | None = None
    reason: str = ""
    part: str = BODY_PART


Operation = Union[
    SetTextOp,
    ClearRegionOp,
    CloneTableRowsOp,
    ReplaceTableRowsOp,
    ReplaceBlockItemsOp,
    ProtectOp,
]


@dataclass
class DocxAssertion:
    """An expected value at a *final* locator -- feeds functional QA."""

    expected: Any
    value_type: ValueType = "string"
    para_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    part: str = BODY_PART

    @property
    def ref(self) -> str:
        if self.para_index is not None:
            return f"para {self.para_index}"
        return f"table {self.table_index} row {self.row_index} cell {self.cell_index}"


@dataclass
class CompileResult:
    data: bytes
    rows_inserted: int
    paragraphs_inserted: int
    paragraphs_removed: int
    operations_applied: int
    assertions: list[DocxAssertion]
    packaging: str  # "surgical" | "library"

    @property
    def expected_delta(self) -> Any:
        """The structural change this compile intends, for `structural_docx`.

        Every cloned table cell brings one `<w:p>` with it, which is why the
        raw paragraph delta is the body delta plus the cell count. QA rejects
        anything other than this, so declaring it is stricter than tolerating
        change. Imported lazily so the compiler doesn't depend on the QA layer.
        """
        from app.qa.structural_docx import ExpectedDelta

        body_delta = self.paragraphs_inserted - self.paragraphs_removed
        return ExpectedDelta(
            paragraphs=body_delta + self._cells_inserted,
            body_paragraphs=body_delta,
            tables=0,
            table_rows=self.rows_inserted,
            table_cells=self._cells_inserted,
        )

    _cells_inserted: int = 0


# ── write protection, enforced before any bytes are touched ────────────────


@dataclass(frozen=True)
class ProtectedTarget:
    """A region no operation may write. Mirrors `protect.ProtectedRange`."""

    para_index: int | None = None
    para_span: tuple[int, int] | None = None
    table_index: int | None = None
    row_span: tuple[int, int] | None = None
    reason: str = ""
    region_id: str | None = None
    part: str = BODY_PART

    @property
    def paragraphs(self) -> tuple[int, int] | None:
        if self.para_span is not None:
            return self.para_span
        if self.para_index is not None:
            return (self.para_index, self.para_index)
        return None

    def describe(self) -> str:
        return f"{self.region_id or self.reason or 'protected'}"


def protected_targets_from_schema(schema: object) -> list[ProtectedTarget]:
    """Lift every protected region out of a docx `DocumentSchema`.

    Typed loosely on purpose, exactly as `protect.protected_ranges_from_schema`
    is: the compiler stays independent of the ingestion layer and this is the
    one place the two meet.
    """
    targets: list[ProtectedTarget] = []
    for region in getattr(schema, "regions", []):
        if not region.protected:
            continue
        locator = region.locator
        targets.append(
            ProtectedTarget(
                para_index=locator.para_index,
                para_span=tuple(locator.para_span) if locator.para_span else None,
                table_index=locator.table_index,
                row_span=tuple(locator.row_span) if locator.row_span else None,
                reason=region.kind,
                region_id=region.region_id,
                part=locator.part,
            )
        )
    return targets


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _paragraph_targets(op: Operation) -> tuple[int, int] | None:
    if isinstance(op, SetTextOp):
        return (op.para_index, op.para_index)
    if isinstance(op, ClearRegionOp):
        if op.para_span is not None:
            return op.para_span
        if op.para_index is not None:
            return (op.para_index, op.para_index)
    if isinstance(op, ReplaceBlockItemsOp):
        return op.para_span
    if isinstance(op, (_ClonePargraphsOp, _RemoveParagraphsOp)):
        return op.para_span
    return None


def _table_target(op: Operation) -> tuple[int, tuple[int, int] | None] | None:
    if isinstance(op, ClearRegionOp) and op.table_index is not None:
        return (op.table_index, op.row_span)
    if isinstance(op, CloneTableRowsOp):
        return (op.table_index, (op.at_row, op.at_row))
    if isinstance(op, ReplaceTableRowsOp):
        return (op.table_index, (op.first_row, op.last_row))
    if isinstance(op, _RowValuesOp):
        return (op.table_index, (op.row_index, op.row_index))
    return None


def preflight_docx(
    operations: list[Operation], protected: list[ProtectedTarget]
) -> None:
    """Raise `ProtectedWriteError` if any operation would write a protected region.

    Runs over the whole spec before a single byte changes, so a bad spec
    produces an exception instead of a half-written file.
    """
    targets = list(protected)
    for op in operations:
        if isinstance(op, ProtectOp):
            targets.append(
                ProtectedTarget(
                    para_index=op.para_index,
                    para_span=op.para_span,
                    table_index=op.table_index,
                    row_span=op.row_span,
                    reason=op.reason or "declared",
                    part=op.part,
                )
            )
    if not targets:
        return

    for op in operations:
        if isinstance(op, ProtectOp):
            continue
        paragraphs = _paragraph_targets(op)
        table = _table_target(op)
        for guarded in targets:
            if getattr(op, "part", BODY_PART) != guarded.part:
                continue

            guarded_paragraphs = guarded.paragraphs
            if paragraphs is not None and guarded_paragraphs is not None:
                if _overlaps(paragraphs, guarded_paragraphs):
                    raise ProtectedWriteError(
                        f"{type(op).__name__} targets paragraphs {paragraphs[0]}-"
                        f"{paragraphs[1]} which intersects protected "
                        f"{guarded_paragraphs[0]}-{guarded_paragraphs[1]} "
                        f"({guarded.describe()}) in {guarded.part}"
                    )
            if table is not None and guarded.table_index == table[0]:
                rows, guarded_rows = table[1], guarded.row_span
                if guarded_rows is None or rows is None or _overlaps(rows, guarded_rows):
                    raise ProtectedWriteError(
                        f"{type(op).__name__} targets table {table[0]} rows "
                        f"{rows} which intersects protected {guarded_rows or 'whole table'} "
                        f"({guarded.describe()}) in {guarded.part}"
                    )
            # An insertion strictly above a protected region shifts it without
            # damaging it -- that is what Word itself does when a user inserts
            # a row. One *inside* it would tear it in half.
            if isinstance(op, CloneTableRowsOp) and guarded.table_index == op.table_index:
                if guarded.row_span and guarded.row_span[0] < op.at_row <= guarded.row_span[1]:
                    raise ProtectedWriteError(
                        f"inserting at table {op.table_index} row {op.at_row} would split "
                        f"protected rows {guarded.row_span} ({guarded.describe()})"
                    )


# ── per-document edit session ─────────────────────────────────────────────


def _run_text(paragraph: Any) -> str:
    return "".join(run.text for run in paragraph.runs)


def _new_run_from_paragraph_mark(paragraph_element: Any) -> Any:
    """Append a run to `<w:p>`, inheriting the paragraph mark's formatting.

    An empty paragraph or an empty table cell has no run to copy character
    formatting from, but Word keeps the formatting of the paragraph mark in
    `w:pPr/w:rPr` -- which is precisely what the next character typed there
    would pick up. The BRD's revision block relies on this: the spare row's
    cells hold no runs at all, and their `rFonts minorHAnsi` lives on the
    paragraph mark. A run created without it renders the new version row in the
    document default font instead of the table's theme font.
    """
    run = paragraph_element.makeelement(f"{W}r", {})
    properties = paragraph_element.find(qn("w:pPr"))
    if properties is not None:
        mark_properties = properties.find(qn("w:rPr"))
        if mark_properties is not None:
            run.append(copy.deepcopy(mark_properties))
    paragraph_element.append(run)
    return run


def _has_foreign_content(element: Any) -> str | None:
    """Content a run-level writer must not clone or overwrite.

    A drawing would be duplicated into a second image; a hyperlink would be
    duplicated into a second link that the fingerprint *would* catch, and a
    rewritten one into garbled text that it would not.
    """
    for tag, what in ((f"{W}drawing", "a drawing"), (f"{W}hyperlink", "a hyperlink")):
        if element.find(f".//{tag}") is not None or element.find(tag) is not None:
            return what
    return None


class _DocumentEditor:
    """Accumulates edits to one document, then renders it once."""

    def __init__(self, data: bytes) -> None:
        self.original = data
        self.document = docx.Document(io.BytesIO(data))
        # Cached in original order. python-docx recomputes `paragraphs` and
        # `rows` on every access by walking the tree, so an insertion would
        # renumber them mid-spec; holding the objects means an index resolved
        # here keeps pointing at the same element afterwards.
        self.paragraphs = list(self.document.paragraphs)
        self.tables = list(self.document.tables)
        self.original_rows = {
            index: list(table.rows) for index, table in enumerate(self.tables)
        }
        self.rows_inserted = 0
        self.paragraphs_inserted = 0
        self.paragraphs_removed = 0
        self.cells_inserted = 0

    # -- reads ---------------------------------------------------------

    def _paragraph(self, index: int) -> Any:
        if not 0 <= index < len(self.paragraphs):
            raise CompilerError(
                f"paragraph {index} does not exist ({len(self.paragraphs)} body "
                f"paragraphs in {BODY_PART})"
            )
        return self.paragraphs[index]

    def _table(self, index: int) -> Any:
        if not 0 <= index < len(self.tables):
            raise CompilerError(
                f"table {index} does not exist ({len(self.tables)} tables in {BODY_PART})"
            )
        return self.tables[index]

    def _row(self, table_index: int, row_index: int) -> Any:
        rows = self.original_rows[table_index]
        if not 0 <= row_index < len(rows):
            raise CompilerError(
                f"table {table_index} row {row_index} does not exist "
                f"({len(rows)} rows)"
            )
        return rows[row_index]

    # -- writes --------------------------------------------------------

    def set_text(self, op: SetTextOp) -> None:
        paragraph = self._paragraph(op.para_index)
        self._guard_writable(paragraph, op.para_index)
        self._write_paragraph(paragraph, op.text)

    def _guard_writable(self, paragraph: Any, para_index: int) -> None:
        if _run_text(paragraph) != paragraph.text:
            foreign = _has_foreign_content(paragraph._p) or "content outside its runs"
            raise CompilerError(
                f"paragraph {para_index} holds text inside {foreign}, which "
                f"`Paragraph.runs` does not expose. A run-level write would leave "
                f"that text in place beside the new text and the hyperlink count "
                f"would not change, so the corruption would pass structural QA. "
                f"Refusing: this region should be `immutable` in the schema."
            )

    @staticmethod
    def _write_paragraph(paragraph: Any, text: str) -> None:
        """All the text into the first run; the rest keep their properties, empty.

        The paragraph therefore takes run 0's character formatting -- size,
        weight, colour -- which is the formatting the template author gave the
        value. Blanking the trailing runs rather than deleting them keeps the
        change reversible and touches no element counts.
        """
        runs = paragraph.runs
        if runs:
            runs[0].text = text
            for run in runs[1:]:
                run.text = ""
            return
        if not text:
            return  # nothing to clear, and no reason to add an empty run
        run_element = _new_run_from_paragraph_mark(paragraph._p)
        text_element = run_element.makeelement(f"{W}t", {})
        run_element.append(text_element)
        text_element.text = text
        if text != text.strip():
            text_element.set(qn("xml:space"), "preserve")

    def clear(self, op: ClearRegionOp) -> None:
        if op.para_index is not None or op.para_span is not None:
            span = op.para_span or (op.para_index, op.para_index)
            for index in range(span[0], span[1] + 1):
                paragraph = self._paragraph(index)
                self._guard_writable(paragraph, index)
                self._write_paragraph(paragraph, "")
            return
        if op.table_index is None:
            raise CompilerError("ClearRegionOp names no paragraph and no table")
        rows = self.original_rows[self._checked_table_index(op.table_index)]
        span = op.row_span or (1, len(rows) - 1)
        for row_index in range(span[0], span[1] + 1):
            self._clear_row(self._row(op.table_index, row_index))

    def _checked_table_index(self, table_index: int) -> int:
        self._table(table_index)
        return table_index

    def _clear_row(self, row: Any) -> None:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                if _run_text(paragraph) != paragraph.text:
                    continue  # foreign content: leave it rather than garble it
                self._write_paragraph(paragraph, "")

    def write_row_values(
        self,
        table_index: int,
        row_index: int,
        payload: dict[int, Any],
        value_types: dict[int, ValueType],
    ) -> None:
        """Fill cells of a row that already exists, leaving its styling alone."""
        self._write_tr(
            self._row(table_index, row_index)._tr,
            payload,
            value_types,
            table_index,
            row_index,
        )

    def insert_rows(self, op: CloneTableRowsOp) -> list[tuple[int, dict[int, Any]]]:
        """Insert `op.rows` at `op.at_row`. Returns (row index, payload) pairs."""
        if not op.rows:
            return []
        table = self._table(op.table_index)
        template = self._row(op.table_index, op.row_template_row)
        foreign = _has_foreign_content(template._tr)
        if foreign is not None:
            raise CompilerError(
                f"table {op.table_index} row {op.row_template_row} contains {foreign}; "
                f"cloning it would duplicate the reference. Choose another template row."
            )
        if op.at_row < 1:
            raise CompilerError(
                f"cannot insert at table {op.table_index} row {op.at_row}: row 0 is the "
                f"header row"
            )

        rows = self.original_rows[op.table_index]
        anchor = rows[min(op.at_row, len(rows)) - 1]._tr
        cells_per_row = len(template._tr.findall(f"{W}tc"))

        placed: list[tuple[int, dict[int, Any]]] = []
        for offset, payload in enumerate(op.rows):
            new_tr = copy.deepcopy(template._tr)
            anchor.addnext(new_tr)
            anchor = new_tr
            self._blank_tr(new_tr)
            row_index = op.at_row + offset
            self._write_tr(new_tr, payload, op.value_types, op.table_index, row_index)
            placed.append((row_index, payload))
            self.cells_inserted += cells_per_row

        self.rows_inserted += len(op.rows)
        # `table.rows` is recomputed from the tree, so the clones are visible
        # immediately; the cached originals stay in original coordinates.
        _ = table
        return placed

    @staticmethod
    def _blank_tr(tr: Any) -> None:
        """Empty a cloned row's cells, keeping one formatted run per cell."""
        for cell in tr.findall(f"{W}tc"):
            paragraphs = cell.findall(f"{W}p")
            for extra in paragraphs[1:]:
                cell.remove(extra)
            if not paragraphs:
                continue
            paragraph = paragraphs[0]
            runs = paragraph.findall(f"{W}r")
            for extra in runs[1:]:
                paragraph.remove(extra)
            for run in runs[:1]:
                for text_element in run.findall(f"{W}t"):
                    text_element.text = ""

    def _write_tr(
        self,
        tr: Any,
        payload: dict[int, Any],
        value_types: dict[int, ValueType],
        table_index: int,
        row_index: int,
    ) -> None:
        cells = tr.findall(f"{W}tc")
        for cell_index, value in sorted(payload.items()):
            if not 0 <= cell_index < len(cells):
                raise CompilerError(
                    f"table {table_index} row {row_index}: cell index {cell_index} is "
                    f"outside the cloned row's {len(cells)} cells. The template row "
                    f"may be a short one -- the schema records `template_row` as the "
                    f"widest data row for this reason."
                )
            self._write_tc(cells[cell_index], "" if value is None else str(value))

    @staticmethod
    def _write_tc(tc: Any, text: str) -> None:
        paragraphs = tc.findall(f"{W}p")
        if not paragraphs:  # pragma: no cover - a w:tc always holds a w:p
            paragraph = tc.makeelement(f"{W}p", {})
            tc.append(paragraph)
            paragraphs = [paragraph]
        paragraph = paragraphs[0]
        runs = paragraph.findall(f"{W}r")
        if runs:
            run = runs[0]
            text_elements = run.findall(f"{W}t")
            if text_elements:
                target = text_elements[0]
                for extra in text_elements[1:]:
                    run.remove(extra)
            else:
                target = run.makeelement(f"{W}t", {})
                run.append(target)
        else:
            run = _new_run_from_paragraph_mark(paragraph)
            target = run.makeelement(f"{W}t", {})
            run.append(target)
        target.text = text
        if text != text.strip():
            target.set(qn("xml:space"), "preserve")

    def insert_paragraphs(self, span: tuple[int, int], items: list[str]) -> list[tuple[int, str]]:
        """Clone the block's last paragraph once per extra item."""
        if not items:
            return []
        template = self._paragraph(span[1])
        foreign = _has_foreign_content(template._p)
        if foreign is not None:
            raise CompilerError(
                f"paragraph {span[1]} contains {foreign}; cloning it would duplicate "
                f"the reference. It should not be the last paragraph of a writable block."
            )

        anchor = template._p
        placed: list[tuple[int, str]] = []
        for offset, text in enumerate(items):
            new_p = copy.deepcopy(template._p)
            anchor.addnext(new_p)
            anchor = new_p
            paragraph = Paragraph(new_p, template._parent)
            self._write_paragraph(paragraph, text)
            placed.append((span[1] + 1 + offset, text))

        self.paragraphs_inserted += len(items)
        return placed

    def remove_paragraphs(self, span: tuple[int, int]) -> int:
        """Drop a shrinking block's surplus paragraphs, bottom-up."""
        removed = 0
        for index in range(span[1], span[0] - 1, -1):
            paragraph = self._paragraph(index)
            self._guard_writable(paragraph, index)
            foreign = _has_foreign_content(paragraph._p)
            if foreign is not None:  # pragma: no cover - the guard above catches these
                raise CompilerError(
                    f"paragraph {index} contains {foreign}; refusing to remove it"
                )
            parent = paragraph._p.getparent()
            if parent is None:  # pragma: no cover - a body paragraph always has one
                continue
            parent.remove(paragraph._p)
            removed += 1
        self.paragraphs_removed += removed
        return removed

    # -- render --------------------------------------------------------

    def render(self, *, repackage: bool) -> tuple[bytes, str]:
        buffer = io.BytesIO()
        self.document.save(buffer)
        saved = buffer.getvalue()
        if not repackage:
            return saved, "library"
        return _repackage(self.original, saved), "surgical"


def _rel_set(xml: bytes) -> set[tuple[str, str, str, str]]:
    return set(parse_relationships(xml.decode("utf-8", "replace")))


def _repackage(original: bytes, saved: bytes) -> bytes:
    """Rebuild the package from the original zip, swapping in the new body part.

    Everything python-docx re-serialised but did not semantically change --
    styles, numbering, content types, relationships -- is discarded in favour
    of the bytes Word itself wrote. If the edit *did* need a package-level
    change, this is refused rather than applied, because that is the one case
    where copying the old parts would silently drop the new one.
    """
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(
        io.BytesIO(saved)
    ) as edited:
        source_parts = set(source.namelist())
        edited_parts = set(edited.namelist())
        if source_parts != edited_parts:
            raise CompilerError(
                "the edit changed the package part list "
                f"(added {sorted(edited_parts - source_parts)}, "
                f"lost {sorted(source_parts - edited_parts)}); "
                "surgical repackaging would drop it. Recompile with repackage=False."
            )
        for part in sorted(p for p in source_parts if p.endswith(".rels")):
            if _rel_set(source.read(part)) != _rel_set(edited.read(part)):
                raise CompilerError(
                    f"the edit changed relationships in {part}; surgical repackaging "
                    "would drop them. Recompile with repackage=False."
                )

        body = edited.read(BODY_PART)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as destination:
            for item in source.infolist():
                if item.filename == BODY_PART:
                    destination.writestr(item, body)
                else:
                    destination.writestr(item, source.read(item.filename))
    return buffer.getvalue()


# ── spec compilation ──────────────────────────────────────────────────────


def _expand_table(op: ReplaceTableRowsOp) -> list[Operation]:
    """Decompose `replace_region_rows` over a table into primitives.

    Fill the rows the table already has; grow it if there are more rows than
    fit; blank the leftovers if there are fewer.
    """
    existing = op.last_row - op.first_row + 1
    template_row = op.row_template_row or op.first_row
    expanded: list[Operation] = []

    for offset, payload in enumerate(op.rows[:existing]):
        expanded.append(
            _RowValuesOp(
                table_index=op.table_index,
                row_index=op.first_row + offset,
                payload=payload,
                value_types=op.value_types,
                part=op.part,
            )
        )
    if len(op.rows) > existing:
        expanded.append(
            CloneTableRowsOp(
                table_index=op.table_index,
                at_row=op.last_row + 1,
                rows=op.rows[existing:],
                row_template_row=template_row,
                value_types=op.value_types,
                part=op.part,
            )
        )
    elif len(op.rows) < existing:
        expanded.append(
            ClearRegionOp(
                table_index=op.table_index,
                row_span=(op.first_row + len(op.rows), op.last_row),
                part=op.part,
            )
        )
    return expanded


def _expand_block(op: ReplaceBlockItemsOp) -> list[Operation]:
    first, last = op.para_span
    existing = last - first + 1
    expanded: list[Operation] = []
    for offset, text in enumerate(op.items[:existing]):
        expanded.append(SetTextOp(para_index=first + offset, text=text, part=op.part))
    if len(op.items) > existing:
        expanded.append(
            _ClonePargraphsOp(
                para_span=op.para_span, items=op.items[existing:], part=op.part
            )
        )
    elif len(op.items) < existing:
        # Surplus paragraphs are *removed*, not blanked -- the one place this
        # compiler deliberately diverges from the xlsx side. There, an unused
        # row is blanked because an empty styled row is a recoverable state and
        # a deleted one isn't. Here the block's paragraphs are usually numbered
        # list items, and a blanked one renders in Word as a bullet or a number
        # with nothing after it. Leaving five of those behind after rewriting an
        # eight-item section to three is a visible defect, not a recoverable
        # state. A paragraph is not a fixed slot the way a spreadsheet row is.
        expanded.append(
            _RemoveParagraphsOp(
                para_span=(first + len(op.items), last), part=op.part
            )
        )
    return expanded


@dataclass
class _RowValuesOp:
    """Write values into an existing table row. Internal: produced by expansion."""

    table_index: int
    row_index: int
    payload: dict[int, Any]
    value_types: dict[int, ValueType] = field(default_factory=dict)
    part: str = BODY_PART


@dataclass
class _ClonePargraphsOp:
    """Grow a paragraph block. Internal: produced by expansion."""

    para_span: tuple[int, int]
    items: list[str]
    part: str = BODY_PART


@dataclass
class _RemoveParagraphsOp:
    """Drop a shrinking block's surplus paragraphs. Internal: produced by expansion."""

    para_span: tuple[int, int]
    part: str = BODY_PART


def compile_change_spec(
    original_bytes: bytes,
    operations: list[Operation],
    *,
    protected: list[ProtectedTarget] | None = None,
    repackage: bool = True,
) -> CompileResult:
    """Apply a Change Spec to a docx and report what it did.

    `protected` targets (from the region schema) are enforced alongside any
    `ProtectOp` in the spec itself: the pre-flight runs before a single byte is
    touched, so a spec that would write over an image fails without producing a
    file at all.
    """
    editor = _DocumentEditor(original_bytes)

    flat: list[Operation] = []
    for op in operations:
        if isinstance(op, ReplaceTableRowsOp):
            flat.extend(_expand_table(op))
        elif isinstance(op, ReplaceBlockItemsOp):
            flat.extend(_expand_block(op))
        else:
            flat.append(op)

    # Every op, expansions included, is checked before a byte moves.
    preflight_docx(flat, protected or [])

    clear_ops = [op for op in flat if isinstance(op, ClearRegionOp)]
    text_ops = [op for op in flat if isinstance(op, SetTextOp)]
    row_value_ops = [op for op in flat if isinstance(op, _RowValuesOp)]
    insert_ops = [op for op in flat if isinstance(op, CloneTableRowsOp)]
    block_ops = [op for op in flat if isinstance(op, _ClonePargraphsOp)]
    removal_ops = [op for op in flat if isinstance(op, _RemoveParagraphsOp)]

    for op in clear_ops:
        editor.clear(op)
    for op in text_ops:
        editor.set_text(op)
    for op in row_value_ops:
        editor.write_row_values(op.table_index, op.row_index, op.payload, op.value_types)

    # Bottom-up, so a structural edit never invalidates an index still to be
    # used. This is what makes original-document coordinates valid across a
    # whole spec: insertions and removals are interleaved in one descending
    # pass, because a spec may grow one block and shrink another.
    row_placements: list[tuple[CloneTableRowsOp, list[tuple[int, dict[int, Any]]]]] = []
    for op in sorted(insert_ops, key=lambda op: op.at_row, reverse=True):
        row_placements.append((op, editor.insert_rows(op)))

    block_placements: list[tuple[_ClonePargraphsOp, list[tuple[int, str]]]] = []
    for op in sorted(
        block_ops + removal_ops, key=lambda op: op.para_span[1], reverse=True
    ):
        if isinstance(op, _RemoveParagraphsOp):
            editor.remove_paragraphs(op.para_span)
        else:
            block_placements.append((op, editor.insert_paragraphs(op.para_span, op.items)))

    assertions = _assertions(
        text_ops,
        row_value_ops,
        row_placements,
        block_placements,
        insert_ops,
        block_ops,
        removal_ops,
    )

    data, packaging = editor.render(repackage=repackage)
    result = CompileResult(
        data=data,
        rows_inserted=editor.rows_inserted,
        paragraphs_inserted=editor.paragraphs_inserted,
        paragraphs_removed=editor.paragraphs_removed,
        operations_applied=len(clear_ops)
        + len(text_ops)
        + len(row_value_ops)
        + len(insert_ops)
        + len(block_ops)
        + len(removal_ops),
        assertions=assertions,
        packaging=packaging,
    )
    result._cells_inserted = editor.cells_inserted
    return result


def _paragraph_shift(
    para_index: int,
    block_ops: list[_ClonePargraphsOp],
    removal_ops: list[_RemoveParagraphsOp],
    exclude: tuple[int, int] | None,
) -> int:
    """How far an original-coordinate paragraph moves once the edits land.

    Growth above it pushes it down, removal above it pulls it up. Only edits
    strictly above count: an op never moves its own target.
    """
    delta = sum(
        len(op.items)
        for op in block_ops
        if op.para_span[1] < para_index and op.para_span != exclude
    )
    delta -= sum(
        op.para_span[1] - op.para_span[0] + 1
        for op in removal_ops
        if op.para_span[1] < para_index
    )
    return delta


def _row_shift(
    table_index: int, row_index: int, insert_ops: list[CloneTableRowsOp], exclude: int | None
) -> int:
    return sum(
        len(op.rows)
        for op in insert_ops
        if op.table_index == table_index and op.at_row <= row_index and op.at_row != exclude
    )


def _assertions(
    text_ops: list[SetTextOp],
    row_value_ops: list[_RowValuesOp],
    row_placements: list[tuple[CloneTableRowsOp, list[tuple[int, dict[int, Any]]]]],
    block_placements: list[tuple[_ClonePargraphsOp, list[tuple[int, str]]]],
    insert_ops: list[CloneTableRowsOp],
    block_ops: list[_ClonePargraphsOp],
    removal_ops: list[_RemoveParagraphsOp],
) -> list[DocxAssertion]:
    assertions: list[DocxAssertion] = []

    for op in text_ops:
        if not op.text:
            continue
        final = op.para_index + _paragraph_shift(
            op.para_index, block_ops, removal_ops, exclude=None
        )
        assertions.append(
            DocxAssertion(
                expected=op.text,
                value_type=op.value_type,
                para_index=final,
                part=op.part,
            )
        )
    for op in row_value_ops:
        final_row = op.row_index + _row_shift(
            op.table_index, op.row_index, insert_ops, exclude=None
        )
        for cell_index, value in op.payload.items():
            if value is None or value == "":
                continue
            assertions.append(
                DocxAssertion(
                    expected=str(value),
                    value_type=op.value_types.get(cell_index, "string"),
                    table_index=op.table_index,
                    row_index=final_row,
                    cell_index=cell_index,
                    part=op.part,
                )
            )
    for op, placed in row_placements:
        for row_index, payload in placed:
            final_row = row_index + _row_shift(
                op.table_index, row_index, insert_ops, exclude=op.at_row
            )
            for cell_index, value in payload.items():
                if value is None or value == "":
                    continue
                assertions.append(
                    DocxAssertion(
                        expected=str(value),
                        value_type=op.value_types.get(cell_index, "string"),
                        table_index=op.table_index,
                        row_index=final_row,
                        cell_index=cell_index,
                        part=op.part,
                    )
                )
    for op, placed in block_placements:
        for para_index, text in placed:
            final = para_index + _paragraph_shift(
                para_index, block_ops, removal_ops, exclude=op.para_span
            )
            assertions.append(
                DocxAssertion(expected=text, para_index=final, part=op.part)
            )
    return assertions


def apply_change_spec(original_bytes: bytes, operations: list[Operation]) -> bytes:
    """Compile a spec and return just the bytes."""
    return compile_change_spec(original_bytes, operations).data


# ── region_id bridge ──────────────────────────────────────────────────────
#
# The injection barrier from plan §3.2: *the model may only emit `region_id`s
# present in the schema; unknown targets are dropped, not guessed.* Everything
# upstream names a region and supplies values; only these functions turn a name
# into a paragraph index or a cell address, so no caller is ever in a position
# to invent one. They also refuse to build an operation for a region the
# detector marked non-editable, which makes `preflight_docx` the second line of
# defence rather than the only one.


def _find(schema: Any, region_id: str) -> Any:
    for region in schema.regions:
        if region.region_id == region_id:
            return region
    raise UnknownRegionError(region_id)


def _editable(region: Any) -> Any:
    if not region.editable:
        raise RegionNotEditableError(
            f"{region.region_id} is {region.kind} (editable=False, "
            f"protected={region.protected})"
        )
    return region


def _column_map(region: Any) -> dict[str, int]:
    """Header text -> cell index, taken from the schema."""
    return {
        column["name"]: column["index"]
        for column in region.notes.get("columns", [])
        if column.get("name")
    }


def _translate(
    rows: list[dict[str, Any]], mapping: dict[str, int], region_id: str, strict: bool
) -> list[dict[int, Any]]:
    translated: list[dict[int, Any]] = []
    for row in rows:
        converted: dict[int, Any] = {}
        for name, value in row.items():
            if isinstance(name, int):
                converted[name] = value
                continue
            index = mapping.get(name)
            if index is None:
                if strict:
                    raise UnknownRegionError(
                        f"{region_id} has no column {name!r}; known: {sorted(mapping)}"
                    )
                continue  # drop, never guess
            converted[index] = value
        translated.append(converted)
    return translated


def set_field(schema: Any, region_id: str, value: Any) -> SetTextOp:
    """Write a `field` / `field_empty` region's value, keeping its label.

    The schema records the label prefix verbatim (`'Prepared by: '`), so the
    wording and spacing the template author chose are reproduced rather than
    reconstructed -- only the value after the colon changes.
    """
    region = _editable(_find(schema, region_id))
    if region.locator.para_index is None:
        raise RegionNotEditableError(
            f"{region_id} is not a paragraph region; use replace_region_rows"
        )
    prefix = region.notes.get("label_prefix", "")
    value_type = region.value_type if region.value_type in ("string", "number", "date") else "string"
    return SetTextOp(
        para_index=region.locator.para_index,
        text=f"{prefix}{value}",
        value_type=value_type,
        part=region.locator.part,
    )


def set_text(schema: Any, region_id: str, text: str) -> SetTextOp:
    """Replace a paragraph region's whole text, label included."""
    region = _editable(_find(schema, region_id))
    if region.locator.para_index is None:
        raise RegionNotEditableError(f"{region_id} is not a single-paragraph region")
    return SetTextOp(
        para_index=region.locator.para_index, text=text, part=region.locator.part
    )


def clear_region(schema: Any, region_id: str) -> ClearRegionOp:
    region = _editable(_find(schema, region_id))
    locator = region.locator
    return ClearRegionOp(
        para_index=locator.para_index,
        para_span=tuple(locator.para_span) if locator.para_span else None,
        table_index=locator.table_index,
        row_span=tuple(locator.row_span) if locator.row_span else None,
        part=locator.part,
    )


def add_table_rows(
    schema: Any,
    region_id: str,
    rows: list[dict[str, Any]],
    *,
    value_types: dict[str, ValueType] | None = None,
    strict: bool = True,
) -> CloneTableRowsOp:
    """Append rows to a `table_loop` / `table_data` region."""
    region = _editable(_find(schema, region_id))
    return _clone_op(region, region_id, rows, value_types, strict)


def _clone_op(
    region: Any,
    region_id: str,
    rows: list[dict[str, Any]],
    value_types: dict[str, ValueType] | None,
    strict: bool,
) -> CloneTableRowsOp:
    if region.locator.table_index is None:
        raise RegionNotEditableError(f"{region_id} is not a table region")
    notes = region.notes
    mapping = _column_map(region)
    return CloneTableRowsOp(
        table_index=region.locator.table_index,
        at_row=notes.get("insert_at_row", 1),
        rows=_translate(rows, mapping, region_id, strict),
        row_template_row=notes.get("template_row", notes.get("first_data_row", 1)),
        value_types={
            mapping.get(name, name): kind
            for name, kind in (value_types or {}).items()
        },
        part=region.locator.part,
    )


def replace_region_rows(
    schema: Any,
    region_id: str,
    rows: list[dict[str, Any]] | list[str],
    *,
    value_types: dict[str, ValueType] | None = None,
    strict: bool = True,
) -> ReplaceTableRowsOp | ReplaceBlockItemsOp:
    """Rewrite a region's rows in full, growing or blanking it to fit.

    Polymorphic on the region's shape, because the Change Spec addresses a
    `region_id` and shouldn't have to know whether it resolves to table rows or
    to a run of paragraphs. A `repeating_block` takes a list of strings; a table
    takes a list of column-keyed dicts.
    """
    region = _editable(_find(schema, region_id))
    locator = region.locator

    if locator.table_index is not None:
        notes = region.notes
        first = notes.get("first_data_row", 1)
        last = locator.row_span[1] if locator.row_span else first - 1
        if last < first:
            raise RegionNotEditableError(
                f"{region_id} has no data rows to replace (it is {region.kind}); "
                "use add_table_rows to populate it"
            )
        return ReplaceTableRowsOp(
            table_index=locator.table_index,
            first_row=first,
            last_row=last,
            rows=_translate(rows, _column_map(region), region_id, strict),  # type: ignore[arg-type]
            row_template_row=notes.get("template_row", first),
            value_types={
                _column_map(region).get(name, name): kind
                for name, kind in (value_types or {}).items()
            },
            part=locator.part,
        )

    if locator.para_span is None:
        raise RegionNotEditableError(
            f"{region_id} is a single paragraph; use set_text or set_field"
        )
    items = [item if isinstance(item, str) else str(item) for item in rows]
    return ReplaceBlockItemsOp(
        para_span=tuple(locator.para_span), items=items, part=locator.part
    )


def append_history_row(
    schema: Any, region_id: str, values: dict[str, Any], *, strict: bool = True
) -> CloneTableRowsOp:
    """Append a row to the in-document revision block (plan §1.3, §4 Ring 2).

    The one write that deliberately bypasses `editable`. A `history` region is
    `editable=False` because the *generation agent* must not fill it in, but it
    is `protected=False` because publishing a new version is supposed to append
    to it -- that is what makes the version history travel with the file. So
    the region is looked up without the editability gate, and `preflight_docx`
    still refuses if a schema ever marks the block protected.
    """
    region = _find(schema, region_id)
    if region.kind != "history":
        raise RegionNotEditableError(
            f"{region_id} is {region.kind}, not the document's revision block"
        )
    if region.protected:
        raise RegionNotEditableError(f"{region_id} is protected")
    return _clone_op(region, region_id, [values], None, strict)
