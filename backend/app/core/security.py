"""Password hashing, access tokens and one-time codes.

Everything here is pure: it takes values and returns values, touching neither
the database nor the request. That is what lets the OTP and token rules be
tested without a server, and it keeps the policy decisions (how long a code
lives, what a token carries) in one readable place instead of scattered across
the route handlers that enforce them.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt hashes at most 72 bytes and *silently truncates* beyond that, so a
# 200-character passphrase would be no stronger than its first 72 bytes. Passing
# a longer password raises in bcrypt 5, so the limit is enforced at validation
# time with a message that says so rather than surfacing as a 500.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")


# ── passwords ─────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check that never raises.

    A malformed or truncated hash in the database is a failed login, not a 500:
    bcrypt raises `ValueError` on a hash it cannot parse, and letting that
    escape would turn one corrupt row into an unhandled error on every attempt.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """The reason this password is unusable, or None if it is fine.

    Returns a message rather than raising so both the register and the reset
    path can surface it as a 422 with the same wording.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
    if password.lower() == password or password.upper() == password:
        return "Password must contain both upper and lower case letters."
    if not any(character.isdigit() for character in password):
        return "Password must contain at least one digit."
    return None


# ── identifiers ───────────────────────────────────────────────────────────


def normalize_email(email: str) -> str:
    """Lowercased and stripped.

    Applied on every write *and* every lookup, which is what makes the plain
    unique index on `users.email` a real case-insensitive constraint --
    `Riya@ymsli.com` and `riya@ymsli.com` cannot both register.
    """
    return email.strip().lower()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.match(username.strip()):
        return "Username must be 3-64 characters, using letters, digits, dot, dash or underscore."
    return None


# ── one-time codes ────────────────────────────────────────────────────────


def generate_otp() -> str:
    """A six-digit code from the system CSPRNG.

    `secrets.randbelow` rather than `random`: the latter is a Mersenne Twister
    seeded predictably enough that observing a few codes reveals the rest, and
    these codes are the only thing standing in front of a password reset.
    Leading zeros are kept -- `042917` is a valid code and zero-padding is what
    keeps all million values reachable.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_otp(code: str, code_hash: str) -> bool:
    """Compared with `compare_digest` so a wrong code takes the same time.

    A plain `==` on hex strings leaks how many leading characters matched, and
    with five attempts per code and unlimited re-sends that is enough of a
    signal to be worth removing.
    """
    return hmac.compare_digest(hash_otp(code), code_hash)


def otp_expiry(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# ── access tokens ─────────────────────────────────────────────────────────


def create_access_token(user_id: uuid.UUID, role: str, email: str) -> str:
    """A signed JWT carrying the claims the API authorises against.

    `role` is in the token so the admin dependency does not need a database
    round trip on every request -- with the cost that a demotion only takes
    effect when the token expires. That is the deliberate trade for a 12-hour
    token; the admin routes re-read the user row anyway, so a demoted admin is
    still refused there.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Raised for any token that cannot be trusted, expired or otherwise."""


def decode_access_token(token: str) -> dict:
    """Verified claims, or `TokenError`.

    `algorithms` is pinned to the configured one. Accepting the token's own
    `alg` is the classic JWT forgery: a caller sends `alg: none`, or signs with
    HMAC against a public key, and the library obligingly agrees.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid session token.") from exc
