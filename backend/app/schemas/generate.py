import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.change_spec import ChangeSpec


class CompileRequest(BaseModel):
    """Compile a Change Spec against one stored version.

    `dry_run` defaults to **true**, deliberately. Plan §6 exposes the dry run as
    the normal path -- the review screen shows QA and the dropped operations
    before anyone commits -- and a default that wrote a new version on a
    malformed request would be the wrong way round.
    """

    model_config = ConfigDict(extra="forbid")

    spec: ChangeSpec
    version_id: uuid.UUID | None = Field(
        default=None, description="Which version to compile against. Defaults to the current one."
    )
    dry_run: bool = True
    publish: bool = Field(
        default=False,
        description=(
            "On a real run, also point `templates.current_version_id` at the result. "
            "Off by default: a derived document is not automatically the template "
            "everyone should start from."
        ),
    )
    change_note: str | None = None


class DroppedOperationOut(BaseModel):
    """An operation that never reached the file, and why.

    The honest half of the result. Plan §14: a region we could not write is left
    untouched and *shown*, never guessed at.
    """

    index: int
    op: str
    target: str
    reason: str


class AssertionOut(BaseModel):
    kind: str
    subject: str
    expected: Any = None
    actual: Any = None
    passed: bool


class CompileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    change_spec_id: uuid.UUID
    template_id: uuid.UUID
    base_version_id: uuid.UUID
    dry_run: bool
    status: str = Field(description="compiled | committed | failed")
    overall: str = Field(description="pass | fail")

    operations_submitted: int
    operations_applied: int
    dropped: list[DroppedOperationOut] = Field(default_factory=list)
    rows_inserted: int = 0

    structural: dict[str, Any] = Field(default_factory=dict)
    functional: dict[str, Any] = Field(default_factory=dict)
    assertions: list[AssertionOut] = Field(default_factory=list)
    protected_regions: list[str] = Field(
        default_factory=list,
        description="Regions the compiler would have refused. The 'we never wrote the logo' report.",
    )
    packaging: str | None = Field(
        default=None,
        description="`surgical` when the result was rebuilt from the original zip, part for part.",
    )
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int = 0

    # Present only on a committed run.
    result_version_id: uuid.UUID | None = None
    result_version_number: int | None = None
    # Set instead of `result_version_id` when the compile produced somebody's
    # document rather than a candidate revision. Exactly one of the two is ever
    # non-null; both are null on a dry run or a failure.
    result_document_id: uuid.UUID | None = None
    download_url: str | None = None
    qa_run_id: uuid.UUID | None = None
    created_at: datetime | None = None
