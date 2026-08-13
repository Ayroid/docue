import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Job kinds. Only ingestion exists today; preview rendering, bulk import and
# visual QA are the others plan §6 names.
KIND_INGESTION = "ingestion"

# Terminal states are `succeeded` and `failed`; a poller stops on either.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED)


class Job(Base):
    """An async unit of work the client polls. Plan §8's `jobs`.

    Ingestion takes 15-40s, so `POST /templates` cannot do it inside the
    request. The row is the whole contract with the frontend: it is created
    `queued` before the response goes out, so the `job_id` in a 202 is always
    resolvable, and it advances through `stage`/`progress` as the pipeline runs.

    `result` is an addition to §8's DDL. The job-status payload Track C polls
    has to carry `warnings[]` and `regions_detected`, and neither belongs on
    `template_versions` -- a warning is a fact about *this ingestion run*, not
    about the document. Keeping it as one JSONB summary rather than a column per
    field means adding a stage's output later doesn't need a migration.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_jobs_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Not a foreign key: a job outlives what it refers to. An ingestion job for
    # a version that later gets deleted should still be readable in the log.
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_QUEUED, index=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES
