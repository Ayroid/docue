import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalOut(BaseModel):
    """One row of the approval queue.

    Flattened across `templates` and `template_versions` rather than nesting
    them: the queue is a table, every column here is one the reviewer reads
    before deciding, and a nested shape would make the frontend dig for the
    submitter's name.
    """

    version_id: uuid.UUID
    template_id: uuid.UUID
    title: str
    original_filename: str
    format: str
    version_number: int
    approval_status: str
    size_bytes: int
    file_hash: str
    # Null until the enrichment pass finishes, exactly as on `TemplateOut`.
    # Shown so a reviewer can see what the model thinks the template is for.
    purpose: str | None = None
    category: str | None = None
    form_id: str | None = None
    submitted_by: uuid.UUID | None = None
    submitted_by_name: str | None = None
    submitted_by_email: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    submitted_at: datetime


class ApprovalQueueOut(BaseModel):
    items: list[ApprovalOut]
    pending: int
    total: int


class ApproveIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    # Required, unlike the approval note: a rejection the submitter cannot act
    # on is worse than no review at all.
    note: str = Field(min_length=3, max_length=1000)


class RoleIn(BaseModel):
    role: str
