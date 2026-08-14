import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["DocumentOut", "SubmitVersionIn"]


class SubmitVersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why this should become the next version. Shown to doc control.",
    )
    publish: bool = Field(
        default=False,
        description=(
            "Also point the template at it while it awaits review. Off by default: "
            "doing so takes the template out of the library until an admin decides."
        ),
    )


class DocumentOut(BaseModel):
    """A document somebody made. Not a version of the template it came from."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    template_title: str | None = None
    format: str | None = None
    title: str

    base_version_id: uuid.UUID
    base_version_number: int | None = None
    base_version_is_current: bool = Field(
        default=True,
        description="False when the template has moved on since this was generated.",
    )

    session_id: uuid.UUID | None = None
    size_bytes: int
    created_at: datetime
    created_by: uuid.UUID | None = None

    # Set once the author put this forward as a template version.
    promoted_version_id: uuid.UUID | None = None
    promoted_version_number: int | None = None
    promoted_status: str | None = Field(
        default=None, description="`pending` | `approved` | `rejected`, once submitted."
    )

    download_url: str
