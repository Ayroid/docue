"""Write protection, enforced before any bytes are touched.

The claim "the logo survives generation" should be structural, not a matter of
the model behaving. Every region the detector marks `protected` -- branding,
formulas, the Instruction sheet, anything it couldn't classify -- becomes a
range no operation may write into. The check runs on the whole spec up front,
so a bad spec produces an exception instead of a half-written file.

Pre-flight refuses two distinct things:

- a write whose target *intersects* a protected range
- an insertion whose point falls *inside* one, which would tear it in half

An insertion strictly above a protected range is allowed: shifting a merged
logo down by two rows moves it without damaging it, which is exactly what
Excel does when a user inserts a row.
"""

from dataclasses import dataclass

from app.compiler import sheet_xml as sx
from app.compiler.xlsx_surgical import (
    ClearRegionOp,
    CloneTableRowsOp,
    Operation,
    ProtectOp,
    SetValueOp,
)


@dataclass(frozen=True)
class ProtectedRange:
    sheet_file: str
    ref: str
    reason: str = ""
    region_id: str | None = None


class ProtectedWriteError(RuntimeError):
    """An operation targets a range that must not be written."""


def protected_ranges_from_schema(schema: object) -> list[ProtectedRange]:
    """Lift every protected region out of a `DocumentSchema`.

    Typed loosely on purpose: the compiler stays independent of the ingestion
    layer, and this is the one place the two meet.
    """
    ranges: list[ProtectedRange] = []
    for region in getattr(schema, "regions", []):
        if not region.protected:
            continue
        sheet_file = region.locator.sheet_file
        if sheet_file is None:
            continue
        ranges.append(
            ProtectedRange(
                sheet_file=sheet_file,
                ref=region.locator.ref,
                reason=region.kind,
                region_id=region.region_id,
            )
        )
    return ranges


def _intersects(left: str, right: str) -> bool:
    l_min_col, l_min_row, l_max_col, l_max_row = sx.bounds(left)
    r_min_col, r_min_row, r_max_col, r_max_row = sx.bounds(right)
    return (
        l_min_col <= r_max_col
        and r_min_col <= l_max_col
        and l_min_row <= r_max_row
        and r_min_row <= l_max_row
    )


def preflight(operations: list[Operation], protected: list[ProtectedRange]) -> None:
    """Raise `ProtectedWriteError` if any operation would write a protected range."""
    ranges = list(protected)
    for op in operations:
        if isinstance(op, ProtectOp):
            ranges.append(ProtectedRange(op.sheet_file, op.ref, op.reason or "declared"))
    if not ranges:
        return

    for op in operations:
        if isinstance(op, (SetValueOp, ClearRegionOp)):
            for guarded in ranges:
                if op.sheet_file == guarded.sheet_file and _intersects(op.ref, guarded.ref):
                    raise ProtectedWriteError(
                        f"{type(op).__name__} targets {op.ref} which intersects protected "
                        f"{guarded.ref} ({guarded.region_id or guarded.reason}) in "
                        f"{guarded.sheet_file}"
                    )
        elif isinstance(op, CloneTableRowsOp):
            for guarded in ranges:
                if op.sheet_file != guarded.sheet_file:
                    continue
                _, min_row, _, max_row = sx.bounds(guarded.ref)
                if min_row < op.at_row <= max_row:
                    raise ProtectedWriteError(
                        f"inserting at row {op.at_row} would split protected "
                        f"{guarded.ref} ({guarded.region_id or guarded.reason}) in "
                        f"{guarded.sheet_file}"
                    )
