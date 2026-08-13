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


def diff_fingerprints(before: Fingerprint, after: Fingerprint) -> StructuralQAResult:
    """Raise StructuralQAError on any regression; otherwise return the diff."""
    lost_parts = sorted(set(before.package_parts) - set(after.package_parts))
    passed = (
        not lost_parts
        and before.merged_ranges == after.merged_ranges
        and before.sensitivity_label == after.sensitivity_label
        and before.rich_value_parts == after.rich_value_parts
    )

    result = StructuralQAResult(
        passed=passed,
        lost_parts=lost_parts,
        merged_ranges_before=before.merged_ranges,
        merged_ranges_after=after.merged_ranges,
    )

    if not passed:
        raise StructuralQAError(
            f"Structural QA failed: lost_parts={lost_parts}, "
            f"merged_ranges {before.merged_ranges}->{after.merged_ranges}, "
            f"sensitivity_label {before.sensitivity_label}->{after.sensitivity_label}, "
            f"rich_value_parts {before.rich_value_parts}->{after.rich_value_parts}"
        )

    return result
