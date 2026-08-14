import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PromotionDecisionIn",
    "PromotionOut",
    "PromotionRequestIn",
    "VersionHistoryOut",
    "VersionOut",
]


class PromotionRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why this should become the next version. Shown to doc control.",
    )


class PromotionDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Sent to whoever asked. On a rejection this is the only explanation they get.",
    )


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    template_title: str | None = None
    version_id: uuid.UUID
    version_number: int | None = None
    requested_by_id: uuid.UUID
    requested_by: str | None = Field(
        default=None, description="Username, resolved for display."
    )
    requested_role: str
    note: str | None = None
    status: str
    decided_by_id: uuid.UUID | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    # Present when the decision published something, so the caller can poll it.
    ingestion_job_id: uuid.UUID | None = Field(
        default=None,
        description="The re-ingestion queued by publishing. Poll it like an upload's job.",
    )


class VersionOut(BaseModel):
    """One row of a template's history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    lifecycle: str
    origin: str
    is_current: bool
    created_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by: str | None = None
    size_bytes: int
    in_doc_version: str | None = None
    # The `Ver.` the document claims about itself vs the number the hub gave it.
    # Disagreement is drift, detectable without opening the file.
    claims_stale_version: bool = False
    download_url: str | None = None

    # ── change detection (from the stored change_spec) ────────────────────
    summary: str = "Uploaded"
    changed: list[dict[str, Any]] = Field(default_factory=list)
    dropped: list[dict[str, Any]] = Field(default_factory=list)
    protected_regions: list[str] = Field(default_factory=list)
    qa_overall: str | None = None
    intent: str | None = None

    # Set when this version is waiting on doc control.
    pending_promotion_id: uuid.UUID | None = None


class VersionHistoryOut(BaseModel):
    template_id: uuid.UUID
    template_title: str
    current_version_id: uuid.UUID | None = None
    versions: list[VersionOut] = Field(default_factory=list)
