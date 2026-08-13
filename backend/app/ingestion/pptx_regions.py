"""Deterministic region detector for pptx templates.

Same taxonomy as the xlsx detector (plan Appendix A) and the same fail-safe
default -- anything unrecognised is `immutable` -- but the signals are entirely
different. A deck has no merged cells or serial columns; it has placeholders
with declared types, bullet lists whose length is the variable part, tables
inside graphic frames, and pictures.

Structural signals used here:

  placeholder type title/ctrTitle          -> title
  placeholder type subtitle/body, 1 para   -> field
  placeholder type body, several paras     -> repeating_block  (a bullet list)
  placeholder with no text                 -> field_empty
  graphicFrame containing <a:tbl>          -> table_loop / table_data
  graphicFrame containing a chart          -> derived, never writable
  picture                                  -> branding, never writable
  speaker notes                            -> field
  anything else                            -> immutable

One divergence from the xlsx detector is deliberate: **`title` is editable
here.** In a spreadsheet form the title is the form's identity ("Form:Minutes
of Meeting") and rewriting it would be vandalism; on a slide the title is the
slide's content, and a readout deck exists to have new titles written into it.
Appendix A's "rarely" covers both readings, so the kind is the same and the
editability differs, rather than inventing a kind.

Detection runs through python-pptx rather than raw XML, which is the opposite
choice to the xlsx detector. That's a measurement, not a preference: python-pptx
round-trips both the corporate deck and the generated template without losing a
single part, while openpyxl drops nine from the MOM. Shape ids and placeholder
types are exactly what this needs and reading them by hand would buy nothing.
"""

import io
from dataclasses import dataclass, field
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

DETECTOR_VERSION = "structural-pptx/1.0.0"

MAX_LABEL_LEN = 60  # longer than this reads as content, not a label

# python-pptx placeholder-type names, via `placeholder_format.type`.
_TITLE_PLACEHOLDERS = {"TITLE", "CENTER_TITLE"}
_SUBTITLE_PLACEHOLDERS = {"SUBTITLE"}
_BODY_PLACEHOLDERS = {"BODY", "OBJECT", "CONTENT", "VERTICAL_BODY"}
# PowerPoint fills these in itself. They hold text, so they look like fields,
# but writing them is the application's job.
_SYSTEM_PLACEHOLDERS = {"SLIDE_NUMBER", "DATE", "FOOTER", "HEADER"}

# kind -> (editable, protected), as in the xlsx detector. `title` differs; see
# the module docstring.
_WRITABILITY: dict[str, tuple[bool, bool]] = {
    "title": (True, False),
    "field": (True, False),
    "field_empty": (True, False),
    "repeating_block": (True, False),
    "table_loop": (True, False),
    "table_data": (True, False),
    "branding": (False, True),
    "derived": (False, True),
    "immutable": (False, True),
}


@dataclass
class SlideLocator:
    """Where a region lives in a deck. Mirrors `{slide, shape_id}` from §8."""

    slide_index: int  # 1-based, presentation order
    slide_part: str  # "ppt/slides/slide1.xml"
    shape_id: int | None = None  # None for speaker notes
    shape_name: str | None = None
    notes: bool = False


@dataclass
class PptxRegion:
    region_id: str
    kind: str
    label: str | None
    locator: SlideLocator
    value_type: str  # string | mixed | none
    current_content: str | None
    editable: bool
    protected: bool
    required: bool
    detection_method: str
    ordinal: int
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SlideSchema:
    index: int
    part: str
    layout: str | None
    title: str | None
    regions: list[PptxRegion]


@dataclass
class PptxDocumentSchema:
    detector_version: str
    format: str
    slides: list[SlideSchema]

    @property
    def regions(self) -> list[PptxRegion]:
        return [region for slide in self.slides for region in slide.regions]

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for region in self.regions:
            counts[region.kind] = counts.get(region.kind, 0) + 1
        return dict(sorted(counts.items()))

    def writable(self) -> list[PptxRegion]:
        return [region for region in self.regions if region.editable]


def _slug(text: str, fallback: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in text.lower())
    slug = "_".join(part for part in cleaned.split("_") if part)
    return slug[:48] or fallback


def _placeholder_type(shape: Any) -> str | None:
    if not shape.is_placeholder:
        return None
    placeholder_type = shape.placeholder_format.type
    return getattr(placeholder_type, "name", str(placeholder_type))


def _paragraph_texts(shape: Any) -> list[str]:
    if not shape.has_text_frame:
        return []
    return [
        paragraph.text.strip()
        for paragraph in shape.text_frame.paragraphs
        if paragraph.text.strip()
    ]


