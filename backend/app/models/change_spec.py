import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A spec's life. `planned` is emitted but not compiled; `compiled` passed QA in a
# dry run; `committed` produced a stored version; `failed` did not survive QA.
STATUS_PLANNED = "planned"
STATUS_COMPILED = "compiled"
STATUS_COMMITTED = "committed"
STATUS_FAILED = "failed"


class ChangeSpecRow(Base):
    """A stored Change Specification. Plan §8 calls this table "audit gold".

    The point is replay: every generated document keeps the exact specification
    that produced it, so months later you can prove what changed, who asked for
    it, and which approved version it came from. That only works if the spec is
    stored as the JSON it arrived as -- hence `spec_json` verbatim rather than a
    normalised set of operation rows.

    Two deviations from §8's DDL, both because the conversational layer does not
    exist yet:

    * `session_id` is nullable. A spec compiled directly against a version has no
      session, and refusing to store it until sessions exist would mean the
      compile path had no audit trail at all.
    * `template_id`, `base_version_id` and `result_version_id` are recorded here.
      §8 reaches them through `generated_documents`, which belongs to the session
      flow; without it a spec would be untraceable to the bytes it was planned
      against, which is exactly what makes a replay safe or unsafe.
    """

    __tablename__ = "change_specs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'compiled', 'committed', 'failed')",
            name="ck_change_specs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null on a dry run, and null on a failure -- a spec that produced no bytes
    # points at nothing, rather than at a version that does not exist.
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
    spec_version: Mapped[str] = mapped_column(String(10), nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    operation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How many operations never reached the file, and the reasons. Kept because
    # "we left this region untouched, and here is why" is the honest half of the
    # result and has to survive past the response that reported it.
    dropped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(4), nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PLANNED, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
