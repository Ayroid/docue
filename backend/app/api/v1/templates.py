import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.template import Template
from app.models.template_version import TemplateVersion
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


def _to_template_out(template: Template, version: TemplateVersion) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        title=template.title,
        original_filename=template.original_filename,
        format=template.format,
        status=template.status,
        current_version_id=template.current_version_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        current_version=TemplateVersionOut.model_validate(version),
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


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db)) -> TemplateOut:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    version = db.get(TemplateVersion, template.current_version_id) if template.current_version_id else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Template has no version.")

    return _to_template_out(template, version)
