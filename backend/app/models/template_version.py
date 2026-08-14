import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

LIFECYCLE_DRAFT = "draft"
LIFECYCLE_PENDING = "pending"
LIFECYCLE_PUBLISHED = "published"
LIFECYCLE_SUPERSEDED = "superseded"

ORIGIN_UPLOAD = "upload"
ORIGIN_GENERATED = "generated"


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_template_versions_template_id_version_number"),
        UniqueConstraint("storage_bucket", "storage_key", name="uq_template_versions_bucket_key"),
        CheckConstraint("upload_status IN ('uploaded', 'failed')", name="ck_template_versions_upload_status"),
        CheckConstraint(
            "lifecycle IN ('draft', 'pending', 'published', 'superseded')",
            name="ck_template_versions_lifecycle",
        ),
        CheckConstraint("origin IN ('upload', 'generated')", name="ck_template_versions_origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Plan §8: lineage, so a derived version knows what it came from. A line
    # would only need version_number; this allows a branch -- "Q4 Automotive" and
    # "Q4 Europe" can both derive from v1 without either being the other's parent.
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", ondelete="SET NULL"), nullable=True
    )
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
    # Where this version sits in the version-control story. `draft` is a
    # generated document nobody has asked to publish; `pending` is one waiting
    # on doc control; `published` is or was the template's current version;
    # `superseded` is one that used to be. The last two are not redundant
    # against `templates.current_version_id` -- that says which single version
    # is live *now*, while `superseded` says "this was live once", which is what
    # makes the history read as a lineage rather than a pile of files.
    lifecycle: Mapped[str] = mapped_column(
        String(20), nullable=False, default=LIFECYCLE_PUBLISHED, index=True
    )
    # `upload` or `generated`. Derivable from `storage_key`'s prefix today,
    # which is exactly why it is a column: the prefix is a storage detail, and
    # the two will disagree the first time anyone reorganises the bucket.
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default=ORIGIN_UPLOAD)
    # Who produced these bytes. Nullable because every version predating auth
    # has no author, and `SET NULL` because deleting an account must not delete
    # the record of what they published.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
