import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.jobs.runner import enqueue_ingestion, run_ingestion_job
from app.models.document_region import DocumentRegion
from app.models.document_schema import DocumentSchemaRow
from app.models.job import KIND_INGESTION, Job
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.schemas.ingestion import (
    DocumentSchemaOut,
    IngestionAccepted,
    JobStatusOut,
    RegionOut,
)
from app.schemas.template import TemplateOut, TemplateVersionOut
from app.storage.s3 import delete_file, upload_file

router = APIRouter(prefix="/templates", tags=["templates"])

ALLOWED_FORMATS = {".xlsx": "xlsx", ".docx": "docx", ".pptx": "pptx"}
MIME_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# xlsx/docx/pptx are all zip containers; a valid file must start with the zip local-file-header signature
ZIP_MAGIC = b"PK\x03\x04"
MAX_PAGE_SIZE = 100


def _to_template_out(template: Template, version: TemplateVersion | None) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        title=template.title,
        original_filename=template.original_filename,
        format=template.format,
        status=template.status,
        form_id=template.form_id,
        house_pattern=template.house_pattern,
        current_version_id=template.current_version_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        current_version=TemplateVersionOut.model_validate(version) if version is not None else None,
    )


@router.post("", response_model=IngestionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_template(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> IngestionAccepted:
    """Store the original, then ingest it in the background.

    **This used to answer 201 with the whole `TemplateOut`.** It now answers 202
    with a `job_id`, per contract C6, because ingestion is 15-40s of parsing and
    region detection and holding the request open for it would give the frontend
    nothing to render. The template row exists by the time this returns, so
    `GET /templates/{id}` works immediately -- only its schema arrives later.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Only .xlsx, .docx, .pptx are allowed.",
        )
    fmt = ALLOWED_FORMATS[ext]

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    buffer = io.BytesIO()
    hasher = hashlib.sha256()
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the {settings.max_upload_size_mb}MB upload limit.",
            )
        hasher.update(chunk)
        buffer.write(chunk)

    if size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
    # Taken before the S3 upload: boto3's transfer manager closes the file object
    # it is handed, so reading `buffer` afterwards raises "I/O operation on closed
    # file". The background task needs these bytes, so they are captured here
    # while the buffer is still open.
    payload = buffer.getvalue()
    if payload[:4] != ZIP_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not look like a valid Office Open XML document.",
        )
    buffer.seek(0)

    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    storage_key = f"originals/{template_id}/v1/{file.filename}"

    try:
        upload_file(buffer, storage_key, MIME_TYPES[fmt])
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        template = Template(
            id=template_id,
            title=Path(file.filename).stem,
            original_filename=file.filename,
            format=fmt,
        )
        db.add(template)
        db.flush()  # templates row must exist before template_versions.template_id can reference it

        version = TemplateVersion(
            id=version_id,
            template_id=template_id,
            version_number=1,
            storage_bucket=settings.s3_bucket_name,
            storage_key=storage_key,
            file_hash=hasher.hexdigest(),
            size_bytes=size,
            mime_type=MIME_TYPES[fmt],
        )
        db.add(version)
        db.flush()  # template_versions row must exist before templates.current_version_id can reference it

        template.current_version_id = version_id
        # Queued in the same transaction as the template, so a 202 can never
        # hand back a job_id that isn't resolvable yet.
        job = enqueue_ingestion(db, version_id)
        job_id = job.id
        db.commit()
    except Exception as exc:
        db.rollback()
        delete_file(storage_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save template metadata.",
        ) from exc

    # Runs after the response is sent. The bytes are already in memory from
    # hashing, so they are handed over rather than re-fetched from S3.
    background_tasks.add_task(run_ingestion_job, job_id, template_id, version_id, payload)

    return IngestionAccepted(
        template_id=template_id,
        version_id=version_id,
        job_id=job_id,
        status="ingesting",
    )


@router.get("", response_model=list[TemplateOut])
def list_templates(
    page: int = 1,
    page_size: int = 20,
    format: str | None = None,
    db: Session = Depends(get_db),
) -> list[TemplateOut]:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page must be >= 1.")
    if not (1 <= page_size <= MAX_PAGE_SIZE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"page_size must be between 1 and {MAX_PAGE_SIZE}.",
        )
    if format is not None and format not in MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format filter '{format}'. Use one of {sorted(MIME_TYPES)}.",
        )

    query = db.query(Template).filter(Template.status == "active")
    if format is not None:
        query = query.filter(Template.format == format)
    templates = (
        query.order_by(Template.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    )

    version_ids = [t.current_version_id for t in templates if t.current_version_id is not None]
    versions_by_id = {}
    if version_ids:
        versions = db.query(TemplateVersion).filter(TemplateVersion.id.in_(version_ids)).all()
        versions_by_id = {v.id: v for v in versions}

    return [_to_template_out(t, versions_by_id.get(t.current_version_id)) for t in templates]


def _version_for(db: Session, template_id: uuid.UUID, version_id: uuid.UUID | None) -> tuple[Template, TemplateVersion]:
    """The template plus one of its versions, defaulting to the current one.

    A version is only reachable *through* its template here. That is what stops
    a caller walking other templates' versions by guessing UUIDs, and it is why
    both endpoints below take `template_id` in the path even though `version_id`
    alone would be enough to find the rows.
    """
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    target_id = version_id or template.current_version_id
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template has no version."
        )
    version = db.get(TemplateVersion, target_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Version not found for this template."
        )
    return template, version


@router.get("/{template_id}/ingestion/{job_id}", response_model=JobStatusOut)
def ingestion_status(
    template_id: uuid.UUID, job_id: uuid.UUID, db: Session = Depends(get_db)
) -> JobStatusOut:
    """Poll an ingestion job. Terminal states are `succeeded` and `failed`.

    The fingerprint is read from `template_versions` rather than copied into the
    job row -- it belongs to the bytes, not to the run that looked at them, and
    duplicating it would double the size of every job row for nothing.
    """
    job = db.get(Job, job_id)
    if job is None or job.kind != KIND_INGESTION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    # The job's entity is the version; check it really belongs to this template
    # so a job id can't be used to probe an unrelated template.
    _, version = _version_for(db, template_id, job.entity_id)

    summary = job.result or {}
    return JobStatusOut(
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        error=job.error,
        fingerprint=version.fingerprint,
        pipeline_version=summary.get("pipeline_version"),
        detector_version=summary.get("detector_version"),
        regions_detected=summary.get("regions_detected"),
        regions_writable=summary.get("regions_writable"),
        counts_by_kind=summary.get("counts_by_kind"),
        containers=summary.get("containers"),
        house_pattern_matched=summary.get("house_pattern_matched"),
        form_id=summary.get("form_id"),
        in_doc_version=summary.get("in_doc_version"),
        harvest_source=summary.get("harvest_source"),
        region_ids_stable=summary.get("region_ids_stable"),
        enrichment=summary.get("enrichment"),
        warnings=summary.get("warnings", []),
        elapsed_ms=summary.get("elapsed_ms"),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{template_id}/regions", response_model=DocumentSchemaOut)
def get_regions(
    template_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> DocumentSchemaOut:
    """The persisted Document Schema. Defaults to the template's current version.

    Regions come back in `sequence` order, which is document order across the
    whole file. Not `ordinal`: that is the detector's own numbering and it
    restarts at 0 on every sheet, so BFL has four regions numbered 0 and sorting
    by it would interleave the sheets in whatever order Postgres returned them.
    """
    template, version = _version_for(db, template_id, version_id)

    schema_row = (
        db.query(DocumentSchemaRow)
        .filter(DocumentSchemaRow.version_id == version.id)
        .one_or_none()
    )
    if schema_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No schema for this version yet. Ingestion may still be running -- "
                f"poll /api/v1/templates/{template_id}/ingestion/{{job_id}}."
            ),
        )

    regions = (
        db.query(DocumentRegion)
        .filter(DocumentRegion.version_id == version.id)
        .order_by(DocumentRegion.sequence)
        .all()
    )
    counts: dict[str, int] = {}
    for region in regions:
        counts[region.kind] = counts.get(region.kind, 0) + 1

    return DocumentSchemaOut(
        template_id=template.id,
        version_id=version.id,
        format=template.format,
        detector_version=schema_row.detector_version,
        regions_detected=len(regions),
        regions_writable=sum(1 for region in regions if region.editable),
        counts_by_kind=dict(sorted(counts.items())),
        form_id=template.form_id,
        house_pattern=template.house_pattern,
        in_doc_version=version.in_doc_version,
        created_at=schema_row.created_at,
        regions=[RegionOut.model_validate(region) for region in regions],
    )


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db)) -> TemplateOut:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")

    return _to_template_out(template, version)
