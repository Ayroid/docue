"""Deterministic region detector for docx templates.

The xlsx detector reads *shape* off a grid: a bold label with an empty merged
cell beside it, a styled header row with nothing under it. A Word document has
no grid, and this corpus takes away the other obvious signal as well -- the BRD
is an Azure DevOps export in which **all 291 paragraphs carry style `Normal`**.
There is not one `Heading 1`. So structure cannot be read off style names and
has to be inferred from what is actually in the file:

- **Font size against the document default.** `word/styles.xml` sets
  `docDefaults` to 22 half-points, so body text is 11pt. The BRD's headings are
  the paragraphs that override it -- 24pt for the document title, 18pt for
  `Document Revision`, 16pt for each work-item line. That ladder is the heading
  outline the export threw away.
- **Numbering.** 19 contiguous `w:numPr` groups mark every list in the file.
- **A colon-terminated label.** `Prepared by: YMSLI` is a field; `Description:`
  with nothing after the colon is a *caption* for the prose that follows it,
  which is a different thing and has to be classified differently.
- **Anchored drawings.** Five of the six `<w:drawing>` elements are floating,
  and each sits alone in a text-empty paragraph.

Same two safety rules as the xlsx detector:

1. **Anything unclassified becomes `immutable`.** A visible gap in the output
   beats silent corruption of somebody's document.
2. **A paragraph whose text is not wholly owned by its plain runs is never
   writable.** This is the docx-specific one, and it is not theoretical: in the
   BRD, 14 paragraphs hold their text inside `<w:hyperlink>` elements, which
   `Paragraph.runs` does not return. Three of them (`p.runs == 0`) have *no*
   runs at all. A run-level writer that rewrote run 0 and cleared the rest
   would leave the hyperlink's text sitting in the paragraph beside the new
   text -- and because the `<w:hyperlink>` element itself survives, the
   structural fingerprint would still count 14 and pass. Refusing the write is
   the only way that failure mode stays visible.

The taxonomy is plan Appendix A, unchanged; the locators are the docx shapes
from plan §8 (`{para_index, run_span}` for paragraphs, table/row/cell for
tables), so a detected region drops straight into `document_regions`.
"""

import io
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

DETECTOR_VERSION = "structural-docx/1.0.0"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# ── Scan bounds ────────────────────────────────────────────────────────────
# The BRD is 291 paragraphs; an Azure DevOps export of a whole epic tree can be
# far longer, and ingestion has a 30s budget (plan §14).
MAX_SCAN_PARAGRAPHS = 20_000
MAX_SCAN_TABLES = 500

# ── Detection thresholds ──────────────────────────────────────────────────
DEFAULT_BODY_SIZE_PT = 11.0  # only used when styles.xml declares no default
MAX_LABEL_LEN = 60  # longer than this is prose, not a label
MAX_FIELD_VALUE_LEN = 400  # longer than this is a paragraph that happens to have a colon
MAX_CAPTION_LEN = 120
# A caption's block ends after this many consecutive empty paragraphs. The
# export puts exactly one spacer between paragraphs of the same block.
BLOCK_BLANK_STREAK = 2
MIN_BLOCK_PARAGRAPHS = 1
MAX_HEADING_LEN = 200

# YMSLI's templates park a literal '*' in cells to mark print extents; the
# xlsx detector treats it as a sentinel and so does this one, for the same
# reason -- counted as content it turns an empty table into a populated one.
SENTINEL_VALUES = frozenset({"*"})

# The house revision block, plan §1.3. Column names vary between files -- the
# BRD writes `Review date` where the plan's prose says `Date of Review`, and it
# has no `Comments` column at all -- so this matches on a normalised token set
# with a threshold, never on an exact header list.
_HISTORY_TOKENS = frozenset(
    {
        "ver",
        "version",
        "date",
        "updatedby",
        "revisionsummary",
        "description",
        "reviewdate",
        "dateofreview",
        "reviewedby",
        "approvaldate",
        "dateofapproval",
        "approvedby",
        "comments",
    }
)
_HISTORY_REQUIRED = frozenset({"ver", "version"})
MIN_HISTORY_TOKENS = 4

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_DOC_DEFAULT_SIZE_RE = re.compile(
    r"<w:docDefaults>.*?<w:rPrDefault>.*?<w:sz\s+w:val=\"(\d+)\"", re.DOTALL
)
# `Prepared by: YMSLI` -> ('Prepared by: ', 'YMSLI'). The label group is
# non-greedy so the first colon wins, and it is captured *with* its trailing
# whitespace so a writer can reproduce the label byte-for-byte.
_LABEL_VALUE_RE = re.compile(r"^([^:\n]{1,60}:[ \t]*)(.*)$", re.DOTALL)
_DATE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_EXPORT_MARKER_RE = re.compile(r"Export to Word/PDF|Azure Extension", re.IGNORECASE)

