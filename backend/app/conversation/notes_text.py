"""Turn an uploaded file into the plain text the notes reader works on.

People do not keep their prior context in a textarea. It is in the minutes
somebody mailed round, a page of a BRD, a spreadsheet of action items, last
week's deck. This module is the one place that turns any of those into a string,
so `POST /sessions/{id}/notes` can accept the file rather than asking the user to
open it, select all, and paste.

**This is not the ingestion pipeline and must not be confused with it.**
`app/ingestion/` detects *regions* in a document that is about to become a
template -- structure, locators, writability. What happens here is the opposite
and much dumber: flatten everything readable into prose and throw the structure
away. The output is evidence for a model to read, never a schema, and nothing
downstream resolves a locator against it.

Every reader is defensive in the same direction. A file that cannot be parsed
yields `""` and the caller reports that it could not be read; it never raises
into the request. A partially-readable file yields the part that read -- half a
page of notes is worth more than an error, and the user can see what landed.
"""

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["SUPPORTED_NOTE_TYPES", "extract_note_text"]

# What the upload control offers, and what the endpoint accepts. Keyed by
# extension because that is what a browser reliably sends; the content type from
# a Windows client is `application/octet-stream` often enough to be useless.
SUPPORTED_NOTE_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# Past this the reader's own token budget is the binding constraint, not ours,
# and a 400-page PDF is not notes. Truncated rather than refused: the first
# 60,000 characters of a long document are still worth reading, and refusing
# outright would send the user away to do the truncation by hand.
MAX_CHARS = 60_000


def _from_text(data: bytes) -> str:
    # utf-8 first, then cp1252, which is what Outlook and Notepad produce on the
    # machines this runs for. `errors="replace"` last so a stray byte costs one
    # character rather than the whole file.
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - one bad page is not a bad file
            logger.warning("notes: page %d of the PDF could not be read: %s", number, exc)
    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        # A scanned PDF is images. Saying so is better than returning "" and
        # letting the caller report "nothing could be matched to a field",
        # which would send the user looking for the wrong problem.
        logger.info("notes: the PDF yielded no text; it is probably a scan")
    return text


def _from_docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # Tables carry the action items in every BRD in this corpus, and
    # `Document.paragraphs` does not include cell text.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _from_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    # `data_only=True` reads the cached result of a formula rather than the
    # formula itself: "=SUM(B2:B9)" is not evidence about anything.
    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    parts: list[str] = []
    try:
        for sheet in workbook.worksheets:
            parts.append(f"# {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        workbook.close()
    return "\n".join(parts)


def _from_pptx(data: bytes) -> str:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):
        parts.append(f"# Slide {number}")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
        # Speaker notes are where the decisions usually are.
        notes = getattr(slide, "notes_slide", None) if slide.has_notes_slide else None
        if notes is not None and notes.notes_text_frame.text.strip():
            parts.append(f"(notes) {notes.notes_text_frame.text}")
    return "\n".join(parts)


_READERS: dict[str, Any] = {
    ".txt": _from_text,
    ".md": _from_text,
    ".pdf": _from_pdf,
    ".docx": _from_docx,
    ".xlsx": _from_xlsx,
    ".pptx": _from_pptx,
}


def extract_note_text(filename: str, data: bytes) -> tuple[str, str | None]:
    """`(text, reason it is empty)`. Never raises.

    The second element is `None` on success and a sentence a user can act on
    otherwise -- "that file type is not supported", "the PDF has no text layer".
    A caller that only reports "nothing matched a field" would send someone
    hunting for a problem in their notes when the problem was the file.
    """
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    reader = _READERS.get(suffix)
    if reader is None:
        return "", (
            f"{suffix or 'That file'} is not a format I can read. Supported: "
            + ", ".join(sorted(SUPPORTED_NOTE_TYPES))
        )

    try:
        text = reader(data)
    except Exception as exc:  # noqa: BLE001 - a broken upload is not a 500
        logger.warning("notes: %s could not be read: %s", filename, exc)
        return "", f"That {suffix} file could not be read: {type(exc).__name__}."

    text = (text or "").strip()
    if not text:
        return "", (
            "No text could be read out of that file. A scanned PDF is images rather "
            "than text, so there is nothing to extract."
            if suffix == ".pdf"
            else "That file appears to contain no text."
        )

    if len(text) > MAX_CHARS:
        logger.info("notes: %s truncated from %d to %d characters", filename, len(text), MAX_CHARS)
        text = text[:MAX_CHARS]
    return text, None
