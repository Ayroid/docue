import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentSchemaRow(Base):
    """The full region schema for one version, as detected.

    Plan §8's `document_schemas`. Hangs off `version_id`, never `template_id`:
    v2 of a template may have regions v1 didn't, so a schema belongs to the
    bytes it was read from and to nothing else. `UNIQUE` on `version_id`
    because re-ingesting a version replaces its schema rather than adding one.

    `schema_json` keeps the detector's output whole -- including the per-sheet
    and per-slide grouping that `document_regions` flattens away -- so a schema
    can be replayed exactly as it was produced even after the detector changes.
    `detector_version` is what makes that comparison meaningful.

    The class is `DocumentSchemaRow`, not `DocumentSchema`, so it cannot be
    confused with the detectors' `DocumentSchema` dataclass in imports. They are
    different things: one is a row, the other is the detection result.
    """

    __tablename__ = "document_schemas"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_document_schemas_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    detector_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # Null until Track B's region classifier runs over the structural pass.
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