# kind -> (editable, protected). Identical mapping to the xlsx detector's, and
# for the same reason: `protected` is what the compiler pre-flight refuses to
# write through, `editable` is what the generation agent may offer.
_WRITABILITY: dict[str, tuple[bool, bool]] = {
    "field": (True, False),
    "field_empty": (True, False),
    "table_loop": (True, False),
    "table_data": (True, False),
    "repeating_block": (True, False),
    "title": (False, False),
    "history": (False, False),  # system-written on publish, not user-written
    "branding": (False, True),
    "derived": (False, True),
    "instruction": (False, True),
    "immutable": (False, True),
}


@dataclass
class Locator:
    """Where a docx region lives. Mirrors `document_regions.locator` JSONB.

    `para_index` indexes `Document.paragraphs`, which holds *body* paragraphs
    only -- table-cell paragraphs are not in it. That is deliberate: cloning a
    nine-cell table row adds nine `<w:p>` elements to the package but leaves
    every `para_index` in this schema still pointing at the same paragraph.
    """

    part: str = "word/document.xml"
    para_index: int | None = None
    run_span: list[int] | None = None  # [start, end) into Paragraph.runs
    para_span: list[int] | None = None  # [first, last] inclusive, for blocks
    table_index: int | None = None
    row_index: int | None = None
    row_span: list[int] | None = None  # [first, last] inclusive data rows
    cell_index: int | None = None
    ref: str = ""  # human-readable, for logs and the admin UI

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}


@dataclass
class Region:
    region_id: str
    kind: str
    label: str | None
    locator: Locator
    value_type: str  # string | number | date | mixed | none
    current_content: str | None
    editable: bool
    protected: bool
    required: bool
    detection_method: str
    ordinal: int
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentSchema:
    """The docx analogue of the xlsx `DocumentSchema`.

    A workbook groups regions by sheet, so the xlsx schema carries a list of
    `SheetSchema`. A Word document has one body, so regions hang directly off
    the schema and `regions` / `counts_by_kind` / `writable` behave exactly as
    they do on the xlsx side -- which is what the compiler and the question
    planner actually consume.
    """

    detector_version: str
    format: str
    regions: list[Region]
    notes: dict[str, Any] = field(default_factory=dict)

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for region in self.regions:
            counts[region.kind] = counts.get(region.kind, 0) + 1
        return dict(sorted(counts.items()))

    def writable(self) -> list[Region]:
        return [region for region in self.regions if region.editable]

    def by_id(self, region_id: str) -> Region | None:
        for region in self.regions:
            if region.region_id == region_id:
                return region
        return None


# ── Package-level facts, read from the zip ────────────────────────────────


