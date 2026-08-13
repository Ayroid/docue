"""Structural QA for docx: compare fingerprints before/after a compile.

Plan §11 Level 1, the docx half. `structural.py` hard-fails an xlsx compile on
any lost package part because openpyxl is known to drop them. python-docx does
not drop them -- but it *re-serialises the whole package* rather than copying
parts byte-for-byte the way the surgical xlsx compiler does, so docx
preservation is a measured property, not a structural one. That is exactly why
it has to be re-measured on every compile instead of assumed.

The split between what may change and what may not:

- **Never, under any operation:** a package part, a `<w:drawing>`, a
  `<w:hyperlink>` or its relationship, an image relationship, a media file, a
  section, a content control, a header/footer, a customXml part, the
  sensitivity label. Any of these moving is a hard fail and the file is not
  delivered.
- **Only by exactly the declared amount:** paragraph, table, row and cell
  counts. Appending a revision row legitimately adds one `<w:tr>` and nine
  `<w:p>` (one per cell), so a flat "nothing changed" check would fail every
  useful compile. The compiler declares the delta it intended in
  `CompileResult.expected_delta` and QA rejects anything else -- which is
  stricter than tolerating change, not looser.
"""

from dataclasses import dataclass, field

from app.ingestion.fingerprint_docx import DocxFingerprint

# One exception type for the whole QA layer: a caller wrapping a compile
# doesn't need to know which format failed to know the file must not ship.
from app.qa.structural import StructuralQAError

__all__ = [
    "ExpectedDelta",
    "DocxStructuralQAResult",
    "StructuralQAError",
    "diff_docx_fingerprints",
]


@dataclass(frozen=True)
class ExpectedDelta:
    """Growth a compile intends to cause. Anything not declared here is a fail."""

    paragraphs: int = 0
    body_paragraphs: int = 0
    tables: int = 0
    table_rows: int = 0
    table_cells: int = 0

    def __bool__(self) -> bool:
        return any(
            (
                self.paragraphs,
                self.body_paragraphs,
                self.tables,
                self.table_rows,
                self.table_cells,
            )
        )


@dataclass
class DocxStructuralQAResult:
    passed: bool
    lost_parts: list[str]
    added_parts: list[str]
    drawings_before: int
    drawings_after: int
    hyperlinks_before: int
    hyperlinks_after: int
    media_before: int
    media_after: int
    paragraph_delta: int
    table_row_delta: int
    expected: ExpectedDelta = field(default_factory=ExpectedDelta)
    regressions: list[str] = field(default_factory=list)

    @property
    def preserved(self) -> str:
        """One line for the package-integrity panel (plan §4 Ring 3, item 1)."""
        return (
            f"{len(self.lost_parts) == 0 and 'all' or 'NOT ALL'} package parts, "
            f"{self.drawings_after} drawings, {self.media_after} media files, "
            f"{self.hyperlinks_after} hyperlinks"
        )


def diff_docx_fingerprints(
    before: DocxFingerprint,
    after: DocxFingerprint,
    *,
    expected: ExpectedDelta | None = None,
) -> DocxStructuralQAResult:
    """Raise StructuralQAError on any regression; otherwise return the diff."""
    expected = expected or ExpectedDelta()

    lost_parts = sorted(set(before.package_parts) - set(after.package_parts))
    added_parts = sorted(set(after.package_parts) - set(before.package_parts))

    regressions: list[str] = []
    if lost_parts:
        regressions.append(f"lost package parts: {lost_parts}")
    if added_parts:
        # Not a loss, but it means the compiler wrote outside the body part and
        # the preservation argument no longer holds without explaining why.
        regressions.append(f"unexpected new package parts: {added_parts}")

    # A reference to a relationship that isn't declared is what makes Word open
    # a file with "unreadable content" and offer to repair it. Compared as sets
    # rather than absolutely: if the *source* document already had one we can't
    # fix it here, but a compile must not introduce one.
    introduced = sorted(
        set(after.dangling_relationships) - set(before.dangling_relationships)
    )
    if introduced:
        regressions.append(f"introduced dangling relationship references: {introduced}")

    # The counts that must be identical. `drawings` is the one the plan calls
    # out by name: 6 in the BRD, of which `doc.inline_shapes` can only see 1.
    for name in (
        "drawings",
        "inline_drawings",
        "anchored_drawings",
        "legacy_pictures",
        "blips",
        "hyperlinks",
        "hyperlink_rels",
        "image_rels",
        "media_files",
        "sections",
        "content_controls",
        "headers",
        "footers",
        "custom_xml_parts",
        "sensitivity_label",
    ):
        was = getattr(before, name)
        now = getattr(after, name)
        if was != now:
            regressions.append(f"{name} {was} -> {now}")

    # The counts a row insertion is allowed to move, by the declared amount.
    for name, allowed in (
        ("paragraphs", expected.paragraphs),
        ("body_paragraphs", expected.body_paragraphs),
        ("tables", expected.tables),
        ("table_rows", expected.table_rows),
        ("table_cells", expected.table_cells),
    ):
        was = getattr(before, name)
        now = getattr(after, name)
        delta = now - was
        if delta != allowed:
            regressions.append(
                f"{name} {was} -> {now} (delta {delta:+d}, expected {allowed:+d})"
            )

    result = DocxStructuralQAResult(
        passed=not regressions,
        lost_parts=lost_parts,
        added_parts=added_parts,
        drawings_before=before.drawings,
        drawings_after=after.drawings,
        hyperlinks_before=before.hyperlinks,
        hyperlinks_after=after.hyperlinks,
        media_before=before.media_files,
        media_after=after.media_files,
        paragraph_delta=after.paragraphs - before.paragraphs,
        table_row_delta=after.table_rows - before.table_rows,
        expected=expected,
        regressions=regressions,
    )

    if not result.passed:
        raise StructuralQAError(
            "Structural QA failed (docx): " + "; ".join(result.regressions)
        )

    return result
