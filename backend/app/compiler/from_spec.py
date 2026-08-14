"""Apply a Change Specification. One entry point over the three compilers.

`app/ingestion/detect.py` did this for detection; this is the same job on the
write side, and it was the same problem. Each format grew its own vocabulary:
`compile_change_spec` twice and `compile_pptx_spec` once, `diff_fingerprints` /
`diff_docx_fingerprints` / `diff_pptx_fingerprints`, `check_assertions` /
`check_docx_assertions` / `check_pptx_assertions`. Six names for three ideas.
Nothing outside `scripts/` could compile anything without knowing which format
it was holding.

**This module is the deterministic boundary from plan §3.** Above it, a model
emits JSON naming regions. Below it, three compilers write bytes. Nothing
crosses except values, and every value passes three gates:

1. **The target must resolve to a region the detector found.** Not found → the
   operation is *dropped and reported*, never guessed at (contract C5). This is
   the injection barrier: a model that invents `sheet1.secret_field`, or hides
   `<w:p/>` in a value, cannot reach a byte, because the only thing it can
   nominate is a name that already exists.
2. **The region must be editable.** Branding, formulas, the Instruction sheet
   and anything unclassified are refused here, and refused again by each
   compiler's own pre-flight before a byte moves.
3. **The result must survive QA.** Structural (nothing lost) and functional
   (every value landed) both run before the caller is allowed to keep the bytes.

Dropped operations are the honest half of this. A spec that half-applies is not
a failure to hide -- plan §14's rule is that a region we could not write is left
untouched and *shown*. `SpecCompileResult.dropped` is how it gets shown.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.ingestion.detect import fingerprint
from app.schemas.change_spec import (
    ChangeSpec,
    ClearRegionOp,
    CloneTableRowsOp,
    ProtectOp,
    ReplaceRegionRowsOp,
    SetBulletsOp,
    SetNotesOp,
    SetValueOp,
)

logger = logging.getLogger("app.compiler.spec")

__all__ = [
    "DroppedOperation",
    "SpecCompileError",
    "SpecCompileResult",
    "compile_spec",
]


class SpecCompileError(RuntimeError):
    """The spec cannot be compiled at all. A dropped operation is not this."""


@dataclass
class DroppedOperation:
    """An operation that never reached the file, and why.

    Surfaced rather than raised: a model naming a region that isn't there is an
    expected event, and the safe response is a visible gap.
    """

    index: int
    op: str
    target: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "op": self.op, "target": self.target, "reason": self.reason}


@dataclass
class AssertionOutcome:
    kind: str  # "value" | "invariant"
    subject: str
    expected: Any
    actual: Any
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
        }


@dataclass
class SpecCompileResult:
    data: bytes
    fmt: str
    applied: int
    dropped: list[DroppedOperation] = field(default_factory=list)
    rows_inserted: int = 0
    structural_passed: bool = False
    structural_detail: dict[str, Any] = field(default_factory=dict)
    functional_passed: bool = False
    functional_checks: int = 0
    spec_assertions: list[AssertionOutcome] = field(default_factory=list)
    protected_regions: list[str] = field(default_factory=list)
    packaging: str | None = None
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Every gate. A caller must not keep the bytes unless this is true."""
        return (
            self.structural_passed
            and self.functional_passed
            and all(outcome.passed for outcome in self.spec_assertions)
        )

    def report(self) -> dict[str, Any]:
        """The QA payload for `qa_runs` and for the review screen."""
        return {
            "overall": "pass" if self.passed else "fail",
            "applied": self.applied,
            "dropped": [d.as_dict() for d in self.dropped],
            "rows_inserted": self.rows_inserted,
            "structural": {"passed": self.structural_passed, **self.structural_detail},
            "functional": {"passed": self.functional_passed, "checks": self.functional_checks},
            "assertions": [a.as_dict() for a in self.spec_assertions],
            "protected_regions": self.protected_regions,
            "packaging": self.packaging,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }


# ── target resolution ─────────────────────────────────────────────────────


def _region_by_id(schema: Any, region_id: str) -> Any | None:
    return next((r for r in schema.regions if r.region_id == region_id), None)


