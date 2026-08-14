"""Stage ⑦ — the change planner. Plan §10, with one deliberate departure.

**§10 draws this stage as a Sonnet call. It is code.** The departure is worth
stating plainly, because "we skipped a stage" and "we built the stage without a
model" are very different claims and only the second is true.

By the time execution reaches here, every value already carries a `region_id`
(from stage ⑤ or ⑥) and a provenance. The only remaining decision is *which
operation writes a value of this shape into a region of this kind*, and that is
a lookup, not a judgement:

    field / field_empty        →  set_value
    table_loop / table_data    →  clone_table_rows
    repeating_block            →  replace_region_rows
    everything else            →  never targeted

Handing that lookup to a model would add a failure mode -- a `set_value` aimed
at a table, a `clone_table_rows` at a date cell -- with no capability in return,
and would spend 2-5s of an 8s budget (§6) deciding something a dict already
knows. The genuinely generative work is *what the prose says*, and that is a
value produced by the deriver, not an op name chosen here.

What this module does own is the part §3.2 calls load-bearing:

- **Every operation carries a provenance**, so the review screen can badge
  typed / derived / AI-drafted / system without inspecting the value.
- **Protected regions are declared, not just avoided.** A `protect` op is
  emitted for every region the detector marked protected, so the audit trail
  records the guarantee the compile relied on rather than leaving it implicit.
- **Assertions are generated, not hand-written.** One `must_equal` per scalar
  write, plus `package_parts_preserved` on every spec. That block is the
  functional test suite from §11 Level 2, and it exists because the planner
  wrote it, not because someone remembered to.

A region with a null value produces no operation at all. That is the whole
fail-safe: the region keeps whatever the template had, and the review screen
shows it as untouched.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.schemas.change_spec import (
    SPEC_VERSION,
    ChangeSpec,
    CloneTableRowsOp,
    InvariantAssertion,
    ProtectOp,
    ReplaceRegionRowsOp,
    SetBulletsOp,
    SetValueOp,
    Target,
    ValueAssertion,
)

logger = logging.getLogger(__name__)

__all__ = ["PlannedChange", "plan_change_spec", "writes_cleanly"]

# kind -> the op that writes it. Absence means "not writable from a
# conversation", which is the fail-safe default from plan Appendix A.
_SCALAR_OPS = {"field", "field_empty", "title"}
_APPEND_OPS = {"table_loop", "table_data"}
_REPLACE_OPS = {"repeating_block"}


@dataclass
class PlannedChange:
    spec: ChangeSpec
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def operation_count(self) -> int:
        return self.spec.operation_count


def _normalise_rows(region: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """Coerce whatever the extractor produced into column-keyed rows.

    A `repeating_block` is the awkward case: it has no header row, so its
    columns are the synthetic `serial` / `content` pair that
    `region_ops.column_map` exposes. A model handed those names usually returns
    them, but one that returns `{"Summary": "..."}` instead would have its row
    rejected by `_translate(strict=True)` deep in the compiler and the whole
    operation dropped. Folding an unrecognised single-column row into `content`
    keeps the text rather than losing it to a naming disagreement.
    """
    out: list[dict[str, Any]] = []
    if region.kind not in _REPLACE_OPS:
        return [r for r in rows if isinstance(r, dict)]

    known = {"serial", "content", (region.notes or {}).get("column_header")}
    for row in rows:
        if not isinstance(row, dict):
            out.append({"content": str(row)})
            continue
        if any(key in known for key in row):
            out.append(row)
            continue
        # Nothing recognisable: join the values in order rather than drop them.
        joined = " ".join(str(v) for v in row.values() if v)
        if joined:
            out.append({"content": joined})
    return out


def _bullet_items(rows: list[Any]) -> list[str]:
    """Row dicts → bullet strings, for a deck's body placeholder."""
    items: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            text = str(row.get("content") or " ".join(str(v) for v in row.values() if v)).strip()
        else:
            text = str(row).strip()
        if text:
            items.append(text)
    return items


def _op_for(fmt: str, region: Any, value: Any, provenance: str) -> Any | None:
    """The one operation that writes `value` into `region`, or None."""
    target = Target(region_id=region.region_id)

    if isinstance(value, list):
        # A `repeating_block` on a slide is a bullet body, not a table: the
        # pptx compiler reaches a body placeholder through `set_bullets` and has
        # no other door to it. Routing it as a table op is what produced four
        # silent drops on the Workshop Readout deck.
        if fmt == "pptx" and region.kind in _REPLACE_OPS:
            items = _bullet_items(value)
            if not items:
                return None
            return SetBulletsOp(
                op="set_bullets", target=target, items=items, provenance=provenance
            )
        rows = _normalise_rows(region, value)
        if not rows:
            return None
        if region.kind in _APPEND_OPS:
            return CloneTableRowsOp(
                op="clone_table_rows", target=target, rows=rows, provenance=provenance
            )
        if region.kind in _REPLACE_OPS:
            return ReplaceRegionRowsOp(
                op="replace_region_rows", target=target, rows=rows, provenance=provenance
            )
        return None

    text = str(value).strip()
    if not text:
        return None
    if region.kind in _SCALAR_OPS:
        return SetValueOp(
            op="set_value",
            target=target,
            value=text,
            expected_after=text,
            provenance=provenance,
        )
    if region.kind in _APPEND_OPS:
        # A scalar for a table is a single-cell row. Rare, but a user answering
        # "one action: chase the mapping" should not lose it to a shape mismatch.
        columns = [c["name"] for c in (region.notes or {}).get("columns", []) if c.get("name")]
        if columns:
            return CloneTableRowsOp(
                op="clone_table_rows",
                target=target,
                rows=[{columns[0]: text}],
                provenance=provenance,
            )
    return None


