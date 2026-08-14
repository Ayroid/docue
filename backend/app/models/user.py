import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The two roles the product has. `admin` is the reviewer role: it is the only one
# that sees the approval queue and the only one that can act on it.
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)

# `pending` is a real, reachable state, not a transient one: registration
# succeeds before the OTP is entered, so a row exists for an address that has
# not been proved yet. Login refuses it -- otherwise anyone could hold an
# account on a colleague's address by never opening the email.
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class User(Base):
    """A person who can sign in.

    Email is the identity that matters -- it is what OTPs are sent to and what
    approval notifications reach -- so it carries the uniqueness constraint and
    is stored lowercased by the service layer. `username` is a second, equally
    unique handle because the login form accepts either.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        CheckConstraint(
            "status IN ('pending', 'active', 'disabled')", name="ck_users_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stored lowercased (see `normalize_email`); the unique index is therefore a
    # real case-insensitive constraint without needing the citext extension.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # bcrypt output, never the password. Sized for bcrypt's 60-char digest with
    # room for a future algorithm prefix.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_USER, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN
