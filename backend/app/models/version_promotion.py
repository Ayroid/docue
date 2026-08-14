import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class VersionPromotion(Base):
    """A request to make one version the template's current one.

    Raised when a member finishes a document and asks for it to become the next
    version; an admin's own promotion skips straight to approved and is recorded
    here anyway, so the history reads the same whoever acted.

    Kept apart from `template_versions` because a request has its own lifetime.
    A rejected one has to survive the version being promoted later by somebody
    else, and a column on the version would have to be overwritten to record the
    second attempt -- losing the first, which is the one that explains why the
    document sat unpublished for a week.
    """

    __tablename__ = "version_promotions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_version_promotions_status",
        ),
        # At most one *pending* request per version, any number of decided ones.
        # This is what stops a double-clicked submit button from queueing the
        # same document twice and being approved twice.
        Index(
            "uq_version_promotions_pending",
            "version_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # A snapshot of the role held when the request was raised, not a lookup.
    # Promoting someone to admin next month must not silently rewrite the
    # history of every request they ever made as an admin request.
    requested_role: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING, index=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
