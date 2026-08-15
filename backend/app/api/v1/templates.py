import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.access.templates import can_view_version, load_viewable, visible_templates_filter
from app.api.deps import current_user, optional_user
from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.jobs.runner import enqueue_ingestion, run_ingestion_job
from app.models.document_region import DocumentRegion
from app.models.document_schema import DocumentSchemaRow
from app.models.job import KIND_INGESTION, Job
from app.models.template import Template
from app.models.template_version import APPROVAL_APPROVED, APPROVAL_PENDING, TemplateVersion
from app.models.user import ROLE_ADMIN, User
from app.notifications.service import notify_approval_requested
from app.schemas.ingestion import (
    DocumentSchemaOut,
    IngestionAccepted,
    JobStatusOut,
    RegionOut,
)
from app.schemas.template import TemplateOut, TemplateVersionOut
from app.storage.s3 import delete_file, download_file, upload_file

logger = logging.getLogger("app.api.templates")

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


# The rule this module used to own now lives in `app.access.templates`, because
# five other paths reached these same rows without asking it. It takes a session
# now -- a restricted template's grants have to be looked up -- so it is called
# directly rather than through the old zero-session alias.


def _to_template_out(template: Template, version: TemplateVersion | None) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        title=template.title,
        original_filename=template.original_filename,
        format=template.format,
        status=template.status,
        form_id=template.form_id,
        house_pattern=template.house_pattern,
        purpose=template.purpose,
        when_to_use=template.when_to_use,
        audience=template.audience,
        category=template.category,
        tags=list(template.tags or []),
        # Derived rather than stored: "has a vector" is what actually decides
        # whether semantic search can return this template, so it is read from
        # the column that decides it instead of a flag that could disagree.
        searchable=template.embedding is not None,
        approval_status=version.approval_status if version is not None else APPROVAL_PENDING,
        review_note=version.review_note if version is not None else None,
        visibility=template.visibility,
        owner_id=template.owner_id,
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
    user: User = Depends(current_user),
) -> IngestionAccepted:
    """Store the original, then ingest it in the background.

    **This used to answer 201 with the whole `TemplateOut`.** It now answers 202
    with a `job_id`, per contract C6, because ingestion is 15-40s of parsing and
    region detection and holding the request open for it would give the frontend
    nothing to render. The template row exists by the time this returns, so
    `GET /templates/{id}` works immediately -- only its schema arrives later.

    **The version lands `pending` and is not in the library.** `GET /templates`
    filters on approval, so an upload is stored, ingested and searchable-ready
    but genuinely unlisted until an admin approves it. Admins are notified
    in the hub and by email as soon as the row is committed.
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

    is_admin = user.role == ROLE_ADMIN

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
            owner_id=user.id,
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
            # An admin's own upload is approved on arrival. The queue exists so
            # an admin sees a document before the library does, and here the
            # admin *is* the uploader -- routing it through would ask them to
            # approve their own file, and leave the library missing a template
            # they had already decided to publish.
            #
            # Recorded as a real decision rather than a silent exemption:
            # `reviewed_by` names who published it and `reviewed_at` says when,
            # so the audit trail reads the same as any other approval instead of
            # showing an approved version nobody ever reviewed.
            approval_status=APPROVAL_APPROVED if is_admin else APPROVAL_PENDING,
            submitted_by=user.id,
            reviewed_by=user.id if is_admin else None,
            reviewed_at=datetime.now(timezone.utc) if is_admin else None,
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

    # Both run after the response is sent. Notifying the admins takes an SMTP
    # round trip per admin, and the uploader should not wait through it to be
    # told their file was accepted. The bytes are already in memory from
    # hashing, so they are handed over rather than re-fetched from S3.
    background_tasks.add_task(run_ingestion_job, job_id, template_id, version_id, payload)
    # Nothing to announce when the uploader was an admin: the version is already
    # approved, so this would mail every admin -- the uploader included -- asking
    # them to review a decision that has been made. The queue would be empty when
    # they followed the link.
    if not is_admin:
        background_tasks.add_task(
            _announce_submission, template_id, version_id, template.title, user.id
        )

    return IngestionAccepted(
        template_id=template_id,
        version_id=version_id,
        job_id=job_id,
        status="ingesting",
    )


def _announce_submission(
    template_id: uuid.UUID, version_id: uuid.UUID, title: str, submitter_id: uuid.UUID
) -> None:
    """Tell the admins, on its own session.

    A background task outlives the request, and with it the `get_db` session
    that was closed when the response went out -- so this opens its own rather
    than closing over one. Failures are logged and swallowed: the upload
    already succeeded, and the version is in the queue whether or not the
    announcement got out.
    """
    db = SessionLocal()
    try:
        submitter = db.get(User, submitter_id)
        notify_approval_requested(
            db,
            submitter=submitter,
            template_title=title,
            template_id=template_id,
            version_id=version_id,
            version_number=1,
        )
    except Exception:
        logger.exception("Failed to announce version %s for approval", version_id)
    finally:
        db.close()


@router.post(
    "/{template_id}/versions",
    response_model=IngestionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_new_version(
    template_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestionAccepted:
    """Upload a replacement file as this template's next version.

    The other half of "update this template", beside revising it through the
    conversation. Same gate, same ingestion, same notification as a first upload
    -- the only difference is that no `Template` row is created, because this is
    a revision of one that exists rather than a new thing in the library.

    **The format must match.** A template's identity includes what kind of file
    it is: its regions, its compiler and every document ever generated from it
    assume one. Replacing a workbook with a deck is a new template, not a new
    version, and saying so here is kinder than letting the region detector
    discover it later.

    `current_version_id` is deliberately *not* moved. The new version is pending,
    and pointing the template at it would take the template out of the library
    until an admin approves -- which is a decision for whoever approves, not for
    whoever uploads.

    **Gated on being able to see the template first.** This is a write, so it was
    not on the list of read paths that leaked, but it read one: it took any
    `template_id` from any signed-in caller, and the format check below answers
    "This template is a .xlsx file" for a template the caller cannot open --
    confirming it exists and what it is. It also let them queue a pending version
    against it. Proposing a new version of an *approved* template is open to
    everyone, as it was; an unapproved one is now its owner's and admins' alone.
    """
    template, _ = load_viewable(db, template_id, user=user)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Only .xlsx, .docx, .pptx are allowed.",
        )
    fmt = ALLOWED_FORMATS[ext]
    if fmt != template.format:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This template is a .{template.format} file, and a version of it must be "
                f"one too. Upload a .{fmt} as a new template instead."
            ),
        )

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
    payload = buffer.getvalue()
    if payload[:4] != ZIP_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not look like a valid Office Open XML document.",
        )
    buffer.seek(0)

    number = (
        db.query(func.max(TemplateVersion.version_number))
        .filter(TemplateVersion.template_id == template_id)
        .scalar()
        or 0
    ) + 1
    version_id = uuid.uuid4()
    storage_key = f"originals/{template_id}/v{number}/{file.filename}"

    try:
        upload_file(buffer, storage_key, MIME_TYPES[fmt])
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        version = TemplateVersion(
            id=version_id,
            template_id=template_id,
            version_number=number,
            parent_version_id=template.current_version_id,
            storage_bucket=settings.s3_bucket_name,
            storage_key=storage_key,
            file_hash=hasher.hexdigest(),
            size_bytes=size,
            mime_type=MIME_TYPES[fmt],
            approval_status=APPROVAL_PENDING,
            submitted_by=user.id,
        )
        db.add(version)
        db.flush()
        job = enqueue_ingestion(db, version_id)
        job_id = job.id
        db.commit()
    except Exception as exc:
        db.rollback()
        delete_file(storage_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record the new version.",
        ) from exc

    background_tasks.add_task(run_ingestion_job, job_id, template_id, version_id, payload)
    background_tasks.add_task(
        _announce_submission, template_id, version_id, template.title, user.id
    )

    logger.info(
        "template %s received v%s by upload from %s", template_id, number, user.id
    )
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
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> list[TemplateOut]:
    """The library: approved versions only, unless you ask for your own.

    `mine=true` returns the caller's own submissions whatever their review
    state, which is what lets someone watch an upload through the queue. It is
    the only way to see an unapproved template here, and it is scoped to the
    caller -- an anonymous `mine=true` is simply empty.
    """
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

    # Joined to the current version rather than filtered afterwards, so
    # pagination counts the rows the caller will actually receive -- filtering
    # a fetched page would return short pages and skip templates entirely.
    query = (
        db.query(Template, TemplateVersion)
        .join(TemplateVersion, TemplateVersion.id == Template.current_version_id)
        .filter(Template.status == "active")
    )
    if mine:
        if user is None:
            return []
        # No access filter: these are the caller's own uploads. Owning a
        # template is one of the ways `access_ok` grants access, so filtering
        # here could only ever remove rows the rule already allows -- and
        # restricting your own template must not hide it from you.
        query = query.filter(Template.owner_id == user.id)
    else:
        query = query.filter(TemplateVersion.approval_status == APPROVAL_APPROVED)
        # The access half, in the query rather than over the fetched page: this
        # route paginates, and filtering after the fact would return short pages
        # and skip templates entirely.
        query = query.filter(visible_templates_filter(user))
    if format is not None:
        query = query.filter(Template.format == format)

    rows = (
        query.order_by(Template.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    )
    return [_to_template_out(template, version) for template, version in rows]


@router.get("/{template_id}/ingestion/{job_id}", response_model=JobStatusOut)
def ingestion_status(
    template_id: uuid.UUID,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> JobStatusOut:
    """Poll an ingestion job. Terminal states are `succeeded` and `failed`.

    The fingerprint is read from `template_versions` rather than copied into the
    job row -- it belongs to the bytes, not to the run that looked at them, and
    duplicating it would double the size of every job row for nothing.

    **The caller is now resolved and checked.** This route reports on a version,
    and it used to do so for any version whose job id was known -- including
    versions of somebody else's unapproved upload. The uploader keeps access to
    their own job because `can_view_version` grants the submitter it, which is
    what the upload screen polls immediately after a 202.
    """
    job = db.get(Job, job_id)
    if job is None or job.kind != KIND_INGESTION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    # The job's entity is the version; check it really belongs to this template
    # so a job id can't be used to probe an unrelated template.
    _, version = load_viewable(db, template_id, job.entity_id, user=user)

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
    user: User | None = Depends(optional_user),
) -> DocumentSchemaOut:
    """The persisted Document Schema. Defaults to the template's current version.

    Regions come back in `sequence` order, which is document order across the
    whole file. Not `ordinal`: that is the detector's own numbering and it
    restarts at 0 on every sheet, so BFL has four regions numbered 0 and sorting
    by it would interleave the sheets in whatever order Postgres returned them.

    **This is a read of the document's contents, and it is now gated like one.**
    A region schema names every field, label and protected area in the file; it
    was previously served for any template id, approved or not, to a caller who
    did not have to be signed in.
    """
    template, version = load_viewable(db, template_id, version_id, user=user)

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
def get_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> TemplateOut:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")
    if not can_view_version(db, user, template, version):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    return _to_template_out(template, version)


@router.get("/{template_id}/download")
def download_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> StreamingResponse:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")
    if not can_view_version(db, user, template, version):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    try:
        body = download_file(version.storage_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return StreamingResponse(
        body.iter_chunks(64 * 1024),
        media_type=version.mime_type,
        headers={"Content-Disposition": f'inline; filename="{template.original_filename}"'},
    )
