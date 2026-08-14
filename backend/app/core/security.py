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
# The only rule, and the only one worth having -- see `password_problem`.
MIN_PASSWORD_LENGTH = 8

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 64

# Letters, digits, dot, dash, underscore. **`@` is deliberately excluded**, and
# that is a correctness constraint rather than tidiness: `/auth/login` takes one
# `identifier` and resolves it against the email *or* the username, so a
# username containing `@` could equal somebody else's email address and two
# accounts would answer to one login string. Keeping the two character sets
# disjoint is what makes that lookup unambiguous.
USERNAME_ALLOWED_RE = re.compile(r"^[a-z0-9._-]+$")


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

    **Length only, deliberately.** There were composition rules here -- upper
    and lower case, at least one digit -- and they are gone. NIST SP 800-63B
    advises against exactly those: they do not measurably raise the cost of an
    attack, because people satisfy them the same predictable way. `Password1`
    passes every one of them and is in the first thousand entries of any
    wordlist, while `correct horse battery staple` failed two of them. What
    actually resists guessing is length, so that is what is checked.

    Returns a message rather than raising so both the register and the reset
    path can surface it as a 422 with the same wording.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
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
    """The reason this username is unusable, or None if it is fine.

    One message per distinct problem, naming the offending characters. The
    single combined sentence this replaced ("must be 3-64 characters, using
    letters, digits, dot, dash or underscore") was accurate and useless: the two
    inputs people actually type here are their email address and their full
    name, and neither reader could tell from that sentence which half they had
    broken -- the length or the character set.
    """
    candidate = normalize_username(username)

    if len(candidate) < MIN_USERNAME_LENGTH:
        return f"Username must be at least {MIN_USERNAME_LENGTH} characters."
    if len(candidate) > MAX_USERNAME_LENGTH:
        return f"Username must be at most {MAX_USERNAME_LENGTH} characters."

    if not USERNAME_ALLOWED_RE.match(candidate):
        bad = sorted({character for character in candidate if not USERNAME_ALLOWED_RE.match(character)})
        shown = ", ".join("a space" if character == " " else f"'{character}'" for character in bad)
        if "@" in bad:
            return (
                f"Username cannot contain {shown}. Use your name rather than your "
                "email address -- you can sign in with either."
            )
        return f"Username cannot contain {shown}. Use letters, digits, dot, dash or underscore."
    return None


def suggest_username(email: str) -> str:
    """A usable username derived from an email address.

    Used to prefill the field so the common path needs no thought. Everything
    outside the allowed set collapses to a dot rather than being dropped, so
    `riya mehta@ymsli.com` suggests `riya.mehta` instead of `riyamehta` -- the
    word boundary is information and silently deleting it makes the suggestion
    harder to read than the name it came from.
    """
    local = normalize_email(email).split("@", 1)[0]
    collapsed = re.sub(r"[^a-z0-9._-]+", ".", local).strip("._-")
    # Runs of separators read as a typo in a prefilled field.
    collapsed = re.sub(r"\.{2,}", ".", collapsed)
    return collapsed[:MAX_USERNAME_LENGTH]


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
