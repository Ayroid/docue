import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.schemas.template import TemplateOut, TemplateVersionOut
from app.storage.s3 import delete_file, download_file, upload_file

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
        current_version_id=template.current_version_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        current_version=TemplateVersionOut.model_validate(version) if version is not None else None,
    )


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def upload_template(file: UploadFile = File(...), db: Session = Depends(get_db)) -> TemplateOut:
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
    if buffer.getvalue()[:4] != ZIP_MAGIC:
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
        db.commit()
    except Exception as exc:
        db.rollback()
        delete_file(storage_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save template metadata.",
        ) from exc

    db.refresh(template)
    db.refresh(version)
    return _to_template_out(template, version)


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


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db)) -> TemplateOut:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")

    return _to_template_out(template, version)


@router.get("/{template_id}/download")
def download_template(template_id: uuid.UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")

    try:
        body = download_file(version.storage_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return StreamingResponse(
        body.iter_chunks(64 * 1024),
        media_type=version.mime_type,
        headers={"Content-Disposition": f'inline; filename="{template.original_filename}"'},
    )
