"""Compile a Change Spec against a stored version. Plan §4 Ring 1's headline.

    Change Spec → deterministic compiler → new version

That line is described in the plan as "the whole project", and until now it only
existed inside `scripts/`. This is it over HTTP.

**Why this hangs off a version rather than a session.** Plan §6 puts compile and
commit under `POST /sessions/{sid}/compile`, and it should end up there. But the
conversational layer -- context agent, question planner, extractor, deriver --
does not exist yet, and the deterministic half does not need it: a spec is a
spec whether a model or a human wrote it. So the service lives here, addressed
by the version it applies to, and `/sessions/{sid}/compile` becomes a thin
wrapper that looks up the session's spec and calls this. Building it the other
way round would have meant the compile path waiting on the conversation.

**Why the schema is re-detected rather than read from `document_regions`.** The
regions are persisted, but a spec must be resolved against the schema of the
*exact bytes being compiled*. Re-detecting costs 30-300ms and removes a whole
class of failure: a stored schema from an older detector, or from a re-ingest
that has not happened yet, would resolve `region_id`s against coordinates that
no longer describe the file.
"""

import hashlib
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compiler.from_spec import SpecCompileError, compile_spec
from app.core.config import settings
from app.db.session import get_db
from app.ingestion.detect import detect
from app.models.change_spec import (
    STATUS_COMMITTED,
    STATUS_COMPILED,
    STATUS_FAILED,
    ChangeSpecRow,
)
from app.models.qa_run import OVERALL_FAIL, OVERALL_PASS, QaRun
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.schemas.generate import CompileRequest, CompileResponse
from app.storage.s3 import delete_file, download_file, upload_file

logger = logging.getLogger("app.generate")

router = APIRouter(prefix="/templates", tags=["generation"])

# Generated output lives under its own prefix. Plan §2 asks for the immutable
# original store to be distinct from generated artifacts, and `originals/` is
# write-once; a derived version must never land there.
GENERATED_PREFIX = "generated"


