import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

OVERALL_PASS = "pass"
OVERALL_FAIL = "fail"


class QaRun(Base):
    """The QA verdict on one compile. Plan §8's `qa_runs`, §11's three levels.

    Levels 1 and 2 are code and always run: structural proves nothing was *lost*,
    functional proves the edits were actually *made*. `visual` is null until
    LibreOffice and the vision pass exist, and that is deliberate -- an empty
    column is honest where a hardcoded "pass" would not be.

    §8 hangs this off `generated_documents`. That table belongs to the session
    flow, which does not exist yet, so this points at the change spec and the
    version it produced instead: a compile that happens without a session still
    needs its QA recorded, and a dry run has QA but no version at all.
    """

    __tablename__ = "qa_runs"
    __table_args__ = (
        CheckConstraint("overall IN ('pass', 'fail')", name="ck_qa_runs_overall"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    change_spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_specs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null for a dry run: QA ran, no bytes were kept.
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=True)
    structural: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    functional: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    visual: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    assertions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    repairs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    overall: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
