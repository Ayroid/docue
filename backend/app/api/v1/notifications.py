"""The signed-in user's own notifications.

Every route scopes on `Notification.user_id == user.id`. That filter, not the
route shape, is what stops one person reading another's queue -- an id in the
path is never enough on its own.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.notifications.service import mark_read
from app.schemas.auth import MessageOut
from app.schemas.notification import NotificationListOut, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

MAX_PAGE_SIZE = 100


@router.get("", response_model=NotificationListOut)
def list_notifications(
    unread_only: bool = False,
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationListOut:
    if not (1 <= limit <= MAX_PAGE_SIZE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"limit must be between 1 and {MAX_PAGE_SIZE}.",
        )

    base = db.query(Notification).filter(Notification.user_id == user.id)

    # Counted with their own queries rather than from `items`: the list is
    # capped by `limit`, so a badge derived from it would stop counting at 30.
    total = base.count()
    unread = base.filter(Notification.read_at.is_(None)).count()

    listing = base.filter(Notification.read_at.is_(None)) if unread_only else base
    items = listing.order_by(Notification.created_at.desc()).limit(limit).all()

    return NotificationListOut(
        items=[NotificationOut.model_validate(item) for item in items],
        unread=unread,
        total=total,
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationOut:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .one_or_none()
    )
    # 404 rather than 403 for someone else's notification: distinguishing the
    # two confirms the id exists, which is a small oracle for nothing gained.
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")

    mark_read(db, notification)
    db.commit()
    db.refresh(notification)
    return NotificationOut.model_validate(notification)


@router.post("/read-all", response_model=MessageOut)
def read_all(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageOut:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: func.now()}, synchronize_session=False)
    )
    db.commit()
    return MessageOut(message=f"Marked {updated} notification{'s' if updated != 1 else ''} as read.")
