import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeneratedDocument(Base):
    """A document somebody made from a template. **Not a version of it.**

    The distinction this table exists to make: filling a form's fields produces
    a document, and a document is not a revision of the form. Before this
    existed the two shared `template_versions`, so ten people generating minutes
    on Monday turned a form into "version 11", every one of those documents
    queued for doc control's approval, and approving one replaced the blank form
    with somebody's filled-in meeting.

    No `version_number` and no `approval_status`, because neither means anything
    here. A document is finished the moment it compiles; there is nobody to
    approve it and nothing for it to supersede.
    """

    __tablename__ = "generated_documents"
    __table_args__ = (
        UniqueConstraint("storage_bucket", "storage_key", name="uq_generated_documents_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The exact bytes this was compiled from. `RESTRICT`, because deleting the
    # version a document came from would strand it: the region ids in its spec
    # would resolve against nothing, and it could never be explained again.
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_sessions.id", ondelete="SET NULL"), nullable=True
    )
    change_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_specs.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Set only when the author submitted this document as a template version.
    # Null is the ordinary case -- "somebody's document" -- not "not yet
    # promoted".
    promoted_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