def _default_size_pt(data: bytes) -> float:
    """Body text size, from `docDefaults` -- the baseline headings rise above.

    Read from raw XML rather than through `styles.element`: it is one number,
    and the whole heading ladder is measured against it.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "word/styles.xml" not in archive.namelist():
            return DEFAULT_BODY_SIZE_PT
        styles_xml = archive.read("word/styles.xml").decode("utf-8", "replace")
    match = _DOC_DEFAULT_SIZE_RE.search(styles_xml)
    if match is None:
        return DEFAULT_BODY_SIZE_PT
    return int(match.group(1)) / 2.0  # half-points


def _export_tool(document: DocxDocument) -> str | None:
    """The Azure DevOps export leaves its signature in the footer."""
    for section in document.sections:
        for container in (section.footer, section.header):
            for paragraph in container.paragraphs:
                if _EXPORT_MARKER_RE.search(paragraph.text):
                    return paragraph.text.strip()
    return None


# ── Small helpers ─────────────────────────────────────────────────────────


def _slug(text: str, fallback: str) -> str:
    slug = _NON_ALNUM_RE.sub("_", text.lower()).strip("_")
    return slug[:48] or fallback


def _normalise_token(text: str) -> str:
    return _NON_ALNUM_RE.sub("", text.lower())


def _is_sentinel(text: str) -> bool:
    return text.strip() in SENTINEL_VALUES


def _cell_text(text: str) -> str:
    stripped = text.strip()
    return "" if _is_sentinel(stripped) else stripped


def _value_type(text: str | None) -> str:
    if not text:
        return "none"
    stripped = text.strip()
    if _DATE_RE.match(stripped):
        return "date"
    if _NUMBER_RE.match(stripped):
        return "number"
    return "string"


def _run_text(paragraph: Paragraph) -> str:
    return "".join(run.text for run in paragraph.runs)


def _run_text_complete(paragraph: Paragraph) -> bool:
    """Do the plain runs own every character of this paragraph's text?

    False means the text lives partly or wholly inside a `<w:hyperlink>`, a
    field or a content control, and no run-level write can touch it safely.
    """
    return _run_text(paragraph) == paragraph.text


def _drawing_kinds(paragraph: Paragraph) -> list[str]:
    """`inline` / `anchor` per `<w:drawing>` in this paragraph, in document order."""
    kinds: list[str] = []
    for drawing in paragraph._p.iter(f"{W}drawing"):
        child_tags = {child.tag.rpartition("}")[2] for child in drawing}
        if "inline" in child_tags:
            kinds.append("inline")
        elif "anchor" in child_tags:
            kinds.append("anchor")
        else:  # pragma: no cover - a drawing with neither wrapper
            kinds.append("drawing")
    return kinds


def _effective_size_pt(paragraph: Paragraph, default_pt: float) -> float:
    """Largest explicit run size, else the document default.

    `max` rather than the first run's size: the BRD's work-item heading lines
    mix a 16pt title with 10pt metadata in one paragraph, and 16 is what makes
    them a heading.
    """
    sizes = [
        run.font.size.pt
        for run in paragraph.runs
        if run.font.size is not None and run.text.strip()
    ]
    return max(sizes) if sizes else default_pt


def _all_bold(paragraph: Paragraph) -> bool:
    marks = [bool(run.bold) for run in paragraph.runs if run.text.strip()]
    return bool(marks) and all(marks)


def _numbering(paragraph: Paragraph) -> tuple[int, int] | None:
    """(numId, ilvl) if this paragraph is part of a numbered or bulleted list."""
    properties = paragraph._p.pPr
    if properties is None or properties.numPr is None:
        return None
    num_pr = properties.numPr
    if num_pr.numId is None:
        return None
    level = num_pr.ilvl.val if num_pr.ilvl is not None else 0
    return int(num_pr.numId.val), int(level or 0)


def _split_label(text: str) -> tuple[str, str] | None:
    """`('Prepared by: ', 'YMSLI')`, label prefix kept verbatim for rewriting."""
    match = _LABEL_VALUE_RE.match(text)
    if match is None:
        return None
    prefix, value = match.group(1), match.group(2)
    if len(prefix.rstrip().rstrip(":")) > MAX_LABEL_LEN:
        return None
    return prefix, value


# ── Detection ─────────────────────────────────────────────────────────────


@dataclass
class _Para:
    index: int
    paragraph: Paragraph
    text: str
    size_pt: float
    bold: bool
    numbering: tuple[int, int] | None
    drawings: list[str]
    run_text_complete: bool

    @property
    def empty(self) -> bool:
        return not self.text and not self.drawings


@dataclass
class _TablePosition:
    table_index: int
    table: Table
    after_para_index: int | None  # the body paragraph directly above the table


class _DocxDetector:
    def __init__(self, data: bytes) -> None:
        self.document = docx.Document(io.BytesIO(data))
        self.body_size_pt = _default_size_pt(data)
        self.regions: list[Region] = []
        self.claimed: set[int] = set()  # body paragraph indices
        self.sentinel_cells = 0
        self._used_ids: set[str] = set()
        self._heading_levels: dict[float, int] = {}

        self.paras: list[_Para] = []
        for index, paragraph in enumerate(self.document.paragraphs):
            if index >= MAX_SCAN_PARAGRAPHS:
                break
            self.paras.append(
                _Para(
                    index=index,
                    paragraph=paragraph,
                    text=paragraph.text.strip(),
                    size_pt=_effective_size_pt(paragraph, self.body_size_pt),
                    bold=_all_bold(paragraph),
                    numbering=_numbering(paragraph),
                    drawings=_drawing_kinds(paragraph),
                    run_text_complete=_run_text_complete(paragraph),
                )
            )
        self.tables = self._table_positions()

    # -- body order -------------------------------------------------------

    def _table_positions(self) -> list[_TablePosition]:
        """Walk the body once to learn which paragraph each table sits under.

        A table's caption is the paragraph above it -- `Document Revision` for
        the BRD's revision block, `Items (9) Summary:` for its work-item table
        -- and that is only knowable from body order, which neither
        `Document.tables` nor `Document.paragraphs` preserves on its own.
        """
        positions: list[_TablePosition] = []
        tables = self.document.tables
        seen_paragraphs = 0
        table_ordinal = 0
        for child in self.document.element.body.iterchildren():
            if child.tag == f"{W}p":
                seen_paragraphs += 1
            elif child.tag == f"{W}tbl":
                if table_ordinal < len(tables) and table_ordinal < MAX_SCAN_TABLES:
                    positions.append(
                        _TablePosition(
                            table_index=table_ordinal,
                            table=tables[table_ordinal],
                            after_para_index=(
                                seen_paragraphs - 1 if seen_paragraphs else None
                            ),
                        )
                    )
                table_ordinal += 1
        return positions

    # -- claiming ---------------------------------------------------------

    def _claim(self, *indices: int) -> None:
        self.claimed.update(indices)

    def _claim_range(self, first: int, last: int) -> None:
        self.claimed.update(range(first, last + 1))

    def _unclaimed(self, index: int) -> bool:
        return index not in self.claimed

    # -- emission ---------------------------------------------------------

    def _emit(
        self,
        kind: str,
        locator: Locator,
        *,
        label: str | None = None,
        value_type: str = "none",
        current_content: str | None = None,
        id_hint: str | None = None,
        notes: dict[str, Any] | None = None,
    ) -> Region:
        editable, protected = _WRITABILITY[kind]
        local_slug = _slug(id_hint or label or locator.ref, kind)
        base = f"doc.{local_slug}"
        region_id = base
        suffix = 2
        while region_id in self._used_ids:
            region_id = f"{base}_{suffix}"
            suffix += 1
        self._used_ids.add(region_id)

        region = Region(
            region_id=region_id,
            kind=kind,
            label=label,
            locator=locator,
            value_type=value_type,
            current_content=current_content,
            editable=editable,
            protected=protected,
            required=False,  # the LLM pass owns requiredness; structure can't tell
            detection_method="structural",
            ordinal=len(self.regions),
            notes=notes or {},
        )
        self.regions.append(region)
        return region

    # -- passes -----------------------------------------------------------

    def detect(self) -> DocumentSchema:
        # A priority ladder, same as the xlsx detector: the never-writable
        # shapes claim their paragraphs first, then tables, then the
        # label/value fields, then headings, then blocks, and whatever is left
        # defaults to immutable.
        self._build_heading_ladder()
        self._detect_drawings()
        self._detect_tables()
        self._detect_fields()
        self._detect_headings()
        self._detect_captioned_blocks()
        self._detect_numbering_groups()
        self._detect_immutable()

        # Detection runs in priority order; readers and the question planner
        # want document order.
        self.regions.sort(key=self._document_order)
        for ordinal, region in enumerate(self.regions):
            region.ordinal = ordinal

        return DocumentSchema(
            detector_version=DETECTOR_VERSION,
            format="docx",
            regions=self.regions,
            notes=self._document_notes(),
        )

    def _document_order(self, region: Region) -> tuple[int, int]:
        locator = region.locator
        if locator.para_index is not None:
            return (locator.para_index, 0)
        if locator.para_span:
            return (locator.para_span[0], 0)
        if locator.table_index is not None:
            position = next(
                (p for p in self.tables if p.table_index == locator.table_index), None
            )
            anchor = position.after_para_index if position else None
            # Sort a table just after the paragraph it sits under.
            return ((anchor if anchor is not None else 0), 1)
        return (0, 0)  # pragma: no cover - every locator carries one of the above

    def _document_notes(self) -> dict[str, Any]:
        notes: dict[str, Any] = {
            "body_size_pt": self.body_size_pt,
            "body_paragraphs": len(self.paras),
            "heading_ladder": {str(k): v for k, v in sorted(self._heading_levels.items(), reverse=True)},
            "styles_used": sorted(
                {paragraph.style.name for paragraph in self.document.paragraphs if paragraph.style}
            ),
            "tables": len(self.tables),
            "drawings": sum(len(p.drawings) for p in self.paras),
            "hyperlink_paragraphs": sum(1 for p in self.paras if not p.run_text_complete),
        }
        export = _export_tool(self.document)
        if export:
            notes["export_tool"] = export
        history = next((r for r in self.regions if r.kind == "history"), None)
        if history is not None:
            notes["house_pattern"] = "ymsli_revision_block"
            notes["history_region_id"] = history.region_id
            # Plan §8: `in_doc_version` is the `Ver.` the document itself
            # claims, and comparing it to the hub's version number is drift
            # detection with no diffing at all.
            if history.notes.get("in_doc_version"):
                notes["in_doc_version"] = history.notes["in_doc_version"]
        if self.sentinel_cells:
            notes["sentinel_cells"] = self.sentinel_cells
        return notes

    # -- headings ---------------------------------------------------------

    def _build_heading_ladder(self) -> None:
        """Distinct above-body font sizes, largest first -> heading levels 1..n."""
        sizes = sorted(
            {
                para.size_pt
                for para in self.paras
                if para.text and para.size_pt > self.body_size_pt
            },
            reverse=True,
        )
        self._heading_levels = {size: level for level, size in enumerate(sizes, start=1)}

    def _heading_level(self, para: _Para) -> int | None:
        if not para.text or len(para.text) > MAX_HEADING_LEN:
            return None
        return self._heading_levels.get(para.size_pt)

    def _detect_drawings(self) -> None:
        """Image paragraphs. Never written.

        An image is `branding`; anything else anchored in a paragraph takes the
        fail-safe `immutable`, because calling a text box branding would be a
        lie. The BRD's six drawings are one inline logo and five floating
        process-flow screenshots, and `doc.inline_shapes` can see exactly one
        of them.
        """
        for para in self.paras:
            if not para.drawings or not self._unclaimed(para.index):
                continue
            self._claim(para.index)
            kinds = para.drawings
            self._emit(
                "branding",
                Locator(
                    para_index=para.index,
                    run_span=[0, len(para.paragraph.runs)],
                    ref=f"para {para.index}",
                ),
                label=para.text or None,
                current_content=para.text or None,
                id_hint=f"drawing_para{para.index}",
                notes={
                    "drawings": len(kinds),
                    "anchor": kinds[0] if len(set(kinds)) == 1 else "mixed",
                    "drawing_kinds": kinds,
                    "run_text_complete": para.run_text_complete,
                },
            )

    # -- tables -----------------------------------------------------------

    def _detect_tables(self) -> None:
        for position in self.tables:
            table = position.table
            rows = table.rows
            if not rows:
                continue

            header_cells = [_cell_text(cell.text) for cell in rows[0].cells]
            self.sentinel_cells += sum(
                1 for cell in rows[0].cells if _is_sentinel(cell.text)
            )
            columns = [
                {"index": index, "name": name}
                for index, name in enumerate(header_cells)
                if name
            ]

            data_rows = rows[1:]
            populated = 0
            for row in data_rows:
                texts = [_cell_text(cell.text) for cell in row.cells]
                self.sentinel_cells += sum(1 for cell in row.cells if _is_sentinel(cell.text))
                if any(texts):
                    populated += 1
                else:
                    break  # a blank row ends the data; trailing blanks are spare

            is_history = self._is_history_header(header_cells)
            if is_history:
                kind = "history"
            elif populated:
                kind = "table_data"
            else:
                kind = "table_loop"

            cells_per_row = [len(row.cells) for row in rows]
            notes: dict[str, Any] = {
                "header_row": 0,
                "columns": columns,
                "column_count": len(header_cells),
                "row_count": populated,
                "data_row_count": len(data_rows),
                "first_data_row": 1,
                "insert_at_row": 1 + populated,
                "blank_trailing_rows": len(data_rows) - populated,
                "cells_per_row": cells_per_row,
                # Cloning a row copies its cells, so a ragged row makes ragged
                # clones. The BRD's revision block row 1 has five `<w:tc>` for
                # nine grid columns -- cloning *it* would produce a five-cell
                # row and drop the approval columns off the end. Prefer a data
                # row that carries the full set.
                "template_row": self._template_row(cells_per_row),
                "style": table.style.name if table.style is not None else None,
            }
            if kind == "history":
                notes["system_written"] = True
                version = self._latest_version(table, header_cells)
                if version:
                    notes["in_doc_version"] = version

            caption = self._caption_above(position.after_para_index)
            label = None
            if caption is not None:
                self._claim(caption.index)
                # Trailing colon dropped so `Items (9) Summary:` and
                # `Document Revision` produce labels of the same shape, and so
                # a table's label matches a block's and a field's.
                label = caption.text.rstrip().rstrip(":").strip()
                # The caption is part of this region -- it is the region's name,
                # not a write target -- so it is recorded rather than left
                # looking like an unclassified paragraph.
                notes["caption_para"] = caption.index
            if not label:
                label = f"table {position.table_index}"

            row_span = [1, len(rows) - 1] if len(rows) > 1 else None
            self._emit(
                kind,
                Locator(
                    table_index=position.table_index,
                    row_span=row_span,
                    ref=(
                        f"table {position.table_index}"
                        + (f" rows {row_span[0]}-{row_span[1]}" if row_span else "")
                    ),
                ),
                label=label,
                value_type="mixed",
                id_hint=label,
                notes=notes,
            )

    @staticmethod
    def _template_row(cells_per_row: list[int]) -> int:
        """The data row worth cloning: the widest one, else the header."""
        if len(cells_per_row) <= 1:
            return 0
        widest = max(cells_per_row[1:])
        for index in range(1, len(cells_per_row)):
            if cells_per_row[index] == widest:
                return index
        return 0  # pragma: no cover - unreachable, widest came from this slice

    @staticmethod
    def _is_history_header(header_cells: list[str]) -> bool:
        """The house revision block, matched on a normalised token set (§1.3)."""
        tokens = {_normalise_token(name) for name in header_cells if name}
        matched = tokens & _HISTORY_TOKENS
        return bool(tokens & _HISTORY_REQUIRED) and len(matched) >= MIN_HISTORY_TOKENS

    @staticmethod
    def _latest_version(table: Table, header_cells: list[str]) -> str | None:
        """The last non-empty `Ver.` in the revision block."""
        column = next(
            (
                index
                for index, name in enumerate(header_cells)
                if _normalise_token(name) in _HISTORY_REQUIRED
            ),
            None,
        )
        if column is None:
            return None
        latest = None
        for row in table.rows[1:]:
            cells = row.cells
            if column >= len(cells):
                continue
            value = _cell_text(cells[column].text)
            if value:
                latest = value
        return latest

    def _caption_above(self, para_index: int | None) -> _Para | None:
        """The nearest non-empty unclaimed paragraph above a block.

        A paragraph that already carries its own value (`Prepared by: YMSLI`)
        is a field, not a caption, and must not be consumed as one -- tables are
        detected before fields, so without this check a table placed under a
        field would claim it and the field would disappear from the schema.
        `Document Revision` and `Items (9) Summary:` both pass: neither has a
        value after the colon.
        """
        if para_index is None:
            return None
        for index in range(min(para_index, len(self.paras) - 1), -1, -1):
            para = self.paras[index]
            if para.empty:
                continue
            if not self._unclaimed(index):
                return None
            if len(para.text) > MAX_CAPTION_LEN:
                return None
            split = _split_label(para.text)
            if split is not None and split[1].strip():
                return None
            return para
        return None

    # -- fields -----------------------------------------------------------

    def _detect_fields(self) -> None:
        """`Label: value` paragraphs.

        Three things disqualify a candidate, and each one is a real case in the
        BRD rather than a hypothetical:

        * **The top heading tier.** `SE52: Business Requirement Document` is
          colon-shaped and is the document's 24pt title, not a field.
        * **Run text that doesn't match paragraph text.** The work-item lines
          (`... ID: 36897 | Type: Epic ...`) keep their ID inside a hyperlink.
        * **An empty value.** `Description:` is a caption for the prose below
          it; it becomes that block's label, not a field of its own. Only a
          caption with no block after it is a `field_empty`.
        """
        for para in self.paras:
            if para.empty or not self._unclaimed(para.index):
                continue
            split = _split_label(para.text)
            if split is None:
                continue
            prefix, value = split
            value = value.strip()
            if not value:
                continue  # a caption; _detect_captioned_blocks decides its fate
            if len(value) > MAX_FIELD_VALUE_LEN:
                continue
            level = self._heading_level(para)
            if level == 1:
                continue  # the document title
            if not para.run_text_complete:
                continue  # text lives in a hyperlink; no run-level write is safe

            self._claim(para.index)
            self._emit(
                "field",
                Locator(
                    para_index=para.index,
                    run_span=[0, len(para.paragraph.runs)],
                    ref=f"para {para.index}",
                ),
                label=prefix.rstrip().rstrip(":").strip(),
                value_type=_value_type(value),
                current_content=value,
                id_hint=prefix.rstrip().rstrip(":"),
                notes={
                    # The label is reproduced verbatim on write, so setting the
                    # value never disturbs the wording around it.
                    "label_prefix": prefix,
                    "run_count": len(para.paragraph.runs),
                    "run_text_complete": True,
                    "size_pt": para.size_pt,
                },
            )

    def _detect_headings(self) -> None:
        for para in self.paras:
            if para.empty or not self._unclaimed(para.index):
                continue
            level = self._heading_level(para)
            if level is None:
                continue
            self._claim(para.index)
            self._emit(
                "title",
                Locator(
                    para_index=para.index,
                    run_span=[0, len(para.paragraph.runs)],
                    ref=f"para {para.index}",
                ),
                label=para.text,
                value_type="string",
                current_content=para.text,
                id_hint=f"heading_{_slug(para.text, f'para{para.index}')}",
                notes={
                    "heading_level": level,
                    "size_pt": para.size_pt,
                    "run_text_complete": para.run_text_complete,
                },
            )

    # -- blocks -----------------------------------------------------------

    def _detect_captioned_blocks(self) -> None:
        """A colon-terminated caption plus the body paragraphs beneath it.

        This is the docx analogue of the MOM's numbered summary rows: the
        writable unit is the block, and the caption names it. `Description:`
        followed by four prose paragraphs is one `repeating_block` of four
        items, which is what T2 ("rewrite this section") needs to address.
        """
        for para in self.paras:
            if para.empty or not self._unclaimed(para.index):
                continue
            split = _split_label(para.text)
            if split is None or split[1].strip():
                continue  # not a caption, or it has a value and is a field
            if self._heading_level(para) is not None:
                continue  # a heading, already claimed by _detect_headings
            members = self._block_after(para.index)
            if len(members) < MIN_BLOCK_PARAGRAPHS:
                # A caption with nothing under it is a label waiting for a
                # value -- the docx form of the MOM's `Attendees(YMSLI)`.
                self._claim(para.index)
                self._emit(
                    "field_empty",
                    Locator(
                        para_index=para.index,
                        run_span=[0, len(para.paragraph.runs)],
                        ref=f"para {para.index}",
                    ),
                    label=para.text.rstrip().rstrip(":").strip(),
                    value_type="none",
                    current_content=None,
                    id_hint=para.text.rstrip().rstrip(":"),
                    notes={
                        "label_prefix": split[0],
                        "run_count": len(para.paragraph.runs),
                        "run_text_complete": para.run_text_complete,
                    },
                )
                continue
            self._emit_block(
                caption=para,
                members=members,
                id_hint=para.text.rstrip().rstrip(":"),
            )

    def _detect_numbering_groups(self) -> None:
        """Lists with no colon caption above them -- still repeating blocks."""
        index = 0
        while index < len(self.paras):
            para = self.paras[index]
            if para.numbering is None or not self._unclaimed(index) or para.empty:
                index += 1
                continue
            members = [para]
            cursor = index + 1
            while cursor < len(self.paras):
                candidate = self.paras[cursor]
                if candidate.empty:
                    break
                if candidate.numbering is None or not self._unclaimed(cursor):
                    break
                if not candidate.run_text_complete:
                    break  # same boundary rule as _block_after
                members.append(candidate)
                cursor += 1
            caption = self._caption_above(index - 1) if index else None
            self._emit_block(caption=caption, members=members, id_hint=None)
            index = cursor

    def _block_after(self, caption_index: int) -> list[_Para]:
        """The contiguous run of body paragraphs a caption introduces."""
        members: list[_Para] = []
        blank_streak = 0
        for index in range(caption_index + 1, len(self.paras)):
            para = self.paras[index]
            if not self._unclaimed(index):
                break
            if para.empty:
                blank_streak += 1
                if blank_streak >= BLOCK_BLANK_STREAK:
                    break
                continue
            if para.drawings or self._heading_level(para) is not None:
                break
            if not para.run_text_complete:
                # End the block *before* this paragraph rather than absorbing
                # it. The BRD ends four of its list blocks with a link to an
                # attachment (`55.10.001 Capex Approval.vsdx`); swallowing that
                # paragraph would make the whole block unwritable over one line
                # nobody wanted to edit anyway. It falls through to `immutable`
                # on its own instead.
                break
            split = _split_label(para.text)
            if split is not None and not split[1].strip():
                break  # the next caption
            blank_streak = 0
            members.append(para)
        return members

    def _emit_block(
        self, *, caption: _Para | None, members: list[_Para], id_hint: str | None
    ) -> None:
        if not members:
            return
        first, last = members[0].index, members[-1].index
        if caption is not None:
            self._claim(caption.index)
        self._claim_range(first, last)

        numbered = [para for para in members if para.numbering is not None]
        # A block is only writable if every paragraph in it can be rewritten at
        # run level. One hyperlink anywhere inside makes the whole block unsafe,
        # so it takes the fail-safe kind instead.
        writable = all(para.run_text_complete for para in members)
        kind = "repeating_block" if writable else "immutable"

        label = None
        if caption is not None:
            label = caption.text.rstrip().rstrip(":").strip()

        self._emit(
            kind,
            Locator(
                para_span=[first, last],
                ref=f"para {first}-{last}" if first != last else f"para {first}",
            ),
            label=label,
            value_type="string",
            current_content=" | ".join(para.text for para in members)[:500],
            id_hint=id_hint or label or f"block_para{first}",
            notes={
                "paragraphs": [para.index for para in members],
                "item_count": len(members),
                "numbered": bool(numbered),
                "num_ids": sorted({para.numbering[0] for para in numbered}),
                "levels": sorted({para.numbering[1] for para in numbered}),
                "insert_at_para": last + 1,
                "caption_para": caption.index if caption is not None else None,
                "run_text_complete": writable,
                **(
                    {}
                    if writable
                    else {"reason": "a paragraph's text is inside a hyperlink or field"}
                ),
            },
        )

    def _detect_immutable(self) -> None:
        """Fail-safe default: every remaining paragraph with content is off limits."""
        for para in self.paras:
            if para.empty or not self._unclaimed(para.index):
                continue
            self._claim(para.index)
            self._emit(
                "immutable",
                Locator(
                    para_index=para.index,
                    run_span=[0, len(para.paragraph.runs)],
                    ref=f"para {para.index}",
                ),
                label=para.text if len(para.text) <= MAX_LABEL_LEN else None,
                value_type=_value_type(para.text),
                current_content=para.text[:500],
                id_hint=f"immutable_para{para.index}",
                notes={
                    "run_text_complete": para.run_text_complete,
                    **(
                        {}
                        if para.run_text_complete
                        else {"reason": "text is inside a hyperlink or field"}
                    ),
                },
            )


def detect_regions_docx(data: bytes) -> DocumentSchema:
    """Classify every region of a Word document, structurally. No LLM."""
    return _DocxDetector(data).detect()
