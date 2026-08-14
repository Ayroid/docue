import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["VersionHistoryOut", "VersionOut"]


class VersionOut(BaseModel):
    """One row of a template's history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    approval_status: str
    origin: str = Field(description="`generated` if a compile produced it, else `upload`.")
    is_current: bool
    created_at: datetime

    submitted_by: uuid.UUID | None = None
    submitted_by_name: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None

    size_bytes: int
    in_doc_version: str | None = None
    claims_stale_version: bool = Field(
        default=False,
        description="The file's own `Ver.` disagrees with the hub's number. Drift, without a diff.",
    )
    download_url: str | None = None

    # ── change detection, from the stored change_spec ─────────────────────
    summary: str = "Uploaded"
    changed: list[dict[str, Any]] = Field(default_factory=list)
    dropped: list[dict[str, Any]] = Field(default_factory=list)
    protected_regions: list[str] = Field(default_factory=list)
    qa_overall: str | None = None
    intent: str | None = None


class VersionHistoryOut(BaseModel):
    template_id: uuid.UUID
    template_title: str
    current_version_id: uuid.UUID | None = None
    versions: list[VersionOut] = Field(default_factory=list)