def _part_name(part: Any) -> str:
    return str(part.partname).lstrip("/")


def _table_of(shape: Any) -> Any | None:
    return shape.table if getattr(shape, "has_table", False) else None


def _is_chart(shape: Any) -> bool:
    return bool(getattr(shape, "has_chart", False))


def _is_picture(shape: Any) -> bool:
    return shape.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.LINKED_PICTURE)


class _SlideDetector:
    def __init__(self, index: int, slide: Any, used_ids: set[str]) -> None:
        self.index = index
        self.slide = slide
        self.part = _part_name(slide.part)
        self.regions: list[PptxRegion] = []
        self._used_ids = used_ids

    def _emit(
        self,
        kind: str,
        locator: SlideLocator,
        *,
        label: str | None = None,
        value_type: str = "string",
        current_content: str | None = None,
        id_hint: str | None = None,
        notes: dict[str, Any] | None = None,
    ) -> PptxRegion:
        editable, protected = _WRITABILITY[kind]
        base = f"slide{self.index}.{_slug(id_hint or label or kind, kind)}"
        region_id = base
        suffix = 2
        while region_id in self._used_ids:
            region_id = f"{base}_{suffix}"
            suffix += 1
        self._used_ids.add(region_id)

        region = PptxRegion(
            region_id=region_id,
            kind=kind,
            label=label,
            locator=locator,
            value_type=value_type,
            current_content=current_content,
            editable=editable,
            protected=protected,
            required=False,  # the LLM pass owns requiredness
            detection_method="structural",
            ordinal=len(self.regions),
            notes=notes or {},
        )
        self.regions.append(region)
        return region

    def _locator(self, shape: Any) -> SlideLocator:
        return SlideLocator(
            slide_index=self.index,
            slide_part=self.part,
            shape_id=shape.shape_id,
            shape_name=shape.name,
        )

    def detect(self) -> SlideSchema:
        title_text = None
        for shape in self.slide.shapes:
            if _is_picture(shape):
                self._detect_picture(shape)
            elif _is_chart(shape):
                self._detect_chart(shape)
            elif _table_of(shape) is not None:
                self._detect_table(shape)
            elif shape.has_text_frame:
                emitted = self._detect_text_shape(shape)
                if emitted is not None and emitted.kind == "title":
                    title_text = emitted.current_content
            else:
                self._emit(
                    "immutable",
                    self._locator(shape),
                    value_type="none",
                    id_hint=f"shape_{shape.shape_id}",
                    notes={"shape_type": str(shape.shape_type)},
                )
        self._detect_notes()

        return SlideSchema(
            index=self.index,
            part=self.part,
            layout=getattr(self.slide.slide_layout, "name", None),
            title=title_text,
            regions=self.regions,
        )

    def _detect_picture(self, shape: Any) -> None:
        self._emit(
            "branding",
            self._locator(shape),
            value_type="none",
            id_hint=f"picture_{shape.shape_id}",
            notes={"shape_type": "picture"},
        )

    def _detect_chart(self, shape: Any) -> None:
        chart = shape.chart
        # A chart's numbers live in its own embedded workbook part; rewriting
        # the shape cannot change them, so the region is never writable.
        self._emit(
            "derived",
            self._locator(shape),
            value_type="none",
            label=shape.name,
            id_hint=f"chart_{shape.shape_id}",
            notes={
                "chart_type": str(chart.chart_type),
                "series": [series.name for series in chart.plots[0].series]
                if chart.plots
                else [],
                "categories": [str(category) for category in chart.plots[0].categories]
                if chart.plots
                else [],
                "derived_from": "embedded workbook part",
            },
        )

    def _detect_table(self, shape: Any) -> None:
        table = _table_of(shape)
        rows = list(table.rows)
        header_cells = [table.cell(0, column).text.strip() for column in range(len(table.columns))]
        data_rows = [
            index
            for index in range(1, len(rows))
            if any(
                table.cell(index, column).text.strip()
                for column in range(len(table.columns))
            )
        ]
        kind = "table_data" if data_rows else "table_loop"
        self._emit(
            kind,
            self._locator(shape),
            label=shape.name,
            value_type="mixed",
            id_hint=f"table_{_slug(header_cells[0] if header_cells else '', 'table')}"
            if kind == "table_loop"
            else f"table_{shape.shape_id}",
            notes={
                "columns": [
                    {"index": index, "name": name} for index, name in enumerate(header_cells)
                ],
                "header_row": 0,
                "first_data_row": 1,
                "row_count": len(data_rows),
                "total_rows": len(rows),
                # The empty row a template ships with is the row to clone; with
                # no data rows there is nothing else to copy formatting from.
                "row_template_row": data_rows[-1] if data_rows else len(rows) - 1,
                "insert_at_row": (data_rows[-1] + 1) if data_rows else len(rows) - 1,
            },
        )

    def _detect_text_shape(self, shape: Any) -> PptxRegion | None:
        placeholder = _placeholder_type(shape)
        paragraphs = _paragraph_texts(shape)
        locator = self._locator(shape)

        if placeholder in _SYSTEM_PLACEHOLDERS:
            return self._emit(
                "immutable",
                locator,
                label=shape.name,
                current_content=paragraphs[0] if paragraphs else None,
                value_type="string" if paragraphs else "none",
                id_hint=_slug(shape.name, "system"),
                notes={"placeholder": placeholder, "system_managed": True},
            )

        if placeholder in _TITLE_PLACEHOLDERS:
            kind = "title" if paragraphs else "field_empty"
            return self._emit(
                kind,
                locator,
                label="title",
                current_content=" ".join(paragraphs) or None,
                value_type="string" if paragraphs else "none",
                id_hint="title",
                notes={"placeholder": placeholder},
            )

        if not paragraphs:
            # An empty *placeholder* is a declared slot waiting for content. An
            # empty autoshape is decoration -- a background chip or a connector
            # label -- and the design decks are full of them. Offering those as
            # writable would put readout text inside a coloured rectangle.
            return self._emit(
                "field_empty" if placeholder else "immutable",
                locator,
                label=shape.name,
                value_type="none",
                id_hint=f"{_slug(shape.name, 'shape')}_empty",
                notes={"placeholder": placeholder},
            )

        if len(paragraphs) > 1:
            # A bullet list is the pptx repeating region: same shape, variable
            # number of entries, one paragraph's formatting to clone.
            return self._emit(
                "repeating_block",
                locator,
                label=shape.name,
                value_type="string",
                current_content=" | ".join(paragraphs)[:200],
                id_hint=_slug(shape.name, "bullets"),
                notes={
                    "placeholder": placeholder,
                    "paragraph_count": len(paragraphs),
                    "paragraphs": paragraphs,
                    "levels": [
                        paragraph.level for paragraph in shape.text_frame.paragraphs
                    ],
                },
            )

        if placeholder in _SUBTITLE_PLACEHOLDERS or placeholder in _BODY_PLACEHOLDERS:
            return self._emit(
                "field",
                locator,
                label=shape.name,
                value_type="string",
                current_content=paragraphs[0],
                id_hint=_slug(shape.name, "field"),
                notes={"placeholder": placeholder},
            )

        # A lone text box that reads like a label is a field; anything longer is
        # prose we have no basis to rewrite.
        kind = "field" if len(paragraphs[0]) <= MAX_LABEL_LEN else "immutable"
        return self._emit(
            kind,
            locator,
            label=shape.name,
            value_type="string",
            current_content=paragraphs[0],
            id_hint=_slug(shape.name, "textbox"),
            notes={"placeholder": placeholder},
        )

    def _detect_notes(self) -> None:
        if not self.slide.has_notes_slide:
            return
        notes_frame = self.slide.notes_slide.notes_text_frame
        text = notes_frame.text.strip() if notes_frame is not None else ""
        self._emit(
            "field" if text else "field_empty",
            SlideLocator(
                slide_index=self.index,
                slide_part=self.part,
                shape_id=None,
                shape_name="speaker notes",
                notes=True,
            ),
            label="speaker notes",
            value_type="string" if text else "none",
            current_content=text or None,
            id_hint="speaker_notes",
            notes={"notes_part": _part_name(self.slide.notes_slide.part)},
        )


def detect_regions_pptx(data: bytes) -> PptxDocumentSchema:
    """Classify every shape of every slide, structurally."""
    presentation = Presentation(io.BytesIO(data))
    used_ids: set[str] = set()
    slides = [
        _SlideDetector(index, slide, used_ids).detect()
        for index, slide in enumerate(presentation.slides, start=1)
    ]
    return PptxDocumentSchema(
        detector_version=DETECTOR_VERSION, format="pptx", slides=slides
    )


def slide_part_index(data: bytes) -> dict[str, int]:
    """Worksheet-part -> 1-based slide index, for resolving locators later."""
    presentation = Presentation(io.BytesIO(data))
    return {
        _part_name(slide.part): index
        for index, slide in enumerate(presentation.slides, start=1)
    }
