"""One detection vocabulary over the three format detectors.

Three people built three detectors in parallel and each picked its own module
name and container: xlsx groups regions into `SheetSchema`, pptx into
`SlideSchema`, docx keeps them flat. That is fine inside each detector and
unworkable for a caller — the ingestion pipeline should not have to know that
`xlsx` means `regions.detect_regions_xlsx` returning `.sheets` while `pptx`
means `pptx_regions.detect_regions_pptx` returning `.slides`.

What the three already agree on is the part that matters, contract C3: every
`Region` carries `region_id`, `kind`, `label`, `locator`, `value_type`,
`current_content`, `editable`, `protected`, `required`, `detection_method`,
`ordinal`, `notes`, and every schema exposes `.regions`, `.counts_by_kind()`
and `.writable()`. This module leans on exactly that and adds nothing to it, so
it stays correct without any of the three detectors changing.

The one thing it has to normalise is the **locator**, because that is where the
formats genuinely differ (`{sheet, ref}` vs `{para_index, run_span}` vs
`{slide, shape_id}`) and it is a JSONB column rather than three columns. Plan §8
always intended one polymorphic `locator`, so serialising each dataclass as-is
and dropping the nulls is the whole job.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Protocol, runtime_checkable

from app.ingestion.fingerprint import fingerprint_pptx, fingerprint_xlsx
from app.ingestion.fingerprint_docx import fingerprint_docx
from app.ingestion.pptx_regions import detect_regions_pptx
from app.ingestion.regions import detect_regions_xlsx
from app.ingestion.regions_docx import detect_regions_docx

FORMATS = ("xlsx", "docx", "pptx")

__all__ = [
    "FORMATS",
    "UnsupportedFormatError",
    "detect",
    "fingerprint",
    "fingerprint_dict",
    "locator_dict",
    "region_containers",
]


class UnsupportedFormatError(ValueError):
    """A format with no detector. Never guessed at -- the caller gets an error."""


@runtime_checkable
class DetectedSchema(Protocol):
    """The C3 surface the three detectors already share."""

    detector_version: str
    format: str

    @property
    def regions(self) -> list[Any]: ...

    def counts_by_kind(self) -> dict[str, int]: ...

    def writable(self) -> list[Any]: ...


_DETECTORS = {
    "xlsx": detect_regions_xlsx,
    "docx": detect_regions_docx,
    "pptx": detect_regions_pptx,
}

_FINGERPRINTERS = {
    "xlsx": fingerprint_xlsx,
    "docx": fingerprint_docx,
    "pptx": fingerprint_pptx,
}


def _check(fmt: str) -> str:
    normalised = (fmt or "").strip().lower().lstrip(".")
    if normalised not in _DETECTORS:
        raise UnsupportedFormatError(
            f"no detector for format {fmt!r}; known formats are {sorted(_DETECTORS)}"
        )
    return normalised


def detect(data: bytes, fmt: str) -> DetectedSchema:
    """Classify every region of a document, structurally. No LLM.

    Returns whichever schema type the format's detector returns -- they are not
    unified into one class on purpose. Doing that would mean either flattening
    away `SheetSchema`/`SlideSchema` (which the xlsx and pptx test scripts read)
    or editing all three detectors, and neither buys anything: `.regions` is
    what every consumer downstream of here actually iterates.
    """
    return _DETECTORS[_check(fmt)](data)


def fingerprint(data: bytes, fmt: str) -> Any:
    """Package fingerprint for the format. `Fingerprint` | `DocxFingerprint` | `PptxFingerprint`."""
    return _FINGERPRINTERS[_check(fmt)](data)


def region_containers(schema: Any) -> list[tuple[str | None, list[Any]]]:
    """`[(container name, regions)]` — sheets, slides, or one unnamed body.

    Lets a caller report "3 regions on `Cover`" without knowing the format. The
    container is `None` for docx, which has one body and no grouping.
    """
    if hasattr(schema, "sheets"):
        return [(sheet.name, sheet.regions) for sheet in schema.sheets]
    if hasattr(schema, "slides"):
        return [
            (f"slide {slide.index}" + (f" — {slide.title}" if slide.title else ""), slide.regions)
            for slide in schema.slides
        ]
    return [(None, list(schema.regions))]


def locator_dict(locator: Any) -> dict[str, Any]:
    """A region's locator as JSONB, nulls dropped.

    The three locator dataclasses have disjoint fields, which is exactly what
    plan §8's single polymorphic `locator` column expects. Empty values are
    dropped so an xlsx locator doesn't carry nine null docx keys, and the docx
    locator's own `as_dict()` is preferred where it exists because it already
    does this.
    """
    if hasattr(locator, "as_dict"):
        return locator.as_dict()
    if is_dataclass(locator) and not isinstance(locator, type):
        return {
            key: value
            for key, value in asdict(locator).items()
            if value is not None and value != ""
        }
    if isinstance(locator, dict):  # pragma: no cover - defensive
        return {k: v for k, v in locator.items() if v is not None and v != ""}
    raise TypeError(f"cannot serialise locator of type {type(locator).__name__}")


def fingerprint_dict(value: Any) -> dict[str, Any]:
    """A fingerprint as JSONB for `template_versions.fingerprint`.

    `package_parts` is kept in full rather than counted: the whole
    package-integrity claim (plan §4 Ring 3) is *which* parts survived, and a
    stored count could never reconstruct that.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):  # pragma: no cover - defensive
        return dict(value)
    raise TypeError(f"cannot serialise fingerprint of type {type(value).__name__}")
