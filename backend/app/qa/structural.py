"""Structural QA: compare fingerprints before/after a compile. No AI, no rendering."""

from dataclasses import dataclass

from app.ingestion.fingerprint import Fingerprint


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
