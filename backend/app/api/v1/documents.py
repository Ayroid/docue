"""Documents people made from templates, and the one route from a document to a
template version.

A document is the ordinary output of the hub: somebody filled in a form and now
has a file. It is nobody's to approve and supersedes nothing, so almost
everything here is a list and a download.

The exception is `submit-as-version`, which is the moment a document stops being
one. That is a claim about the *template* -- "the form should look like this from
now on" -- so it mints a `template_versions` row and goes to doc control, and the
document keeps a pointer to what it became.
"""

import io
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.v1.generate import (
    GENERATED_PREFIX,
    _next_version_number,
    _announce_compiled_version,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.generated_document import GeneratedDocument
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.models.user import ROLE_ADMIN, User
from app.schemas.document import DocumentOut, SubmitVersionIn
from app.storage.s3 import download_file, upload_file

logger = logging.getLogger("app.documents")

router = APIRouter(prefix="/documents", tags=["documents"])


def _visible(document: GeneratedDocument, user: User) -> bool:
    """A document belongs to whoever made it. Admins can see any of them.

    Not because a document is secret from doc control -- one may be submitted to
    them at any moment -- but because a list of everyone's working files is not
    a queue, and showing it as one would bury the things that need a decision.
    """
    return document.created_by == user.id or user.role == ROLE_ADMIN


def _out(db: Session, document: GeneratedDocument) -> DocumentOut:
    template = db.get(Template, document.template_id)
    base = db.get(TemplateVersion, document.base_version_id)
    promoted = (
        db.get(TemplateVersion, document.promoted_version_id)
        if document.promoted_version_id
        else None
    )
    return DocumentOut(
        id=document.id,
        template_id=document.template_id,
        template_title=template.title if template else None,
        format=template.format if template else None,
        title=document.title,
        base_version_id=document.base_version_id,
        base_version_number=base.version_number if base else None,
        # The template has moved on since this was made. Not an error -- the
        # document is still exactly what its author produced -- but it is the
        # difference between "current" and "made from v2 of a form now on v5",
        # which is the whole reason `in_doc_version` drift detection exists.
        base_version_is_current=bool(
            template and template.current_version_id == document.base_version_id
        ),
        session_id=document.session_id,
        size_bytes=document.size_bytes,
        created_at=document.created_at,
        created_by=document.created_by,
        promoted_version_id=document.promoted_version_id,
        promoted_version_number=promoted.version_number if promoted else None,
        promoted_status=promoted.approval_status if promoted else None,
        download_url=f"/api/v1/documents/{document.id}/download",
    )


def _load(db: Session, document_id: uuid.UUID, user: User) -> GeneratedDocument:
    document = db.get(GeneratedDocument, document_id)
    if document is None or not _visible(document, user):
        # 404 rather than 403 for someone else's document: whether a given id
        # exists is not information this endpoint owes a stranger.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(
    template_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DocumentOut]:
    """The caller's documents, newest first.

    Scoped to the caller even for an admin: this is "my documents", and an admin
    wanting everything has the approval queue and the version history instead.
    """
    query = (
        select(GeneratedDocument)
        .where(GeneratedDocument.created_by == user.id)
        .order_by(GeneratedDocument.created_at.desc())
    )
    if template_id is not None:
        query = query.where(GeneratedDocument.template_id == template_id)
    return [_out(db, d) for d in db.execute(query).scalars().all()]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DocumentOut:
    return _out(db, _load(db, document_id, user))


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    document = _load(db, document_id, user)
    try:
        body = download_file(document.storage_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    suffix = document.storage_key.rsplit(".", 1)[-1]
    filename = f"{document.title}.{suffix}"
    return StreamingResponse(
        body,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{document_id}/submit-as-version", response_model=DocumentOut)
def submit_as_version(
    document_id: uuid.UUID,
    request: SubmitVersionIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DocumentOut:
    """Put this document forward as the template's next version.

    **The bytes are copied, not moved.** The document stays exactly where it is
    and stays its author's; what goes to doc control is a new object under
    `generated/`. Moving it would mean a rejected submission took somebody's
    document down with it, and an approved one quietly removed a file the author
    still had a link to.

    A second submission of the same document is refused rather than queued
    twice: `promoted_version_id` already names what it became, and the honest
    answer to "submit again" is to look at that.
    """
    document = _load(db, document_id, user)
    if document.created_by != user.id:
        # Deliberately stricter than reading. An admin may *see* a document, but
        # putting it forward is a claim in its author's name.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person who created a document can submit it as a version.",
        )
    if document.promoted_version_id is not None:
        existing = db.get(TemplateVersion, document.promoted_version_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This document was already submitted as v{existing.version_number} "
                f"({existing.approval_status})."
                if existing
                else "This document has already been submitted."
            ),
        )

    template = db.get(Template, document.template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")

    try:
        data = download_file(document.storage_key).read()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    number = _next_version_number(db, template.id)
    suffix = document.storage_key.rsplit(".", 1)[-1]
    storage_key = f"{GENERATED_PREFIX}/{template.id}/v{number}/{template.title} v{number}.{suffix}"
    try:
        upload_file(io.BytesIO(data), storage_key, document.mime_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    base = db.get(TemplateVersion, document.base_version_id)
    version = TemplateVersion(
        id=uuid.uuid4(),
        template_id=template.id,
        version_number=number,
        parent_version_id=document.base_version_id,
        storage_bucket=settings.s3_bucket_name,
        storage_key=storage_key,
        file_hash=document.file_hash,
        size_bytes=document.size_bytes,
        mime_type=document.mime_type,
        in_doc_version=base.in_doc_version if base else None,
        submitted_by=user.id,
    )
    db.add(version)
    db.flush()
    document.promoted_version_id = version.id
    if request.publish:
        template.current_version_id = version.id
    db.commit()
    db.refresh(document)

    background_tasks.add_task(
        _announce_compiled_version,
        template.id,
        version.id,
        template.title,
        version.version_number,
        user.id,
    )
    logger.info(
        "document %s submitted as v%s of template %s by %s",
        document.id,
        version.version_number,
        template.id,
        user.id,
    )
    return _out(db, document)
