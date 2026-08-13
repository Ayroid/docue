"""Structural fingerprint for docx package integrity checks.

The xlsx fingerprint exists because openpyxl silently destroys parts. docx is
the opposite case: measured on `BRD Sample.docx`, a python-docx round-trip
loses nothing -- 34 parts in, 34 out, 6 drawings and 14 hyperlinks intact. So
the docx compiler is allowed to go through the library, and this module's job
is to keep proving that on every compile rather than trusting the measurement
to hold for the next document.

Two counts have to be read from the raw XML, and both are traps:

- **`<w:drawing>`, never `doc.inline_shapes`.** The BRD holds 5 PNGs in 6
  drawings, of which exactly *one* is a `<wp:inline>`; the other five are
  `<wp:anchor>` (floating). `inline_shapes` returns 1. A fingerprint built on
  it reports "1/1 images preserved" while four images have vanished -- a false
  pass, which is worse than no QA at all.
- **`<w:hyperlink>` and its relationships together.** The tag carries the
  display text, `word/_rels/document.xml.rels` carries the URL. Losing either
  one leaves a link that looks fine in a diff and is broken on the page.

Everything here is read from the zip with regexes over raw XML, the same way
`fingerprint.py` does it, so no library's object model gets a vote on whether
something survived.
"""

import io
import re
import zipfile
from dataclasses import dataclass

# `<w:pPr>` / `<w:tblGrid>` / `<w:trPr>` / `<w:sdtPr>` all share a prefix with
# a tag counted here, so every pattern pins the character that follows.
_PARAGRAPH_RE = re.compile(r"<w:p[ >/]")
_TABLE_RE = re.compile(r"<w:tbl[ >]")
_ROW_RE = re.compile(r"<w:tr[ >]")
_CELL_RE = re.compile(r"<w:tc[ >]")
_SECTION_RE = re.compile(r"<w:sectPr[ >]")
_DRAWING_RE = re.compile(r"<w:drawing[ >]")
_INLINE_RE = re.compile(r"<wp:inline[ >]")
_ANCHOR_RE = re.compile(r"<wp:anchor[ >]")
_PICT_RE = re.compile(r"<w:pict[ >]")
_BLIP_RE = re.compile(r"<a:blip[ >]")
_HYPERLINK_RE = re.compile(r"<w:hyperlink[ >]")
_CONTENT_CONTROL_RE = re.compile(r"<w:sdt[ >]")

# `r:id` / `r:embed` / `r:link` are how the body points at an image, a
# hyperlink target or a header. A reference with no matching entry in the
# part's `.rels` is the classic cause of Word's "unreadable content" repair
# dialog, so it is counted rather than assumed away.
_REL_REFERENCE_RE = re.compile(r'\br:(?:id|embed|link)="([^"]+)"')
_REL_TAG_RE = re.compile(r"<Relationship\b[^>]*?>")
_ID_ATTR_RE = re.compile(r'\bId="([^"]+)"')
_TYPE_ATTR_RE = re.compile(r'\bType="([^"]+)"')
_TARGET_ATTR_RE = re.compile(r'\bTarget="([^"]+)"')
_MODE_ATTR_RE = re.compile(r'\bTargetMode="([^"]+)"')

_HYPERLINK_REL_TYPE = "hyperlink"
_IMAGE_REL_TYPE = "image"


@dataclass
class DocxFingerprint:
    package_parts: list[str]
    # `paragraphs` counts every `<w:p>` in the body part, table cells included,
    # so cloning a 9-cell table row moves it by 9. `body_paragraphs` counts
    # only the ones the region detector addresses by `para_index`, which row
    # cloning leaves alone -- the tighter invariant of the two.
    paragraphs: int
    body_paragraphs: int
    tables: int
    table_rows: int
    table_cells: int
    sections: int
    drawings: int
    inline_drawings: int
    anchored_drawings: int
    legacy_pictures: int
    blips: int
    hyperlinks: int
    hyperlink_rels: int
    image_rels: int
    media_files: int
    content_controls: int
    headers: int
    footers: int
    custom_xml_parts: int
    sensitivity_label: bool
    # "part:rId" for every relationship the XML points at but the `.rels` does
    # not declare. Should always be empty; if a compile makes it non-empty,
    # Word will offer to repair the file.
    dangling_relationships: list[str]

    @property
    def images_referenced(self) -> int:
        """Distinct image parts the body actually points at."""
        return self.image_rels


def _word_xml_parts(parts: list[str]) -> list[str]:
    return [p for p in parts if p.startswith("word/") and p.endswith(".xml")]


def _count_everywhere(pattern: re.Pattern[str], xml_by_part: dict[str, str]) -> int:
    """Drawings and links live in headers and footnotes too, not just the body."""
    return sum(len(pattern.findall(xml)) for xml in xml_by_part.values())


def _body_paragraphs(document_xml: str) -> int:
    """Count `<w:p>` elements that are direct children of `<w:body>`.

    Done by depth-tracking rather than an XML parse to stay consistent with the
    rest of this module, and because the only thing being asked is "how deep is
    this tag", which needs no tree.
    """
    body_start = document_xml.find("<w:body")
    if body_start == -1:
        return 0
    body_start = document_xml.find(">", body_start)
    if body_start == -1:
        return 0

    depth = 0
    count = 0
    for match in re.finditer(r"<(/?)(w:[A-Za-z]+)([^>]*?)(/?)>", document_xml[body_start:]):
        closing, tag, _, self_closing = match.groups()
        if tag == "w:body" and closing:
            break
        if closing:
            depth -= 1
            continue
        if depth == 0 and tag == "w:p":
            count += 1
        if not self_closing:
            depth += 1
    return count


