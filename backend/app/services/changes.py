"""What changed between one version and the one it came from.

Derived entirely from rows that already exist. Every generated version was
produced by a `change_specs` row -- the exact operations, their provenance and
the region each one targeted -- and judged by a `qa_runs` row. Re-deriving the
same facts by opening both files and diffing them would be slower, would need a
detection pass per comparison, and would be *less* precise: a diff can tell you
a cell reads differently, but only the spec can tell you a human typed it, the
deriver inferred it, or the extractor pulled it out of a sentence.

The honest limit, stated because the UI must not imply otherwise: this reports
**what was written, not what was overwritten**. Specs record the new value; the
previous contents of a region are not stored anywhere, so "before" is available
only where the region was empty to begin with. A true before/after needs the
base bytes re-read region by region, which is a different and heavier feature.

An upload has no spec, and that is not a gap -- there was no change, there was a
new document. Those versions report `origin='upload'` and no operations, which
is what the history should say about them.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change_spec import ChangeSpecRow
from app.models.document_region import DocumentRegion
from app.models.qa_run import QaRun
from app.models.template_version import TemplateVersion

logger = logging.getLogger(__name__)

__all__ = ["RegionChange", "VersionChanges", "changes_for_versions"]

# A value rendered into a summary line is for humans reading a list, not for
# reconstructing the document. Long prose is cut rather than wrapped.
_MAX_RENDERED = 160


@dataclass
class RegionChange:
    """One region this version wrote, and where the value came from."""

    region_id: str
    label: str | None
    op: str
    value: str | None
    provenance: str | None
    rows_written: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "label": self.label,
            "op": self.op,
            "value": self.value,
            "provenance": self.provenance,
            "rows_written": self.rows_written,
        }


@dataclass
class VersionChanges:
    """The change record for one version. Empty for an upload."""

    version_id: uuid.UUID
    changed: list[RegionChange] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    protected_regions: list[str] = field(default_factory=list)
    qa_overall: str | None = None
    intent: str | None = None
    change_spec_id: uuid.UUID | None = None

    @property
    def summary(self) -> str:
        """One line for a collapsed history row."""
        if self.change_spec_id is None:
            return "Uploaded"
        n = len(self.changed)
        head = f"{n} region{'s' if n != 1 else ''} changed"
        if self.dropped:
            head += f", {len(self.dropped)} not applied"
        return head

    def as_dict(self) -> dict[str, Any]:
        return {
            "version_id": str(self.version_id),
            "summary": self.summary,
            "changed": [c.as_dict() for c in self.changed],
            "dropped": self.dropped,
            "protected_regions": self.protected_regions,
            "qa_overall": self.qa_overall,
            "intent": self.intent,
            "change_spec_id": str(self.change_spec_id) if self.change_spec_id else None,
        }


def _render(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[: _MAX_RENDERED - 1] + "…" if len(text) > _MAX_RENDERED else text


def _labels(db: Session, version_ids: set[uuid.UUID]) -> dict[tuple[uuid.UUID, str], str]:
    """`(version_id, region_id) -> label` for every region of these versions.

    Labels are read from the *base* version's detected regions, which is where
    the human-readable name lives ("Venue", "Date"). A spec only carries ids.
    """
    if not version_ids:
        return {}
    rows = db.execute(
        select(DocumentRegion.version_id, DocumentRegion.region_id, DocumentRegion.label).where(
            DocumentRegion.version_id.in_(version_ids)
        )
    ).all()
    return {(r.version_id, r.region_id): r.label for r in rows if r.label}


def changes_for_versions(
    db: Session, versions: list[TemplateVersion]
) -> dict[uuid.UUID, VersionChanges]:
    """Change records for these versions, keyed by version id.

    Batched rather than per-version: a template with twenty versions would
    otherwise cost sixty round trips to render one history panel.
    """
    result = {v.id: VersionChanges(version_id=v.id) for v in versions}
    if not versions:
        return result

    specs = (
        db.execute(
            select(ChangeSpecRow).where(
                ChangeSpecRow.result_version_id.in_([v.id for v in versions])
            )
        )
        .scalars()
        .all()
    )
    if not specs:
        return result

    qa_by_spec = {
        row.change_spec_id: row
        for row in db.execute(
            select(QaRun).where(QaRun.change_spec_id.in_([s.id for s in specs]))
        )
        .scalars()
        .all()
    }
    labels = _labels(db, {s.base_version_id for s in specs})

    for spec in specs:
        record = result.get(spec.result_version_id)
        if record is None:  # pragma: no cover - the IN clause guarantees it
            continue
        record.change_spec_id = spec.id
        record.intent = spec.intent
        record.dropped = list(spec.dropped or [])
        qa = qa_by_spec.get(spec.id)
        record.qa_overall = qa.overall if qa else None

        payload = spec.spec_json or {}
        for operation in payload.get("operations", []):
            if not isinstance(operation, dict):
                continue
            op_name = operation.get("op")
            region_id = (operation.get("target") or {}).get("region_id") or ""
            if op_name == "protect":
                # Reported separately: "the logo was never written" is a claim
                # about what did *not* change, and mixing it into `changed`
                # would overstate every version's edit count.
                if region_id:
                    record.protected_regions.append(region_id)
                continue
            if not region_id:
                continue

            rows = operation.get("rows")
            record.changed.append(
                RegionChange(
                    region_id=region_id,
                    label=labels.get((spec.base_version_id, region_id)),
                    op=op_name or "set_value",
                    value=_render(operation.get("value")),
                    provenance=operation.get("provenance"),
                    rows_written=len(rows) if isinstance(rows, list) else None,
                )
            )

    return result
