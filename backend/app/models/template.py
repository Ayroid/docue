import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Pinned to what `cohere.embed-v4:0` returns at output_dimension=1024, and
# asserted at call time in `app/ai/bedrock.py::embed`. Changing it means
# re-embedding every row, so it lives next to the column it defines.
EMBEDDING_DIMENSIONS = 1024


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint("format IN ('xlsx', 'docx', 'pptx')", name="ck_templates_format"),
        CheckConstraint("status IN ('active', 'deleted')", name="ck_templates_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    # Both harvested during ingestion from what detection already finds and used
    # to throw away. `form_id` is YMSLI's own identifier, read off the document
    # ("YMSLI-F-MOM"), which is the strongest BM25 term the corpus has.
    # `house_pattern` records that the file follows the Cover/History/
    # Instruction shape, which is what makes the revision block trustworthy.
    form_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    house_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── generated discovery metadata (plan §9) ────────────────────────────
    # Written by the LLM metadata pass, not by the uploader. `embedding` is of
    # these fields concatenated -- never of the document body -- so a template
    # is found by what it is for rather than by whose data happens to be in it.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    when_to_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    metadata_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Who uploaded it. Nullable because every template that predates accounts
    # has no owner and inventing one would be a lie; the approval notification
    # falls back to the admins when it is null.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id", use_alter=True, name="fk_templates_current_version"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)
