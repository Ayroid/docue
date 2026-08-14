"""Request dependencies that resolve the caller.

Three levels, and the difference between them is the whole authorisation model:

* `current_user` -- signed in and active. 401 otherwise.
* `current_admin` -- the above, plus the admin role. 403 otherwise.
* `optional_user` -- the caller if there is one, else None, for routes that
  serve both.

The role is re-read from the database on every request rather than trusted from
the token. The token carries `role` so the frontend can render without a second
call, but a user demoted an hour ago still holds a valid token for eleven more,
and authorising off that claim would let them keep approving templates until it
expired.
"""

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE, User

# `auto_error=False` so a missing header reaches our own handler and comes back
# as the 401 message the frontend shows, rather than FastAPI's bare
# "Not authenticated".
bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not signed in.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _user_from_token(token: str, db: Session) -> User:
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = claims.get("sub")
    try:
        user_id = uuid.UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise CREDENTIALS_EXCEPTION from exc

    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_EXCEPTION
    if user.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active. Contact doc control.",
        )
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION
    return _user_from_token(credentials.credentials, db)


def current_admin(user: User = Depends(current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The caller, if they presented a usable token.

    Reads the header directly instead of depending on `bearer_scheme`, so that
    a *malformed* Authorization header is treated as anonymous rather than as
    an error. This is used by routes that must keep working for signed-out
    visitors, where a broken token should degrade to "not signed in".
    """
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return _user_from_token(token, db)
    except HTTPException:
        return None
