import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Who each kind is for: the first goes to every admin, the other two go to the
# person who submitted the template.
KIND_APPROVAL_REQUESTED = "approval_requested"
KIND_TEMPLATE_APPROVED = "template_approved"
KIND_TEMPLATE_REJECTED = "template_rejected"
KINDS = (KIND_APPROVAL_REQUESTED, KIND_TEMPLATE_APPROVED, KIND_TEMPLATE_REJECTED)


class Notification(Base):
    """One in-app message for one user.

    A row per recipient rather than one row fanned out at read time: an admin
    who reads an approval request should not mark it read for every other
    admin, and `read_at` is per person. Five admins therefore means five rows,
    which is the point.

    The message text is written at creation time instead of being rendered from
    the template on read. A notification is a record of what was said when it
    was sent -- if the template is later renamed or deleted, the notification
    should still read the way it did when it arrived, and it should still
    render at all.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Not foreign keys: a notification outlives what it refers to, exactly as
    # `jobs.entity_id` does. Deleting a template should not delete the record
    # that it was once approved.
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False, index=True)
