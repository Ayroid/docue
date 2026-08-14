"""Promoting a generated document to be the template everyone else gets.

The rule, in one place because two endpoints enforce it -- an admin promoting
their own document and an admin approving somebody else's -- and because those
two drifting on what "published" means is exactly the bug this module exists to
make impossible.

**Publishing re-ingests.** A promoted version goes through `enqueue_ingestion` +
`run_ingestion_job`, the same pair `POST /templates` uses, and that is the whole
requirement: region detection, metadata and the embedding are all derived from
the *bytes*, so a version published without re-ingesting would be searchable by
a description of the document it replaced. Discovery would keep answering with
the old purpose and tags while serving the new file. Calling the upload path
rather than reimplementing it is deliberate -- a second ingestion route would
eventually disagree with the first about what a template is.

**What promotion does not do.** It never rewrites bytes and never renumbers a
version. The generated file was compiled, QA-gated and stored at commit time;
promotion is a decision about an artefact that already exists, not a new
compile. That keeps the promoted bytes byte-identical to the ones whoever
approved them actually reviewed, which is the only thing that makes an approval
mean anything.
"""

import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.identity import ROLE_ADMIN, Actor
from app.jobs.runner import enqueue_ingestion
from app.models.template import Template
from app.models.template_version import (
    LIFECYCLE_DRAFT,
    LIFECYCLE_PENDING,
    LIFECYCLE_PUBLISHED,
    LIFECYCLE_SUPERSEDED,
    ORIGIN_GENERATED,
    TemplateVersion,
)
from app.models.version_promotion import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    VersionPromotion,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PromotionOutcome",
    "approve",
    "notify",
    "reject",
    "request_or_publish",
]


@dataclass
class PromotionOutcome:
    """What happened, and what the caller must run after the response is sent.

    `ingestion` is a job id rather than a started job: the ingestion has to run
    *after* the transaction commits, or the background worker opens its own
    session and finds no version to ingest. The router owns `BackgroundTasks`,
    so the service says what to run and the router runs it.
    """

    promotion: VersionPromotion
    published: bool
    ingestion_job_id: uuid.UUID | None = None
    version: TemplateVersion | None = None