def _region_by_ref(schema: Any, ref: str, sheet: str | None) -> Any | None:
    """Resolve a raw ref to the region that owns it.

    Exact match first, which works for every format. Then, for a workbook,
    geometric containment -- `Sheet1!E5` should find the region whose range
    covers `E5`, because that is how §3.2's own example addresses a field and how
    anyone hand-writing a spec thinks.
    """
    candidates = [
        r
        for r in schema.regions
        if getattr(r.locator, "ref", None) == ref
        and (sheet is None or getattr(r.locator, "sheet", None) == sheet)
    ]
    if candidates:
        return candidates[0]

    try:
        from app.compiler import sheet_xml as sx

        min_col, min_row, max_col, max_row = sx.bounds(ref)
    except Exception:  # noqa: BLE001 - not a workbook ref; nothing more to try
        return None

    for region in schema.regions:
        region_ref = getattr(region.locator, "ref", None)
        region_sheet = getattr(region.locator, "sheet", None)
        if not region_ref or (sheet is not None and region_sheet != sheet):
            continue
        try:
            r_min_col, r_min_row, r_max_col, r_max_row = sx.bounds(region_ref)
        except Exception:  # noqa: BLE001
            continue
        if (
            r_min_col <= min_col
            and max_col <= r_max_col
            and r_min_row <= min_row
            and max_row <= r_max_row
        ):
            return region
    return None


def _resolve(schema: Any, operation: Any) -> tuple[Any | None, str | None]:
    """(region, reason it could not be resolved)."""
    target = operation.target
    if target.region_id:
        region = _region_by_id(schema, target.region_id)
        if region is None:
            return None, f"no region {target.region_id!r} in this version's schema"
        return region, None
    region = _region_by_ref(schema, target.ref, target.sheet)
    if region is None:
        return None, f"no region covers {target.describe()!r}"
    return region, None


# ── per-format op building ────────────────────────────────────────────────


def _date_like(value: Any) -> bool:
    from datetime import date, datetime

    if isinstance(value, (date, datetime)):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True  # an Excel serial
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def _number_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return False
        return True
    return False


def _value_reason(fmt: str, region: Any, operation: Any) -> str | None:
    """Why this value cannot go into this region, if it cannot.

    Only enforced for xlsx, and only because that is the format where the value
    is *converted* rather than written: a workbook date is a number wearing a
    number format, so a string reaching `to_excel_serial` raises deep inside the
    compiler. Word and PowerPoint store the text as given, and a docx field whose
    detected type is `date` legitimately accepts `13/08/2026` as a string.

    Caught here rather than left to raise because a model putting prose in a date
    cell is the same class of event as a model naming a region that doesn't
    exist -- it should be dropped with a reason a human can read, not surfaced as
    `Invalid isoformat string`.
    """
    if fmt != "xlsx" or not isinstance(operation, SetValueOp):
        return None
    declared = operation.value_type or (
        region.value_type if region.value_type in ("string", "number", "date") else None
    )
    if declared == "date" and not _date_like(operation.value):
        return (
            f"region holds a date (value_type={region.value_type!r}) and "
            f"{operation.value!r} is not one; a workbook date is a serial number, "
            "so writing text there would render as a number or fail to convert"
        )
    if declared == "number" and not _number_like(operation.value):
        return f"region holds a number and {operation.value!r} is not one"
    return None


def _build_xlsx(schema: Any, operation: Any, region: Any) -> list[Any]:
    from app.compiler import region_ops

    if isinstance(operation, SetValueOp):
        return [
            region_ops.set_field(
                schema, region.region_id, operation.value, value_type=operation.value_type
            )
        ]
    if isinstance(operation, ClearRegionOp):
        return [region_ops.clear_region(schema, region.region_id)]
    if isinstance(operation, CloneTableRowsOp):
        return [
            region_ops.add_table_rows(
                schema,
                region.region_id,
                operation.rows,
                column_styles=operation.column_styles or None,
                value_types=operation.value_types or None,
            )
        ]
    if isinstance(operation, ReplaceRegionRowsOp):
        rows = [row if isinstance(row, dict) else {"content": row} for row in operation.rows]
        return [
            region_ops.replace_block_rows(
                schema,
                region.region_id,
                rows,
                column_styles=operation.column_styles or None,
                value_types=operation.value_types or None,
            )
        ]
    raise SpecCompileError(f"{operation.op} is not supported for xlsx")


def _build_docx(schema: Any, operation: Any, region: Any) -> list[Any]:
    from app.compiler import docx_compiler as dc

    if isinstance(operation, SetValueOp):
        return [dc.set_field(schema, region.region_id, operation.value)]
    if isinstance(operation, ClearRegionOp):
        return [dc.clear_region(schema, region.region_id)]
    if isinstance(operation, CloneTableRowsOp):
        return [
            dc.add_table_rows(
                schema, region.region_id, operation.rows, value_types=operation.value_types or None
            )
        ]
    if isinstance(operation, ReplaceRegionRowsOp):
        return [
            dc.replace_region_rows(
                schema,
                region.region_id,
                operation.rows,
                value_types=operation.value_types or None,
            )
        ]
    raise SpecCompileError(f"{operation.op} is not supported for docx")


