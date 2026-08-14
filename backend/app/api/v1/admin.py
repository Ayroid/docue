"""The approval queue and user administration. Admins only.

Every route here depends on `current_admin`, which re-reads the role from the
database rather than trusting the token's claim -- see `app/api/deps.py` for
why that matters with a 12-hour token.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import current_admin
from app.db.session import get_db
from app.models.template import Template
from app.models.template_version import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_STATUSES,
    TemplateVersion,
)
from app.models.user import ROLE_ADMIN, ROLES, STATUS_ACTIVE, STATUS_DISABLED, User
from app.notifications.service import notify_decision
from app.schemas.admin import ApprovalOut, ApprovalQueueOut, ApproveIn, RejectIn, RoleIn
from app.schemas.auth import MessageOut, UserOut

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_PAGE_SIZE = 100


def _to_approval_out(
    template: Template,
    version: TemplateVersion,
    submitter: User | None,
    reviewer: User | None,
) -> ApprovalOut:
    return ApprovalOut(
        version_id=version.id,
        template_id=template.id,
        title=template.title,
        original_filename=template.original_filename,
        format=template.format,
        version_number=version.version_number,
        approval_status=version.approval_status,
        size_bytes=version.size_bytes,
        file_hash=version.file_hash,
        purpose=template.purpose,
        category=template.category,
        form_id=template.form_id,
        submitted_by=version.submitted_by,
        submitted_by_name=(submitter.full_name or submitter.username) if submitter else None,
        submitted_by_email=submitter.email if submitter else None,
        reviewed_by_name=(reviewer.full_name or reviewer.username) if reviewer else None,
        reviewed_at=version.reviewed_at,
        review_note=version.review_note,
        submitted_at=version.created_at,
    )


@router.get("/approvals", response_model=ApprovalQueueOut)
def list_approvals(
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(current_admin),
) -> ApprovalQueueOut:
    """The review queue. Defaults to everything, newest first.

    `pending` is counted across the whole queue rather than over the returned
    page, so the badge in the nav stays right when the queue is longer than one
    page.
    """
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page must be >= 1.")
    if not (1 <= page_size <= MAX_PAGE_SIZE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"page_size must be between 1 and {MAX_PAGE_SIZE}.",
        )
    if status_filter is not None and status_filter not in APPROVAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status '{status_filter}'. Use one of {sorted(APPROVAL_STATUSES)}.",
        )

    query = (
        db.query(TemplateVersion, Template)
        .join(Template, Template.id == TemplateVersion.template_id)
        .filter(Template.status != "deleted")
    )
    if status_filter is not None:
        query = query.filter(TemplateVersion.approval_status == status_filter)

    total = query.count()
    rows = (
        query.order_by(TemplateVersion.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    pending = (
        db.query(TemplateVersion)
        .join(Template, Template.id == TemplateVersion.template_id)
        .filter(
            Template.status != "deleted",
            TemplateVersion.approval_status == APPROVAL_PENDING,
        )
        .count()
    )

    # One query for every user mentioned on the page rather than a lookup per
    # row: a fifty-row queue would otherwise be a hundred extra round trips.
    user_ids = {
        user_id
        for version, _template in rows
        for user_id in (version.submitted_by, version.reviewed_by)
        if user_id is not None
    }
    users_by_id: dict[uuid.UUID, User] = {}
    if user_ids:
        users_by_id = {
            user.id: user for user in db.query(User).filter(User.id.in_(user_ids)).all()
        }

    return ApprovalQueueOut(
        items=[
            _to_approval_out(
                template,
                version,
                users_by_id.get(version.submitted_by) if version.submitted_by else None,
                users_by_id.get(version.reviewed_by) if version.reviewed_by else None,
            )
            for version, template in rows
        ],
        pending=pending,
        total=total,
    )


def _load_pending(db: Session, version_id: uuid.UUID) -> tuple[TemplateVersion, Template]:
    version = db.get(TemplateVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    template = db.get(Template, version.template_id)
    if template is None or template.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")
    if version.approval_status != APPROVAL_PENDING:
        # 409 rather than a silent re-approve: two admins opening the queue
        # together should not both believe they made the decision, and the
        # second one needs to know the first already did.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That version was already {version.approval_status}.",
        )
    return version, template


def _decide(
    db: Session,
    version_id: uuid.UUID,
    admin: User,
    *,
    approved: bool,
    note: str | None,
) -> ApprovalOut:
    version, template = _load_pending(db, version_id)

    version.approval_status = APPROVAL_APPROVED if approved else APPROVAL_REJECTED
    version.reviewed_by = admin.id
    version.reviewed_at = datetime.now(timezone.utc)
    version.review_note = note
    db.commit()

    submitter = db.get(User, version.submitted_by) if version.submitted_by else None
    # Commits its own rows, then emails. A failed send does not undo the
    # decision -- see `app/notifications/service.py`.
    notify_decision(
        db,
        recipient=submitter,
        reviewer=admin,
        approved=approved,
        template_title=template.title,
        template_id=template.id,
        version_id=version.id,
        version_number=version.version_number,
        note=note,
    )

    db.refresh(version)
    return _to_approval_out(template, version, submitter, admin)


@router.post("/approvals/{version_id}/approve", response_model=ApprovalOut)
def approve_version(
    version_id: uuid.UUID,
    payload: ApproveIn | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> ApprovalOut:
    """Publish the version and tell its submitter.

    This is what actually puts the template in the library: `GET /templates`
    filters on `approval_status == 'approved'`, so before this call the file is
    stored and ingested but genuinely not listed.
    """
    return _decide(db, version_id, admin, approved=True, note=(payload.note if payload else None))


@router.post("/approvals/{version_id}/reject", response_model=ApprovalOut)
def reject_version(
    version_id: uuid.UUID,
    payload: RejectIn,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> ApprovalOut:
    return _decide(db, version_id, admin, approved=False, note=payload.note.strip())


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(current_admin)) -> list[UserOut]:
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [UserOut.model_validate(user) for user in users]


@router.post("/users/{user_id}/role", response_model=UserOut)
def set_role(
    user_id: uuid.UUID,
    payload: RoleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> UserOut:
    """Promote or demote. An admin cannot demote themselves.

    The self-demotion guard is not politeness: with one admin, demoting
    yourself leaves the hub with nobody who can approve a template and nobody
    who can appoint someone who can -- recoverable only by editing the database
    directly.
    """
    if payload.role not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role '{payload.role}'. Use one of {sorted(ROLES)}.",
        )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.id == admin.id and payload.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own administrator access.",
        )

    target.role = payload.role
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)


@router.post("/users/{user_id}/status", response_model=UserOut)
def set_status(
    user_id: uuid.UUID,
    payload: RoleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
) -> UserOut:
    """Enable or disable an account. Reuses `RoleIn` for its single string.

    Only `active` and `disabled` are settable. `pending` is not: it means "has
    not proved this address yet", and letting an admin push someone back into
    it would suggest a re-verification that nothing sends.
    """
    if payload.role not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status must be '{STATUS_ACTIVE}' or '{STATUS_DISABLED}'.",
        )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.id == admin.id and payload.role == STATUS_DISABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot disable your own account."
        )

    target.status = payload.role
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)


@router.get("/health", response_model=MessageOut)
def admin_health(admin: User = Depends(current_admin)) -> MessageOut:
    """A cheap way for the frontend to confirm a token still carries admin."""
    return MessageOut(message=f"Signed in as {admin.username} (admin).")
