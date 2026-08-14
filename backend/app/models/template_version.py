import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Review states for a single version. A new upload starts `pending` and is not
# in the library until an admin moves it to `approved`.
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_STATUSES = (APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED)


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_template_versions_template_id_version_number"),
        UniqueConstraint("storage_bucket", "storage_key", name="uq_template_versions_bucket_key"),
        CheckConstraint("upload_status IN ('uploaded', 'failed')", name="ck_template_versions_upload_status"),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_template_versions_approval_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    upload_status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    # The `Ver.` the document claims about itself, read out of its own revision
    # block during ingestion. Comparing it to `version_number` is drift
    # detection with no diffing at all (plan §1.3): a personal copy still
    # saying `Ver. 1` while the hub is at 3 is two versions behind, provably.
    in_doc_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # The package fingerprint of these exact bytes. Kept in full, `package_parts`
    # included, because the package-integrity claim is *which* parts survived --
    # a stored count could never reconstruct that.
    fingerprint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ── review state ──────────────────────────────────────────────────────
    # Approval lives on the *version*, not the template: v2 of an approved
    # template is an unreviewed document and must not inherit v1's approval.
    # This is what `GET /templates` filters on, so an unapproved upload is
    # genuinely absent from the library rather than merely labelled.
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=APPROVAL_PENDING, index=True
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # The reviewer's own words, shown to the submitter. Required on a rejection
    # -- "no" without a reason gives the submitter nothing to act on.
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