def writes_cleanly(fmt: str, region: Any, value: Any) -> bool:
    """Would this value actually produce an operation for this region?

    The same lookup `_op_for` performs, exposed so a caller can ask *before*
    committing to a value rather than discovering at compile time that it was
    dropped. Sharing the implementation is the point: a second opinion written
    somewhere else would eventually disagree with the one that does the work.

    Used by the notes reader, where the answer decides whether a region counts
    as supplied. A list of rows aimed at a date cell produces no operation, so
    it must not be allowed to stand in for an answer -- otherwise the question
    that would have collected a real one is marked as already handled.
    """
    return _op_for(fmt, region, value, "probe") is not None


def plan_change_spec(
    schema: Any,
    filled_values: dict[str, Any],
    derived_values: dict[str, Any] | None = None,
    *,
    base_version_id: uuid.UUID | None = None,
    tier: str = "T2",
    intent: str | None = None,
    question_of_region: dict[str, str] | None = None,
    context_regions: set[str] | None = None,
) -> PlannedChange:
    """Build the Change Spec. Deterministic, and never raises.

    `filled_values` are what the user typed; `derived_values` are what stage ⑥
    concluded, keyed the same way but wrapped as `{value, basis, confidence}`.
    A region present in both keeps the typed value -- a derivation must never
    overwrite a person's own words.
    """
    by_id = {r.region_id: r for r in schema.regions}
    operations: list[Any] = []
    assertions: list[Any] = []
    skipped: list[dict[str, str]] = []

    # (region_id, value, provenance), typed first so it wins on collision.
    #
    # Three roots, narrowest first. `user_answer:q3` is a value given in reply to
    # a specific question. `user_context` is one read out of text the user
    # pasted -- still theirs, still outranking derivation, but not something
    # they wrote in answer to anything, and the review screen says so. Bare
    # `user_answer` is everything else: an instruction, a review-screen edit.
    candidates: list[tuple[str, Any, str]] = []
    for region_id, value in (filled_values or {}).items():
        question = (question_of_region or {}).get(region_id)
        if question:
            provenance = f"user_answer:{question}"
        elif region_id in (context_regions or set()):
            provenance = "user_context"
        else:
            provenance = "user_answer"
        candidates.append((region_id, value, provenance))
    seen = {rid for rid, _, _ in candidates}
    for region_id, wrapped in (derived_values or {}).items():
        if region_id in seen:
            continue
        value = wrapped.get("value") if isinstance(wrapped, dict) else wrapped
        if value is None:
            continue
        candidates.append((region_id, value, "llm_derived"))

    for region_id, value, provenance in candidates:
        region = by_id.get(region_id)
        if region is None:
            skipped.append({"region_id": region_id, "reason": "not in this version's schema"})
            continue
        if not region.editable or region.protected:
            # Unreachable through the normal path -- the context agent only ever
            # offers editable regions -- but a spec built from a resumed session
            # whose version was re-detected could hit it. Refused here so the
            # reason is specific rather than arriving as a compiler drop.
            skipped.append(
                {
                    "region_id": region_id,
                    "reason": f"{region.kind} (editable={region.editable}, "
                    f"protected={region.protected})",
                }
            )
            continue

        operation = _op_for(schema.format, region, value, provenance)
        if operation is None:
            skipped.append(
                {"region_id": region_id, "reason": f"no operation writes a {type(value).__name__} into {region.kind}"}
            )
            continue
        operations.append(operation)

        # One value assertion per scalar write. Tables are excluded on purpose:
        # a cloned row's content is verified by the compiler's own assertions,
        # and re-reading a whole table through the detector to compare it would
        # be a slower, less precise version of the same check.
        if isinstance(operation, SetValueOp):
            ref = getattr(region.locator, "ref", None)
            if ref:
                assertions.append(
                    ValueAssertion(
                        ref=ref,
                        must_equal=operation.value,
                        sheet=getattr(region.locator, "sheet", None),
                    )
                )

    # Declare every protected region. Redundant against the compiler's own
    # pre-flight, and that is the point: the spec should state the guarantee it
    # relied on, so the audit trail is readable without the compiler's source.
    for region in schema.regions:
        if region.protected:
            operations.append(
                ProtectOp(
                    op="protect",
                    target=Target(region_id=region.region_id),
                    reason=region.kind,
                    provenance="system:protect",
                )
            )

    # The invariant the whole project rests on. Present on every spec, always.
    assertions.append(
        InvariantAssertion(invariant="package_parts_preserved", expect="all")
    )

    spec = ChangeSpec(
        spec_version=SPEC_VERSION,
        base_version_id=base_version_id,
        tier=tier,
        intent=intent,
        operations=operations,
        assertions=assertions,
    )
    logger.info(
        "planned %d operation(s) over %d candidate value(s); %d skipped",
        spec.operation_count,
        len(candidates),
        len(skipped),
    )
    return PlannedChange(spec=spec, skipped=skipped)
