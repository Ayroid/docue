"""Who is asking, and what they are allowed to do.

**This is a seam with a deliberately short life.** A real auth system exists --
it created `users`, `email_otps` and `notifications` and migrated the shared
database to `0005_auth` -- but at the time of writing its code is not on this
branch, only its schema is. So this module resolves a caller against the *real*
`users` table while getting the caller's identity from a header, and it is the
one place that has to change when the auth branch lands: replace the body of
`get_actor` with that branch's dependency, delete `TRUSTED_HEADERS`, and nothing
in `app/services/promotion.py` moves.

Until then the caller's user id arrives in a header and is **believed**. That is
a genuine hole and it is contained rather than hidden: anyone who can reach the
API can name any user id. `TRUSTED_HEADERS` is the single constant a reviewer
greps to confirm nothing else grants privilege.

Two things this does *not* do, both on purpose:

* **No `User` mapped class.** Defining one here would collide with the auth
  branch's own model the moment the branches meet -- two classes mapped to
  `users` is a configuration error, not a merge conflict a human would notice.
  The row is read with a plain SELECT instead. The foreign keys in `0006` still
  give real referential integrity; only the ORM mapping is skipped.
* **No fabricated fallback user.** An unknown or absent id is anonymous, and
  anonymous cannot promote. Inventing a user to stand in would put a name on an
  approval record that no account is behind.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "ROLE_ADMIN",
    "ROLE_USER",
    "Actor",
    "AdminActor",
    "CurrentActor",
    "get_actor",
    "require_actor",
    "require_admin",
]

# Exactly the two values `ck_users_role` permits. Named here so this codebase
# never spells them as literals and never invents a third.
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# The only headers that confer identity.
TRUSTED_HEADERS = ("X-User-Id",)


@dataclass(frozen=True)
class Actor:
    """The caller. `user_id` is what gets stored; `role` is what decides."""

    user_id: uuid.UUID | None
    username: str
    role: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


ANONYMOUS = Actor(user_id=None, username="anonymous", role=None)


def get_actor(
    db: Annotated[Session, Depends(get_db)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> Actor:
    """The caller, resolved against `users`. Never raises; may be anonymous.

    Endpoints that require somebody take `require_actor` instead. This one
    stays permissive so a read-only route can note who is looking without
    turning a malformed header into a 4xx.
    """
    if not x_user_id:
        return ANONYMOUS
    try:
        user_id = uuid.UUID(x_user_id.strip())
    except ValueError:
        logger.warning("X-User-Id is not a uuid; treating the caller as anonymous")
        return ANONYMOUS

    row = db.execute(
        text(
            "SELECT id, username, role, status FROM users WHERE id = :uid"
        ),
        {"uid": str(user_id)},
    ).first()
    if row is None:
        logger.warning("X-User-Id %s names no account; treating as anonymous", user_id)
        return ANONYMOUS
    if row.status != "active":
        # A disabled account is not a caller. Same answer as no account at all,
        # so a suspended admin cannot approve anything on the way out.
        logger.warning("user %s is %s, not active; treating as anonymous", user_id, row.status)
        return ANONYMOUS

    return Actor(user_id=row.id, username=row.username, role=row.role)


CurrentActor = Annotated[Actor, Depends(get_actor)]


def require_actor(actor: CurrentActor) -> Actor:
    """Refuse anonymous callers. For anything that writes an attributable row."""
    if not actor.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to do that.",
        )
    return actor


def require_admin(actor: CurrentActor) -> Actor:
    """Refuse anyone who is not an admin. For approve/reject only.

    Deliberately *not* applied to `promote`: a non-admin promoting is not an
    error, it is the request path. Guarding that endpoint with this would make
    the whole feature admin-only, which is the opposite of what it is for.
    """
    if not actor.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to do that."
        )
    if not actor.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doc control can decide a promotion request.",
        )
    return actor


AuthedActor = Annotated[Actor, Depends(require_actor)]
AdminActor = Annotated[Actor, Depends(require_admin)]