def _relationships(xml: str) -> list[tuple[str, str, str, str]]:
    """(id, type, target, mode) per relationship.

    Attribute order is not fixed -- Word writes `Id` before `Target`, other
    writers don't -- so each attribute is pulled out of the tag separately.
    """
    rels: list[tuple[str, str, str, str]] = []
    for tag in _REL_TAG_RE.findall(xml):
        rel_id = _ID_ATTR_RE.search(tag)
        rel_type = _TYPE_ATTR_RE.search(tag)
        target = _TARGET_ATTR_RE.search(tag)
        mode = _MODE_ATTR_RE.search(tag)
        if rel_id is None or rel_type is None or target is None:
            continue
        rels.append(
            (
                rel_id.group(1),
                rel_type.group(1).rsplit("/", 1)[-1],
                target.group(1),
                mode.group(1) if mode else "Internal",
            )
        )
    return rels


def parse_relationships(xml: str) -> list[tuple[str, str, str, str]]:
    """Public entry point for callers holding a `.rels` part's XML already.

    The docx compiler compares relationship *sets* before and after an edit --
    attribute order changes on re-serialisation, so the bytes can't be compared
    directly, but the tuples can.
    """
    return _relationships(xml)


def document_relationships(data: bytes) -> list[tuple[str, str, str, str]]:
    """The body part's relationships, for callers that need the URLs themselves."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "word/_rels/document.xml.rels" not in archive.namelist():
            return []
        return _relationships(
            archive.read("word/_rels/document.xml.rels").decode("utf-8")
        )


def _rels_part_for(part: str) -> str:
    prefix, _, name = part.rpartition("/")
    return f"{prefix}/_rels/{name}.rels"


def _dangling_relationships(
    archive: zipfile.ZipFile, xml_by_part: dict[str, str], parts: list[str]
) -> list[str]:
    dangling: list[str] = []
    for part, xml in sorted(xml_by_part.items()):
        referenced = set(_REL_REFERENCE_RE.findall(xml))
        if not referenced:
            continue
        rels_part = _rels_part_for(part)
        declared = (
            {rel_id for rel_id, _, _, _ in _relationships(archive.read(rels_part).decode("utf-8", "replace"))}
            if rels_part in parts
            else set()
        )
        dangling.extend(f"{part}:{rel_id}" for rel_id in sorted(referenced - declared))
    return dangling


def fingerprint_docx(data: bytes) -> DocxFingerprint:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = sorted(archive.namelist())
        xml_by_part = {
            part: archive.read(part).decode("utf-8", "replace")
            for part in _word_xml_parts(parts)
        }
        document_xml = xml_by_part.get("word/document.xml", "")
        rels = (
            _relationships(archive.read("word/_rels/document.xml.rels").decode("utf-8"))
            if "word/_rels/document.xml.rels" in parts
            else []
        )
        dangling = _dangling_relationships(archive, xml_by_part, parts)

    return DocxFingerprint(
        package_parts=parts,
        paragraphs=len(_PARAGRAPH_RE.findall(document_xml)),
        body_paragraphs=_body_paragraphs(document_xml),
        tables=len(_TABLE_RE.findall(document_xml)),
        table_rows=len(_ROW_RE.findall(document_xml)),
        table_cells=len(_CELL_RE.findall(document_xml)),
        sections=len(_SECTION_RE.findall(document_xml)),
        drawings=_count_everywhere(_DRAWING_RE, xml_by_part),
        inline_drawings=_count_everywhere(_INLINE_RE, xml_by_part),
        anchored_drawings=_count_everywhere(_ANCHOR_RE, xml_by_part),
        legacy_pictures=_count_everywhere(_PICT_RE, xml_by_part),
        blips=_count_everywhere(_BLIP_RE, xml_by_part),
        hyperlinks=_count_everywhere(_HYPERLINK_RE, xml_by_part),
        hyperlink_rels=sum(1 for _, kind, _, _ in rels if kind == _HYPERLINK_REL_TYPE),
        image_rels=sum(1 for _, kind, _, _ in rels if kind == _IMAGE_REL_TYPE),
        media_files=sum(1 for p in parts if p.startswith("word/media/")),
        content_controls=_count_everywhere(_CONTENT_CONTROL_RE, xml_by_part),
        headers=sum(
            1 for p in parts if re.fullmatch(r"word/header\d*\.xml", p) is not None
        ),
        footers=sum(
            1 for p in parts if re.fullmatch(r"word/footer\d*\.xml", p) is not None
        ),
        custom_xml_parts=sum(
            1 for p in parts if p.startswith("customXml/") and p.endswith(".xml")
        ),
        # Purview writes the same part into docx that it writes into xlsx. The
        # BRD has none; a docx exported from a labelled site will.
        sensitivity_label="docMetadata/LabelInfo.xml" in parts,
        dangling_relationships=dangling,
    )