def _load(db: Session, template_id: uuid.UUID, version_id: uuid.UUID | None) -> tuple[Template, TemplateVersion]:
    template = db.get(Template, template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")
    target_id = version_id or template.current_version_id
    if target_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template has no version.")
    version = db.get(TemplateVersion, target_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Version not found for this template."
        )
    return template, version


def _next_version_number(db: Session, template_id: uuid.UUID) -> int:
    highest = db.execute(
        select(func.max(TemplateVersion.version_number)).where(
            TemplateVersion.template_id == template_id
        )
    ).scalar()
    return (highest or 0) + 1


def _fetch(version: TemplateVersion) -> bytes:
    try:
        return download_file(version.storage_key).read()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{template_id}/compile", response_model=CompileResponse)
def compile_change_spec_endpoint(
    template_id: uuid.UUID,
    request: CompileRequest,
    db: Session = Depends(get_db),
) -> CompileResponse:
    """Apply a Change Spec. `dry_run` returns the QA verdict and keeps nothing.

    The spec row is written whether or not the compile succeeds. A specification
    that failed QA is exactly the thing you want to still have afterwards -- it
    is the evidence for why no document was produced.
    """
    template, version = _load(db, template_id, request.version_id)
    spec = request.spec

    spec_row = ChangeSpecRow(
        id=uuid.uuid4(),
        template_id=template.id,
        base_version_id=version.id,
        spec_version=spec.spec_version,
        spec_json=spec.model_dump(mode="json"),
        operation_count=spec.operation_count,
        tier=spec.tier,
        intent=spec.intent,
        status=STATUS_FAILED,
    )
    db.add(spec_row)

    data = _fetch(version)
    schema = detect(data, template.format)

    try:
        result = compile_spec(data, template.format, schema, spec, version_id=version.id)
    except SpecCompileError as exc:
        # Keep the spec and the reason; produce no file.
        spec_row.status = STATUS_FAILED
        db.add(
            QaRun(
                id=uuid.uuid4(),
                change_spec_id=spec_row.id,
                dry_run=request.dry_run,
                overall=OVERALL_FAIL,
                structural={"error": str(exc)},
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a compiler refusal is a client error here
        spec_row.status = STATUS_FAILED
        db.add(
            QaRun(
                id=uuid.uuid4(),
                change_spec_id=spec_row.id,
                dry_run=request.dry_run,
                overall=OVERALL_FAIL,
                structural={"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    report = result.report()
    spec_row.dropped_count = len(result.dropped)
    spec_row.dropped = [d.as_dict() for d in result.dropped]

    result_version: TemplateVersion | None = None
    storage_key: str | None = None

    # QA is a gate, not a report: bytes that failed it are never stored, even on
    # an explicit non-dry-run request.
    if not request.dry_run and result.passed:
        number = _next_version_number(db, template.id)
        suffix = version.storage_key.rsplit(".", 1)[-1]
        filename = f"{template.title} v{number}.{suffix}"
        storage_key = f"{GENERATED_PREFIX}/{template.id}/v{number}/{filename}"
        try:
            upload_file(io.BytesIO(result.data), storage_key, version.mime_type)
        except RuntimeError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        try:
            result_version = TemplateVersion(
                id=uuid.uuid4(),
                template_id=template.id,
                version_number=number,
                parent_version_id=version.id,
                storage_bucket=settings.s3_bucket_name,
                storage_key=storage_key,
                file_hash=hashlib.sha256(result.data).hexdigest(),
                size_bytes=len(result.data),
                mime_type=version.mime_type,
                # Carried forward: the document still claims the same `Ver.` in
                # its own revision block until publish writes back to it.
                in_doc_version=version.in_doc_version,
            )
            db.add(result_version)
            db.flush()
            spec_row.result_version_id = result_version.id
            spec_row.status = STATUS_COMMITTED
            if request.publish:
                template.current_version_id = result_version.id
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            delete_file(storage_key)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to record the compiled version.",
            ) from exc
    else:
        spec_row.status = STATUS_COMPILED if result.passed else STATUS_FAILED

    qa_run = QaRun(
        id=uuid.uuid4(),
        change_spec_id=spec_row.id,
        result_version_id=result_version.id if result_version else None,
        dry_run=request.dry_run,
        structural=report["structural"],
        functional=report["functional"],
        assertions=report["assertions"],
        overall=OVERALL_PASS if result.passed else OVERALL_FAIL,
        duration_ms=result.duration_ms,
    )
    db.add(qa_run)
    db.commit()

    logger.info(
        "compiled spec %s for template %s: %s, %d applied, %d dropped, dry_run=%s",
        spec_row.id,
        template.id,
        qa_run.overall,
        result.applied,
        len(result.dropped),
        request.dry_run,
    )

    return CompileResponse(
        change_spec_id=spec_row.id,
        template_id=template.id,
        base_version_id=version.id,
        dry_run=request.dry_run,
        status=spec_row.status,
        overall=qa_run.overall,
        operations_submitted=spec.operation_count,
        operations_applied=result.applied,
        dropped=[d.as_dict() for d in result.dropped],
        rows_inserted=result.rows_inserted,
        structural=report["structural"],
        functional=report["functional"],
        assertions=report["assertions"],
        protected_regions=result.protected_regions,
        packaging=result.packaging,
        warnings=result.warnings,
        duration_ms=result.duration_ms,
        result_version_id=result_version.id if result_version else None,
        result_version_number=result_version.version_number if result_version else None,
        download_url=(
            f"/api/v1/templates/{template.id}/versions/{result_version.id}/download"
            if result_version
            else None
        ),
        qa_run_id=qa_run.id,
        created_at=spec_row.created_at,
    )


@router.get("/{template_id}/versions/{version_id}/download")
def download_version(
    template_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db)
):
    """Download one specific version's bytes.

    The existing `/{template_id}/download` serves whichever version is current;
    a compiled result is deliberately *not* current unless it was published, so
    it needs to be reachable by id or it could not be downloaded at all.
    """
    template, version = _load(db, template_id, version_id)
    try:
        body = download_file(version.storage_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    filename = version.storage_key.rsplit("/", 1)[-1]
    return StreamingResponse(
        body.iter_chunks(64 * 1024),
        media_type=version.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