def notify(
    db: Session,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    template_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
) -> None:
    """Write one row into the auth branch's `notifications` table.

    Raw SQL and no model, for the reason `app/core/identity.py` gives: mapping a
    class onto a table another branch already maps would be a configuration
    error the moment the two meet. The columns are stable -- they are in the
    migrated database -- and this is the only writer here.

    A notification is never worth failing a promotion over. If the insert fails
    the approval still stands and the failure is logged, because the alternative
    is a 500 on an action that already succeeded.
    """
    try:
        db.execute(
            text(
                """
                INSERT INTO notifications
                    (id, user_id, kind, title, body, template_id, version_id, created_at)
                VALUES
                    (:id, :user_id, :kind, :title, :body, :template_id, :version_id, now())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": str(user_id),
                "kind": kind,
                "title": title,
                "body": body,
                "template_id": str(template_id) if template_id else None,
                "version_id": str(version_id) if version_id else None,
            },
        )
    except Exception:  # noqa: BLE001 - a lost notification must not undo a decision
        logger.exception("could not write a %s notification for user %s", kind, user_id)


def _admin_ids(db: Session) -> list[uuid.UUID]:
    rows = db.execute(
        text("SELECT id FROM users WHERE role = :role AND status = 'active'"),
        {"role": ROLE_ADMIN},
    ).all()
    return [r.id for r in rows]


def _assert_promotable(db: Session, template: Template, version: TemplateVersion) -> None:
    """Everything that makes this version ineligible, refused with a reason."""
    if version.template_id != template.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That version does not belong to this template.",
        )
    if version.origin != ORIGIN_GENERATED:
        # An upload is already a template; promoting it would mean re-pointing
        # `current_version_id` at a version that never left the library, which
        # is a rollback and deserves its own endpoint and its own audit line.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only a generated document can be promoted. This version was uploaded.",
        )
    if template.current_version_id == version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That version is already the current one.",
        )
    if version.lifecycle == LIFECYCLE_SUPERSEDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That version has already been published and replaced.",
        )

    existing = db.execute(
        select(VersionPromotion).where(
            VersionPromotion.version_id == version.id,
            VersionPromotion.status == STATUS_PENDING,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is already waiting on doc control.",
        )


def _publish(
    db: Session, template: Template, version: TemplateVersion, actor: Actor
) -> uuid.UUID:
    """Make `version` current and queue its re-ingestion. Returns the job id.

    Not committed here: the caller commits, so that publishing and the promotion
    row that records it land together or not at all.
    """
    previous_id = template.current_version_id
    if previous_id and previous_id != version.id:
        previous = db.get(TemplateVersion, previous_id)
        if previous is not None:
            previous.lifecycle = LIFECYCLE_SUPERSEDED

    version.lifecycle = LIFECYCLE_PUBLISHED
    template.current_version_id = version.id

    # The same call `POST /templates` makes. See the module docstring.
    job = enqueue_ingestion(db, version.id)
    logger.info(
        "version %s (v%s) of template %s published by %s; ingestion job %s queued",
        version.id,
        version.version_number,
        template.id,
        actor.username,
        job.id,
    )
    return job.id


def request_or_publish(
    db: Session,
    template: Template,
    version: TemplateVersion,
    actor: Actor,
    *,
    note: str | None = None,
) -> PromotionOutcome:
    """An admin publishes; anyone else asks. One entry point for both.

    A promotion row is written either way. An admin's own promotion is recorded
    as approved-by-themselves rather than skipped, so the history answers "how
    did this become the current version" the same way regardless of who acted --
    a version that simply appeared, with no row explaining it, is the gap an
    audit trail exists to close.
    """
    _assert_promotable(db, template, version)

    promotion = VersionPromotion(
        id=uuid.uuid4(),
        template_id=template.id,
        version_id=version.id,
        requested_by_id=actor.user_id,
        requested_role=actor.role,
        note=note,
        status=STATUS_PENDING,
    )
    db.add(promotion)

    if not actor.is_admin:
        version.lifecycle = LIFECYCLE_PENDING
        try:
            db.commit()
        except IntegrityError:
            # The partial unique index caught a double submit. Someone else's
            # identical request is already queued, which is the outcome the
            # caller wanted anyway.
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This document is already waiting on doc control.",
            ) from None
        db.refresh(promotion)

        for admin_id in _admin_ids(db):
            notify(
                db,
                user_id=admin_id,
                kind="promotion_requested",
                title="A new template version is waiting for approval",
                body=(
                    f"{actor.username} asked to publish v{version.version_number} of "
                    f"{template.title}."
                ),
                template_id=template.id,
                version_id=version.id,
            )
        db.commit()
        logger.info(
            "promotion %s requested by %s for version %s", promotion.id, actor.username, version.id
        )
        return PromotionOutcome(promotion=promotion, published=False, version=version)

    promotion.status = STATUS_APPROVED
    promotion.decided_by_id = actor.user_id
    promotion.decided_at = _now()
    promotion.decision_note = "Published directly by doc control."
    job_id = _publish(db, template, version, actor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is already waiting on doc control.",
        ) from None
    db.refresh(promotion)
    db.refresh(version)
    return PromotionOutcome(
        promotion=promotion, published=True, ingestion_job_id=job_id, version=version
    )


def approve(
    db: Session, promotion: VersionPromotion, actor: Actor, *, note: str | None = None
) -> PromotionOutcome:
    """Publish the version this request names."""
    _assert_pending(promotion)
    template = db.get(Template, promotion.template_id)
    version = db.get(TemplateVersion, promotion.version_id)
    if template is None or version is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The template or version this request names no longer exists.",
        )
    if template.current_version_id == version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That version is already the current one.",
        )

    promotion.status = STATUS_APPROVED
    promotion.decided_by_id = actor.user_id
    promotion.decided_at = _now()
    promotion.decision_note = note
    job_id = _publish(db, template, version, actor)
    db.commit()
    db.refresh(promotion)
    db.refresh(version)

    notify(
        db,
        user_id=promotion.requested_by_id,
        kind="promotion_decided",
        title="Your template version was published",
        body=f"v{version.version_number} of {template.title} is now the current version.",
        template_id=template.id,
        version_id=version.id,
    )
    db.commit()
    return PromotionOutcome(
        promotion=promotion, published=True, ingestion_job_id=job_id, version=version
    )


def reject(
    db: Session, promotion: VersionPromotion, actor: Actor, *, note: str | None = None
) -> PromotionOutcome:
    """Refuse the request and return the version to a draft.

    Back to `draft`, not to some `rejected` state: the document is still a
    perfectly good generated file that its author can download, and a rejected
    *request* is already recorded on the promotion row. Marking the version
    itself rejected would conflate "doc control said not this one" with "these
    bytes are bad".
    """
    _assert_pending(promotion)
    version = db.get(TemplateVersion, promotion.version_id)
    template = db.get(Template, promotion.template_id)

    promotion.status = STATUS_REJECTED
    promotion.decided_by_id = actor.user_id
    promotion.decided_at = _now()
    promotion.decision_note = note
    if version is not None and version.lifecycle == LIFECYCLE_PENDING:
        version.lifecycle = LIFECYCLE_DRAFT
    db.commit()
    db.refresh(promotion)

    notify(
        db,
        user_id=promotion.requested_by_id,
        kind="promotion_decided",
        title="Your template version was not published",
        body=(note or "Doc control did not approve this version.")
        + (f" ({template.title})" if template else ""),
        template_id=promotion.template_id,
        version_id=promotion.version_id,
    )
    db.commit()
    return PromotionOutcome(promotion=promotion, published=False, version=version)


def _assert_pending(promotion: VersionPromotion) -> None:
    if promotion.status != STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This request was already {promotion.status}.",
        )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
