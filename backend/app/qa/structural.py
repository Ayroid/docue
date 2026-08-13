"""Structural QA: compare fingerprints before/after a compile. No AI, no rendering."""

from dataclasses import dataclass, field

from app.ingestion.fingerprint import Fingerprint, PptxFingerprint


class StructuralQAError(RuntimeError):
    pass


@dataclass
class StructuralQAResult:
    passed: bool
    lost_parts: list[str]
    merged_ranges_before: int
    merged_ranges_after: int
    expected_merge_delta: int = 0

    @property
    def merge_delta(self) -> int:
        return self.merged_ranges_after - self.merged_ranges_before


def diff_fingerprints(
    before: Fingerprint,
    after: Fingerprint,
    *,
    expected_merge_delta: int = 0,
) -> StructuralQAResult:
    """Raise StructuralQAError on any regression; otherwise return the diff.

    `expected_merge_delta` exists because row insertion legitimately changes
    the merge count: cloning MOM row 11 clones its `B11:G11` merge too. The
    compiler reports the delta it intended (`CompileResult.merge_delta`), and
    QA then treats anything *other* than that number as a failure -- which is
    stricter than tolerating change, not looser.
    """
    lost_parts = sorted(set(before.package_parts) - set(after.package_parts))
    merge_delta = after.merged_ranges - before.merged_ranges
    passed = (
        not lost_parts
        and merge_delta == expected_merge_delta
        and before.sensitivity_label == after.sensitivity_label
        and before.rich_value_parts == after.rich_value_parts
        and before.media_files == after.media_files
        and before.sheets == after.sheets
    )

    result = StructuralQAResult(
        passed=passed,
        lost_parts=lost_parts,
        merged_ranges_before=before.merged_ranges,
        merged_ranges_after=after.merged_ranges,
        expected_merge_delta=expected_merge_delta,
    )

    if not passed:
        raise StructuralQAError(
            f"Structural QA failed: lost_parts={lost_parts}, "
            f"merged_ranges {before.merged_ranges}->{after.merged_ranges} "
            f"(delta {merge_delta}, expected {expected_merge_delta}), "
            f"sensitivity_label {before.sensitivity_label}->{after.sensitivity_label}, "
            f"rich_value_parts {before.rich_value_parts}->{after.rich_value_parts}, "
            f"media_files {before.media_files}->{after.media_files}, "
            f"sheets {before.sheets}->{after.sheets}"
        )

    return result


@dataclass
class PptxStructuralQAResult:
    passed: bool
    lost_parts: list[str]
    text_runs_before: int
    text_runs_after: int
    table_rows_before: int
    table_rows_after: int
    violations: list[str] = field(default_factory=list)


def diff_pptx_fingerprints(
    before: PptxFingerprint,
    after: PptxFingerprint,
    *,
    expected_row_delta: int = 0,
) -> PptxStructuralQAResult:
    """Compare deck fingerprints, distinguishing invariants from content.

    Slides, layouts, masters, notes slides, shapes, pictures, charts, embedded
    workbooks, media and the sensitivity label are invariants: this compiler
    writes text, never structure, so any change is a bug. Text runs and table
    cells are *content* and move whenever a bullet list or table is rewritten,
    so they are reported rather than enforced -- functional QA is what proves
    the text itself is right.

    `expected_row_delta` is the exception: cloning table rows changes the row
    count on purpose, so the compiler states how many it added and anything
    else fails.
    """
    violations: list[str] = []
    lost_parts = sorted(set(before.package_parts) - set(after.package_parts))
    if lost_parts:
        violations.append(f"parts lost: {lost_parts}")

    for name in (
        "slides",
        "slide_layouts",
        "slide_masters",
        "notes_slides",
        "shapes",
        "pictures",
        "charts",
        "embedded_workbooks",
        "media_files",
        "tables",
        "sensitivity_label",
    ):
        was, now = getattr(before, name), getattr(after, name)
        if was != now:
            violations.append(f"{name} {was}->{now}")

    row_delta = after.table_rows - before.table_rows
    if row_delta != expected_row_delta:
        violations.append(
            f"table_rows {before.table_rows}->{after.table_rows} "
            f"(delta {row_delta}, expected {expected_row_delta})"
        )

    result = PptxStructuralQAResult(
        passed=not violations,
        lost_parts=lost_parts,
        text_runs_before=before.text_runs,
        text_runs_after=after.text_runs,
        table_rows_before=before.table_rows,
        table_rows_after=after.table_rows,
        violations=violations,
    )
    if violations:
        raise StructuralQAError("Structural QA failed: " + "; ".join(violations))
    return result
