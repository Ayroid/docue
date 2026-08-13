import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A session's life. `active` is mid-conversation; `planned` has a spec but has
# not compiled; `compiled` survived a dry run; `committed` produced a stored
# version; `abandoned` was walked away from.
STATUS_ACTIVE = "active"
STATUS_PLANNED = "planned"
STATUS_COMPILED = "compiled"
STATUS_COMMITTED = "committed"
STATUS_ABANDONED = "abandoned"


class GenerationSession(Base):
    """One fill conversation. Plan §8's `generation_sessions`, §10's stages ③-⑦.

    Everything the chain learns lives here rather than in memory, and that is
    the reason plan §10 gives for skipping a framework: state in Postgres makes
    every generation inspectable, resumable and auditable, which an in-process
    agent loop does not. A server restart mid-demo costs nothing.

    **`filled_values` and `derived_values` are kept apart on purpose.** They are
    both `{region_id: value}` and it would be tidier to merge them. They are not
    the same claim: one is what the user typed, the other is what the deriver
    concluded, and the review screen badges them differently because a user is
    entitled to know which is which before it reaches a client document. Merging
    them would erase the distinction that makes the provenance story true.
    """

    __tablename__ = "generation_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'planned', 'compiled', 'committed', 'abandoned')",
            name="ck_generation_sessions_status",
        ),
        CheckConstraint("tier IN ('T1', 'T2', 'T3')", name="ck_generation_sessions_tier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The version the questions were planned against, and the only bytes this
    # session's spec may be compiled onto. `compile_spec` re-checks it.
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No users table and no auth yet, so this stays null rather than carrying a
    # fabricated id that a later migration would have to clean up.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tier: Mapped[str] = mapped_column(String(4), nullable=False, default="T2")
    user_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_ACTIVE, index=True)

    # The context agent's partition, stored so a resumed session does not re-run
    # the stage and possibly partition the same regions differently.
    known_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    filled_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    derived_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # One entry per answered question, with what the extractor pulled out of it.
    # This is what `GET /sessions/{sid}` replays into the chat transcript.
    turns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
