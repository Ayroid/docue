"""Writing a notification and emailing the same fact, in one call.

The two always travel together -- the product promise is "on the app *and* by
email" -- so pairing them here is what stops one arriving without the other.

The in-app row is written first and committed, then the mail is attempted. That
order matters: SMTP is the part that can hang or refuse, and a notification the
user can see in the hub is worth more than a symmetrical failure where neither
lands. `send_email` already swallows its own errors, so a dead relay costs the
request nothing.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notification import (
    KIND_APPROVAL_REQUESTED,
    KIND_TEMPLATE_APPROVED,
    KIND_TEMPLATE_REJECTED,
    Notification,
)
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE, User
from app.notifications.email import (
    send_approval_requested,
    send_template_approved,
    send_template_rejected,
)

logger = logging.getLogger("app.notifications")


def display_name(user: User) -> str:
    return user.full_name or user.username


def create_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    template_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
) -> Notification:
    """Add a notification row. The caller owns the commit."""
    notification = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        template_id=template_id,
        version_id=version_id,
    )
    db.add(notification)
    return notification


def active_admins(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.role == ROLE_ADMIN, User.status == STATUS_ACTIVE)
        .order_by(User.created_at)
        .all()
    )


def notify_approval_requested(
    db: Session,
    *,
    submitter: User | None,
    template_title: str,
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    version_number: int,
) -> int:
    """Tell every active admin that something is waiting. Returns how many.

    Zero admins is logged loudly rather than raised: the upload itself is fine
    and the version sits in the queue regardless, but nobody has been told, and
    that is worth a warning in the server log because the fix is to seed an
    admin.
    """
    admins = active_admins(db)
    if not admins:
        logger.warning(
            "Template %s v%s is awaiting approval but there are no active admins to notify.",
            template_id,
            version_number,
        )
        return 0

    submitter_name = display_name(submitter) if submitter else "Someone"
    title = f"Approval needed: {template_title}"
    body = f"{submitter_name} submitted version {version_number} of “{template_title}” for approval."

    for admin in admins:
        create_notification(
            db,
            user_id=admin.id,
            kind=KIND_APPROVAL_REQUESTED,
            title=title,
            body=body,
            template_id=template_id,
            version_id=version_id,
        )
    db.commit()

    for admin in admins:
        send_approval_requested(admin.email, display_name(admin), template_title, submitter_name)
    return len(admins)


def notify_decision(
    db: Session,
    *,
    recipient: User | None,
    reviewer: User,
    approved: bool,
    template_title: str,
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    version_number: int,
    note: str | None,
) -> bool:
    """Tell the submitter what was decided. False if there is nobody to tell.

    A template uploaded before accounts existed has no submitter, and one whose
    uploader was deleted has a null `submitted_by`. Both are real states, and
    neither should stop an admin approving the template.
    """
    if recipient is None:
        logger.info(
            "Version %s was %s but has no submitter to notify.",
            version_id,
            "approved" if approved else "rejected",
        )
        return False

    reviewer_name = display_name(reviewer)
    if approved:
        title = f"Approved: {template_title}"
        body = (
            f"{reviewer_name} approved version {version_number} of “{template_title}”. "
            f"It is now published in the library."
        )
        if note:
            body += f" Note: {note}"
    else:
        title = f"Changes requested: {template_title}"
        body = (
            f"{reviewer_name} asked for changes to version {version_number} of "
            f"“{template_title}”. Note: {note}"
        )

    create_notification(
        db,
        user_id=recipient.id,
        kind=KIND_TEMPLATE_APPROVED if approved else KIND_TEMPLATE_REJECTED,
        title=title,
        body=body,
        template_id=template_id,
        version_id=version_id,
    )
    db.commit()

    if approved:
        send_template_approved(
            recipient.email, display_name(recipient), template_title, reviewer_name, note
        )
    else:
        send_template_rejected(
            recipient.email, display_name(recipient), template_title, reviewer_name, note or ""
        )
    return True


def mark_read(db: Session, notification: Notification) -> None:
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
