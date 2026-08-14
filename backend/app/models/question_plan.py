import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuestionPlan(Base):
    """One planned question. Plan §8's `question_plans`, §10 stage ④.

    Cached per **version**, not per session, and that is the whole point of the
    table: the questions to ask about a document are a property of the document,
    so the second session started against the same version costs zero planner
    calls. It doubles as the §14 outage story -- a plan computed once keeps
    working when Bedrock is not.

    `covers_regions` is the cluster of `region_id`s this one question supplies.
    Every id in it was checked against the version's schema before the row was
    written; the planner does not get to name a target that does not exist
    (contract C5), and the extractor is later constrained to exactly this list.
    """

    __tablename__ = "question_plans"
    __table_args__ = (
        UniqueConstraint("version_id", "question_no", name="uq_question_plans_version_question"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    example: Mapped[str | None] = mapped_column(Text, nullable=True)
    covers_regions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    # Which planner produced it, so a prompt change can invalidate the cache
    # rather than silently serving questions from an older contract.
    planner_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cached_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
