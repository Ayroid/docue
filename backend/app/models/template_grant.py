import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# What a grant lets someone do. `VIEW` is the whole product today: find the
# template, open it, generate from it. `MANAGE` is defined but not yet consulted
# by any route -- it exists so that "can re-share this" becomes a value change
# rather than a constraint migration on a live table.
PERMISSION_VIEW = "view"
PERMISSION_MANAGE = "manage"
PERMISSIONS = (PERMISSION_VIEW, PERMISSION_MANAGE)


class TemplateGrant(Base):
    """One person's access to one restricted template.

    Only consulted when the template's `visibility` is `restricted`; a `public`
    template needs no rows here and never gets them, which is what keeps the
    table proportional to the exceptions rather than to users x templates.

    **A grant is not the only way in.** The template's owner and any admin reach
    it without a row, for the same reason they always could -- an owner locked
    out of their own upload by restricting it would be a trap, and an admin who
    cannot open a document cannot review it. `app.access.templates` is where
    those paths are spelled out; this table is only the explicit half.
    """

    __tablename__ = "template_grants"
    __table_args__ = (
        CheckConstraint("permission IN ('view', 'manage')", name="ck_template_grants_permission"),
        UniqueConstraint("template_id", "user_id", name="uq_template_grants_template_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PERMISSION_VIEW, server_default=PERMISSION_VIEW
    )
    # Nullable so that deleting the admin who shared a template does not cascade
    # away everyone's access. "We no longer know who granted this" is a better
    # state than a hub that silently un-shares itself.
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # Null means "no end date", which is the ordinary case. Every read path
    # checks it, so an expired grant stops working without anyone sweeping the
    # table.
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