def _build_pptx(schema: Any, operation: Any, region: Any) -> list[Any]:
    from app.compiler import pptx_compiler as pc

    if isinstance(operation, SetValueOp):
        return [pc.set_text(schema, region.region_id, str(operation.value))]
    if isinstance(operation, SetNotesOp):
        return [pc.set_text(schema, region.region_id, operation.text)]
    if isinstance(operation, SetBulletsOp):
        return [pc.set_bullets(schema, region.region_id, operation.items)]
    if isinstance(operation, (CloneTableRowsOp, ReplaceRegionRowsOp)):
        rows = [row for row in operation.rows if isinstance(row, dict)]
        if not rows:
            raise SpecCompileError("a pptx table needs column-keyed rows")
        return [pc.set_table_rows(schema, region.region_id, rows)]
    if isinstance(operation, ReplaceRegionRowsOp):  # pragma: no cover - covered above
        raise SpecCompileError("unreachable")
    raise SpecCompileError(f"{operation.op} is not supported for pptx")


_BUILDERS = {"xlsx": _build_xlsx, "docx": _build_docx, "pptx": _build_pptx}


# ── compile ───────────────────────────────────────────────────────────────


def _compile_and_qa(fmt: str, data: bytes, schema: Any, ops: list[Any]) -> dict[str, Any]:
    """Run the format's compiler and both QA levels. The only format switch."""
    if fmt == "xlsx":
        from app.compiler.protect import protected_ranges_from_schema
        from app.compiler.xlsx_surgical import compile_change_spec
        from app.qa.functional import check_assertions
        from app.qa.structural import diff_fingerprints

        result = compile_change_spec(
            data, ops, protected=protected_ranges_from_schema(schema)
        )
        structural = diff_fingerprints(
            fingerprint(data, fmt),
            fingerprint(result.data, fmt),
            expected_merge_delta=result.merge_delta,
        )
        functional = check_assertions(result.data, result.assertions)
        return {
            "data": result.data,
            "applied": result.operations_applied,
            "rows_inserted": result.rows_inserted,
            "packaging": "surgical",
            "structural_detail": {
                "lost_parts": structural.lost_parts,
                "merged_ranges_before": structural.merged_ranges_before,
                "merged_ranges_after": structural.merged_ranges_after,
            },
            "functional_checks": len(functional.checks),
        }

    if fmt == "docx":
        from app.compiler.docx_compiler import (
            compile_change_spec,
            derived_captions_from_schema,
            protected_targets_from_schema,
        )
        from app.qa.functional_docx import check_docx_assertions
        from app.qa.structural_docx import diff_docx_fingerprints

        result = compile_change_spec(
            data,
            ops,
            protected=protected_targets_from_schema(schema),
            derived=derived_captions_from_schema(schema),
        )
        structural = diff_docx_fingerprints(
            fingerprint(data, fmt), fingerprint(result.data, fmt), expected=result.expected_delta
        )
        functional = check_docx_assertions(result.data, result.assertions)
        return {
            "data": result.data,
            "applied": result.operations_applied,
            "rows_inserted": result.rows_inserted,
            "packaging": result.packaging,
            "structural_detail": {
                "lost_parts": structural.lost_parts,
                "preserved": structural.preserved,
                "captions_refreshed": result.captions_refreshed,
            },
            "functional_checks": len(functional.checks),
        }

    if fmt == "pptx":
        from app.compiler.pptx_compiler import compile_pptx_spec, protected_shapes_from_schema
        from app.qa.functional import check_pptx_assertions
        from app.qa.structural import diff_pptx_fingerprints

        result = compile_pptx_spec(data, ops, protected=protected_shapes_from_schema(schema))
        structural = diff_pptx_fingerprints(
            fingerprint(data, fmt),
            fingerprint(result.data, fmt),
            expected_row_delta=result.rows_added,
        )
        functional = check_pptx_assertions(result.data, result.assertions)
        return {
            "data": result.data,
            "applied": result.operations_applied,
            "rows_inserted": result.rows_added,
            "packaging": "library",
            "structural_detail": {
                "lost_parts": structural.lost_parts,
                "text_runs_before": structural.text_runs_before,
                "text_runs_after": structural.text_runs_after,
            },
            "functional_checks": len(functional.checks),
        }

    raise SpecCompileError(f"no compiler for format {fmt!r}")


def _check_spec_assertions(
    spec: ChangeSpec, fmt: str, before: Any, after: Any, data: bytes, schema: Any
) -> list[AssertionOutcome]:
    """Replay the caller's own assertions (plan §11 Level 2).

    Distinct from the compiler's assertions, which say *what was written*. These
    say *what the planner expected*, which is what catches "the document is valid
    but we didn't actually change the venue".
    """
    outcomes: list[AssertionOutcome] = []
    for assertion in spec.assertions:
        invariant = getattr(assertion, "invariant", None)
        if invariant is not None:
            expected = assertion.expect
            if invariant == "package_parts_preserved":
                lost = sorted(set(before.package_parts) - set(after.package_parts))
                outcomes.append(
                    AssertionOutcome("invariant", invariant, expected, lost or "all", not lost)
                )
                continue
            actual = getattr(after, invariant, None)
            outcomes.append(
                AssertionOutcome("invariant", invariant, expected, actual, actual == expected)
            )
            continue

        # A value assertion. Read it back out of the compiled bytes through the
        # region schema, so a `ref` is resolved the same way an operation's is.
        region = _region_by_ref(schema, assertion.ref.split("!")[-1], assertion.sheet)
        actual = None
        if region is not None:
            fresh = _read_region_content(data, fmt, region.region_id)
            actual = fresh
        passed = actual is not None and str(actual).strip() == str(assertion.must_equal).strip()
        outcomes.append(AssertionOutcome("value", assertion.ref, assertion.must_equal, actual, passed))
    return outcomes


