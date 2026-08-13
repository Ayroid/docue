"""Surgical-compiler smoke test against the real MOM sample. Read-only on the source file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _artifact import write_artifact  # noqa: E402

from app.compiler.xlsx_surgical import SetValueOp, apply_change_spec  # noqa: E402
from app.ingestion.fingerprint import fingerprint_xlsx  # noqa: E402
from app.qa.structural import StructuralQAError, diff_fingerprints  # noqa: E402

SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "Files" / "MOM Sample.xlsx"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "scratch"
OUTPUT_PATH = OUTPUT_DIR / "MOM_Sample_compiled.xlsx"


def main() -> int:
    if not SAMPLE_PATH.exists():
        print(f"Sample file not found: {SAMPLE_PATH}")
        return 1

    original = SAMPLE_PATH.read_bytes()
    before = fingerprint_xlsx(original)
    print(
        f"Before: {len(before.package_parts)} parts, {before.merged_ranges} merges, "
        f"sensitivity_label={before.sensitivity_label}, rich_value_parts={before.rich_value_parts}"
    )

    operations = [
        SetValueOp(
            sheet_file="xl/worksheets/sheet1.xml",
            ref="E5",
            value="Workshop Session - AP Automation (Cycle 2)",
            value_type="string",
        ),
        SetValueOp(
            sheet_file="xl/worksheets/sheet1.xml",
            ref="B5",
            value=46250,  # Excel date serial; style s="22" carries the d-mmm-yy format
            value_type="date",
            preserve_number_format=True,
        ),
    ]
    compiled = apply_change_spec(original, operations)

    after = fingerprint_xlsx(compiled)
    print(
        f"After:  {len(after.package_parts)} parts, {after.merged_ranges} merges, "
        f"sensitivity_label={after.sensitivity_label}, rich_value_parts={after.rich_value_parts}"
    )

    try:
        result = diff_fingerprints(before, after)
    except StructuralQAError as exc:
        print(f"structural QA: FAIL -- {exc}")
        return 1

    print(f"structural QA: PASS -- parts lost: {result.lost_parts}")

    written = write_artifact(OUTPUT_PATH, compiled)
    print(f"Wrote {written} -- open this in real Microsoft Excel to verify visually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
