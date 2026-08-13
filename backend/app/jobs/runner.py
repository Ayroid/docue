"""Background job runner for ingestion.

Plan §6 is explicit about skipping Celery: one `BackgroundTasks` worker and a
Postgres `jobs` table, because at this scale a broker is one more thing to
debug at 3am for no gain. The `jobs` row *is* the contract with the frontend --
it is written `queued` inside the request, so the `job_id` in a 202 is always
resolvable by the time the client can ask about it.

Two things this file is careful about, both of which are easy to get wrong with
`BackgroundTasks`:

* **It opens its own session.** The request's session is closed the moment the
  response goes out, so reusing it would fail on the first query. `SessionLocal`
  is used directly rather than the `get_db` dependency, which only makes sense
  inside a request.
* **A failed ingestion does not fail the upload.** The template, the version and
  the S3 object are already committed when the job starts. If detection dies, the
  job records why and the template stays with no schema -- a visible gap, which
  plan §14 prefers to a half-ingested document that looks complete.
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.ingestion.enrich import run_enrichment
from app.ingestion.pipeline import run_ingestion
from app.models.job import (
    KIND_INGESTION,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
)
from app.models.template import Template
from app.models.template_version import TemplateVersion

logger = logging.getLogger("app.jobs")


def create_job(db: Session, kind: str, entity_id: uuid.UUID) -> Job:
    """Add a `queued` job row. The caller commits it with its own work."""
    job = Job(id=uuid.uuid4(), kind=kind, entity_id=entity_id, status=STATUS_QUEUED, progress=0)
    db.add(job)
    return job


def run_ingestion_job(
    job_id: uuid.UUID,
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    data: bytes,
) -> None:
    """Ingest one uploaded version. Entry point for `BackgroundTasks`.

    `data` is handed over in memory rather than re-fetched from S3. The request
    has already buffered the whole file to hash it, so passing those bytes costs
    nothing and keeps `app/storage/` untouched -- it has no download helper, and
    adding one belongs to whoever owns that module. The trade is that the bytes
    stay resident until the job finishes (bounded by `MAX_UPLOAD_SIZE_MB`); a
    real queue worker in another process would have to fetch from S3 instead,
    which would also prove the stored original is readable.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:  # pragma: no cover - the row is committed before this runs
            logger.error("ingestion job %s vanished before it could run", job_id)
            return

        template = db.get(Template, template_id)
        version = db.get(TemplateVersion, version_id)
        if template is None or version is None:
            _fail(db, job, "template or version row missing")
            return

        job.status = STATUS_RUNNING
        job.stage = "fingerprint"
        db.commit()

        def on_stage(stage: str, progress: int) -> None:
            # Committed as it goes so a poller sees movement rather than a
            # single jump at the end. Only the job row is dirty at this point.
            job.stage = stage
            job.progress = progress
            db.commit()

        try:
            result = run_ingestion(db, template, version, data, on_stage=on_stage)
        except Exception as exc:  # noqa: BLE001 - the job records every failure
            logger.exception("ingestion failed for version %s", version_id)
            db.rollback()
            _fail(db, job, f"{type(exc).__name__}: {exc}")
            return

        # ── enrichment: the AI half, and it is allowed to fail ────────────
        # Runs after the structural result is complete and deliberately cannot
        # move the job to `failed`. Two model calls take 25-50s against a
        # pipeline that finished in under a second; if Bedrock is down, rate
        # limited or slow, the template keeps its regions and simply is not yet
        # searchable by meaning. The warning is recorded so a later pass can
        # find the rows worth redoing.
        enrichment_result = None
        try:
            job.stage = "enrich"
            job.progress = 97
            db.commit()
            # SAVEPOINT, not a bare try/except. A failed statement poisons the
            # whole transaction in Postgres, so rolling the *session* back left
            # it unusable and the final "succeeded" commit failed too -- the job
            # then sat at `running` forever, which is the precise outcome
            # "enrichment cannot fail the ingestion" was meant to prevent.
            # A nested transaction unwinds only the enrichment.
            with db.begin_nested():
                enrichment_result = run_enrichment(db, template, version, data)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - never fails the ingestion
            logger.warning("enrichment failed for version %s: %s", version_id, exc)
            enrichment_result = None
            db.rollback()

        job.status = STATUS_SUCCEEDED
        job.stage = "done"
        job.progress = 100
        job.error = None
        job.result = result.job_result() | (
            {"enrichment": enrichment_result.job_result()}
            if enrichment_result is not None
            else {"enrichment": None}
        )
        # One commit for the schema, the regions, the harvest columns and the
        # job's own success, so a poller never sees `succeeded` against a
        # half-written schema.
        db.commit()
        logger.info(
            "ingestion job %s succeeded: %d regions in %dms",
            job_id,
            result.regions_detected,
            result.elapsed_ms,
        )
    finally:
        db.close()


def _fail(db: Session, job: Job, message: str) -> None:
    job.status = STATUS_FAILED
    job.error = message[:4000]
    db.commit()


def enqueue_ingestion(db: Session, version_id: uuid.UUID) -> Job:
    """Convenience wrapper naming the one job kind that exists today."""
    return create_job(db, KIND_INGESTION, version_id)