def _read_region_content(data: bytes, fmt: str, region_id: str) -> Any:
    """Re-detect the compiled file and read one region's content back.

    Deliberately a fresh detection rather than a targeted read: if the output is
    coherent enough for the detector to find the same region again, that is worth
    more than reading the cell we just wrote with the code that wrote it.
    """
    from app.ingestion.detect import detect

    schema = detect(data, fmt)
    region = _region_by_id(schema, region_id)
    return None if region is None else region.current_content


def compile_spec(
    data: bytes,
    fmt: str,
    schema: Any,
    spec: ChangeSpec,
    *,
    version_id: Any = None,
) -> SpecCompileResult:
    """Apply `spec` to `data`, returning the bytes and every QA verdict.

    `version_id`, when given, is checked against `spec.base_version_id`. Replaying
    a stored spec against different bytes is how a spec that was correct in
    August silently writes the wrong cell in September, and the coordinates in a
    spec are only meaningful for the schema they were planned against.
    """
    started = time.perf_counter()

    if version_id is not None and spec.base_version_id is not None:
        if str(spec.base_version_id) != str(version_id):
            raise SpecCompileError(
                f"this spec was planned against version {spec.base_version_id}, not {version_id}; "
                "re-plan it rather than replaying it against different bytes"
            )

    builder = _BUILDERS.get(fmt)
    if builder is None:
        raise SpecCompileError(f"no compiler for format {fmt!r}")

    ops: list[Any] = []
    dropped: list[DroppedOperation] = []
    warnings: list[str] = []

    for index, operation in enumerate(spec.operations):
        if isinstance(operation, ProtectOp):
            # A declaration. The detector's own `protected` flags are already
            # enforced by every compiler's pre-flight, so this is recorded for
            # the audit trail rather than turned into an op.
            continue

        region, reason = _resolve(schema, operation)
        if region is None:
            dropped.append(
                DroppedOperation(index, operation.op, operation.target.describe(), reason or "unresolved")
            )
            continue
        if not region.editable:
            dropped.append(
                DroppedOperation(
                    index,
                    operation.op,
                    region.region_id,
                    f"region is {region.kind} (editable=False, protected={region.protected})",
                )
            )
            continue
        mismatch = _value_reason(fmt, region, operation)
        if mismatch is not None:
            dropped.append(DroppedOperation(index, operation.op, region.region_id, mismatch))
            continue
        try:
            ops.extend(builder(schema, operation, region))
        except SpecCompileError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unbuildable op is a drop, not a crash
            dropped.append(
                DroppedOperation(
                    index, operation.op, region.region_id, f"{type(exc).__name__}: {exc}"
                )
            )

    if not ops:
        raise SpecCompileError(
            "no operation in this spec could be applied"
            + (f"; dropped: {[d.reason for d in dropped]}" if dropped else "")
        )
    if dropped:
        warnings.append(
            f"{len(dropped)} of {len(spec.operations)} operations were dropped and left untouched"
        )

    before = fingerprint(data, fmt)
    outcome = _compile_and_qa(fmt, data, schema, ops)
    after = fingerprint(outcome["data"], fmt)

    spec_assertions = _check_spec_assertions(spec, fmt, before, after, outcome["data"], schema)

    result = SpecCompileResult(
        data=outcome["data"],
        fmt=fmt,
        applied=outcome["applied"],
        dropped=dropped,
        rows_inserted=outcome["rows_inserted"],
        # Both QA levels raise on failure, so reaching here means they passed.
        structural_passed=True,
        structural_detail=outcome["structural_detail"],
        functional_passed=True,
        functional_checks=outcome["functional_checks"],
        spec_assertions=spec_assertions,
        protected_regions=[r.region_id for r in schema.regions if r.protected],
        packaging=outcome["packaging"],
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
    )
    logger.info(
        "compiled %s spec: %d applied, %d dropped, %d rows, QA %s, %dms",
        fmt,
        result.applied,
        len(result.dropped),
        result.rows_inserted,
        "pass" if result.passed else "FAIL",
        result.duration_ms,
    )
    return result
