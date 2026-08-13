import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentRegion(Base):
    """One detected region. Plan §8's `document_regions`, contract C3's shape.

    Column names match the `Region` dataclass the three detectors return, so
    persisting is a field-for-field copy with no translation layer to drift.

    Two things worth knowing before querying this table:

    * **`locator` is polymorphic by design.** `{sheet, ref, sheet_file}` for
      xlsx, `{part, para_index, run_span}` for docx, `{slide_index, slide_part,
      shape_id}` for pptx. Plan §8 always specified one JSONB column for it;
      three sets of typed columns would be mostly null in every row.
    * **`notes` is not decoration.** It carries what the compiler needs to act
      on the region: a table's `columns` and `template_row`, a block's
      `insert_at_row`, the MOM's `serial_gaps`, the docx caption's
      `caption_count_template`. `region_ops.add_table_rows` reads it directly,
      so a schema persisted without `notes` would be readable but not usable.
      This column is an addition to §8's DDL, which predates the detectors
      carrying notes.

    `semantic_role`, `derivable_from`, `row_template_ref` and `question_group`
    are Track B's to fill: the structural pass cannot know a region's meaning or
    which question should cover it. They are nullable and stay null after
    ingestion.
    """

    __tablename__ = "document_regions"
    __table_args__ = (
        UniqueConstraint("version_id", "region_id", name="uq_document_regions_version_region"),
        Index("ix_document_regions_version_question_group", "version_id", "question_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    current_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    derivable_from: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    row_template_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detection_method: Mapped[str] = mapped_column(String(30), nullable=False)
    question_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # `ordinal` is the detector's own, kept exactly as contract C3 hands it over.
    # For a workbook it restarts at 0 on every sheet, so it is *not* a total
    # order: BFL has four sheets and therefore four regions numbered 0. Ordering
    # a region map by it alone returns rows in whatever order Postgres feels
    # like, interleaving sheets.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Position within the whole document, assigned at ingestion from the order
    # the detector emits regions in -- which is sheet by sheet, slide by slide,
    # paragraph by paragraph. This is what `GET /regions` sorts by.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
