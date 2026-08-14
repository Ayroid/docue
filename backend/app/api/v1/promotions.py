"""Version control: promote a generated document, and read a template's history.

Two audiences, one set of rows. An author asks for their document to become the
next version; doc control decides. An admin skips the asking and publishes,
which is not a separate code path -- see `app/services/promotion.py` -- only a
separate branch inside one.

The history endpoint lives here rather than in `templates.py` because it reports
the same lifecycle these endpoints write, and splitting them would put the
producer and the only consumer of `lifecycle` in different files.
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.v1.generate import _fetch
from app.core.identity import AdminActor, AuthedActor, CurrentActor
from app.db.session import get_db
from app.jobs.runner import run_ingestion_job
from app.models.template import Template
from app.models.template_version import TemplateVersion
from app.models.version_promotion import STATUS_PENDING, VersionPromotion
from app.schemas.promotion import (
    PromotionDecisionIn,
    PromotionOut,
    PromotionRequestIn,
    VersionHistoryOut,
    VersionOut,
)
from app.services import promotion as promo
from app.services.changes import changes_for_versions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["versions"])


def _usernames(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """`user_id -> username`, for display only.

    Raw SQL for the reason `app/core/identity.py` gives: no `User` model here,
    because the auth branch already maps that table.
    """
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.execute(
        text("SELECT id, username FROM users WHERE id = ANY(:ids)"),
        {"ids": [str(i) for i in ids]},
    ).all()
    return {r.id: r.username for r in rows}


def _promotion_out(
    db: Session, promotion: VersionPromotion, *, ingestion_job_id: uuid.UUID | None = None
) -> PromotionOut:
    version = db.get(TemplateVersion, promotion.version_id)
    template = db.get(Template, promotion.template_id)
    names = _usernames(db, {promotion.requested_by_id, promotion.decided_by_id})
    return PromotionOut(
        id=promotion.id,
        template_id=promotion.template_id,
        template_title=template.title if template else None,
        version_id=promotion.version_id,
        version_number=version.version_number if version else None,
        requested_by_id=promotion.requested_by_id,
        requested_by=names.get(promotion.requested_by_id),
        requested_role=promotion.requested_role,
        note=promotion.note,
        status=promotion.status,
        decided_by_id=promotion.decided_by_id,
        decided_by=names.get(promotion.decided_by_id) if promotion.decided_by_id else None,
        decision_note=promotion.decision_note,
        created_at=promotion.created_at,
        decided_at=promotion.decided_at,
        ingestion_job_id=ingestion_job_id,
    )


def _queue_reingestion(
    background_tasks: BackgroundTasks, outcome: promo.PromotionOutcome, template_id: uuid.UUID
) -> None:
    """Run the promoted bytes through the upload ingestion path.

    Fetched from S3 rather than handed over in memory, unlike the upload route:
    nothing here has the file buffered, and the fetch doubles as proof the stored
    object is actually readable before it becomes the template everyone gets.
    """
    if outcome.ingestion_job_id is None or outcome.version is None:
        return
    data = _fetch(outcome.version)
    background_tasks.add_task(
        run_ingestion_job,
        outcome.ingestion_job_id,
        template_id,
        outcome.version.id,
        data,
    )


@router.post(
    "/templates/{template_id}/versions/{version_id}/promote",
    response_model=PromotionOut,
)
def promote_version(
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    request: PromotionRequestIn,
    background_tasks: BackgroundTasks,
    actor: AuthedActor,
    db: Session = Depends(get_db),
) -> PromotionOut:
    """Ask for this generated document to become the template's next version.

    An admin's call publishes immediately and answers with an approved
    promotion. Anyone else's queues a pending one. The status field says which
    happened; the caller should not infer it from their own role, because a role
    can change between rendering a button and pressing it.
    """
    template = db.get(Template, template_id)
    version = db.get(TemplateVersion, version_id)
    if template is None or version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such template or version."
        )

    outcome = promo.request_or_publish(db, template, version, actor, note=request.note)
    if outcome.published:
        _queue_reingestion(background_tasks, outcome, template_id)
    return _promotion_out(db, outcome.promotion, ingestion_job_id=outcome.ingestion_job_id)


@router.get("/promotions", response_model=list[PromotionOut])
def list_promotions(
    actor: CurrentActor,
    promotion_status: str = Query(
        default=STATUS_PENDING,
        alias="status",
        pattern="^(pending|approved|rejected|all)$",
        description="`pending` by default -- the queue doc control actually works from.",
    ),
    db: Session = Depends(get_db),
) -> list[PromotionOut]:
    """The promotion queue.

    An admin sees everyone's. Anyone else sees only their own, so the endpoint
    is useful to an author tracking their request without exposing the queue.
    """
    query = select(VersionPromotion).order_by(VersionPromotion.created_at.desc())
    if promotion_status != "all":
        query = query.where(VersionPromotion.status == promotion_status)
    if not actor.is_admin:
        if not actor.is_authenticated:
            return []
        query = query.where(VersionPromotion.requested_by_id == actor.user_id)

    return [_promotion_out(db, p) for p in db.execute(query).scalars().all()]


@router.post("/promotions/{promotion_id}/approve", response_model=PromotionOut)
def approve_promotion(
    promotion_id: uuid.UUID,
    request: PromotionDecisionIn,
    background_tasks: BackgroundTasks,
    actor: AdminActor,
    db: Session = Depends(get_db),
) -> PromotionOut:
    """Publish the version this request names, and re-ingest it."""
    promotion = db.get(VersionPromotion, promotion_id)
    if promotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such request.")

    outcome = promo.approve(db, promotion, actor, note=request.note)
    _queue_reingestion(background_tasks, outcome, promotion.template_id)
    return _promotion_out(db, outcome.promotion, ingestion_job_id=outcome.ingestion_job_id)


@router.post("/promotions/{promotion_id}/reject", response_model=PromotionOut)
def reject_promotion(
    promotion_id: uuid.UUID,
    request: PromotionDecisionIn,
    actor: AdminActor,
    db: Session = Depends(get_db),
) -> PromotionOut:
    """Refuse the request. The version stays a draft its author can still use."""
    promotion = db.get(VersionPromotion, promotion_id)
    if promotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such request.")

    outcome = promo.reject(db, promotion, actor, note=request.note)
    return _promotion_out(db, outcome.promotion)


@router.get("/templates/{template_id}/versions", response_model=VersionHistoryOut)
def version_history(
    template_id: uuid.UUID,
    include_drafts: bool = Query(
        default=True,
        description="Drafts are other people's unpublished documents; hide them for a public view.",
    ),
    db: Session = Depends(get_db),
) -> VersionHistoryOut:
    """Every version of this template, newest first, with what each one changed.

    The change record comes from the stored `change_spec` for each version --
    see `app/services/changes.py` for what that can and cannot say.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such template.")

    query = select(TemplateVersion).where(TemplateVersion.template_id == template_id)
    if not include_drafts:
        query = query.where(TemplateVersion.lifecycle != "draft")
    versions = list(
        db.execute(query.order_by(TemplateVersion.version_number.desc())).scalars().all()
    )

    changes = changes_for_versions(db, versions)
    names = _usernames(db, {v.created_by_id for v in versions})
    pending = {
        p.version_id: p.id
        for p in db.execute(
            select(VersionPromotion).where(
                VersionPromotion.template_id == template_id,
                VersionPromotion.status == STATUS_PENDING,
            )
        )
        .scalars()
        .all()
    }

    rows: list[VersionOut] = []
    for version in versions:
        record = changes[version.id]
        # Drift detection with no diffing: the `Ver.` the file claims about
        # itself against the number the hub gave it.
        claims_stale = bool(
            version.in_doc_version
            and version.in_doc_version.strip().isdigit()
            and int(version.in_doc_version.strip()) != version.version_number
        )
        rows.append(
            VersionOut(
                id=version.id,
                version_number=version.version_number,
                lifecycle=version.lifecycle,
                origin=version.origin,
                is_current=template.current_version_id == version.id,
                created_at=version.created_at,
                created_by_id=version.created_by_id,
                created_by=names.get(version.created_by_id) if version.created_by_id else None,
                size_bytes=version.size_bytes,
                in_doc_version=version.in_doc_version,
                claims_stale_version=claims_stale,
                download_url=f"/api/v1/templates/{template_id}/versions/{version.id}/download",
                summary=record.summary,
                changed=[c.as_dict() for c in record.changed],
                dropped=record.dropped,
                protected_regions=record.protected_regions,
                qa_overall=record.qa_overall,
                intent=record.intent,
                pending_promotion_id=pending.get(version.id),
            )
        )

    return VersionHistoryOut(
        template_id=template.id,
        template_title=template.title,
        current_version_id=template.current_version_id,
        versions=rows,
    )
