"""Issuing and redeeming email one-time codes.

The rules live here rather than in the routes because email verification and
password reset need exactly the same ones, and two copies would drift: it is
the resend path that quietly stops invalidating old codes, or the reset path
that forgets the attempt cap.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import generate_otp, hash_otp, otp_expiry, verify_otp
from app.models.email_otp import OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES, EmailOtp


@dataclass(frozen=True)
class IssuedOtp:
    code: str
    expires_at: datetime


def issue_otp(db: Session, user_id: uuid.UUID, purpose: str) -> IssuedOtp:
    """Mint a code, invalidating any earlier unused one for the same purpose.

    Invalidating first is what makes "resend" mean resend rather than "add
    another valid code". Without it, every resend widens the set of codes that
    open the account, and the attempt cap is per row -- so five resends would
    quietly buy twenty-five guesses.

    The caller commits: issuing is always part of a larger unit of work
    (registering a user, starting a reset), and a code committed separately
    from the thing it belongs to can outlive a rollback of it.
    """
    now = datetime.now(timezone.utc)
    (
        db.query(EmailOtp)
        .filter(
            EmailOtp.user_id == user_id,
            EmailOtp.purpose == purpose,
            EmailOtp.consumed_at.is_(None),
        )
        .update({EmailOtp.consumed_at: now}, synchronize_session=False)
    )

    code = generate_otp()
    expires_at = otp_expiry(OTP_TTL_MINUTES)
    db.add(
        EmailOtp(
            user_id=user_id,
            purpose=purpose,
            code_hash=hash_otp(code),
            expires_at=expires_at,
        )
    )
    return IssuedOtp(code=code, expires_at=expires_at)


class OtpError(Exception):
    """A code that cannot be redeemed, with a message meant for the user."""


def redeem_otp(db: Session, user_id: uuid.UUID, purpose: str, code: str) -> None:
    """Consume the user's outstanding code, or raise `OtpError`.

    A wrong guess increments `attempts` and is committed even though the
    request fails -- otherwise the cap counts nothing, since the caller's
    rollback would erase every miss.

    Expiry is compared against a timezone-aware `now`. The column is
    `timestamptz`, but psycopg hands back naive datetimes on some driver
    versions, so the value is coerced rather than trusted; comparing a naive to
    an aware datetime raises `TypeError`, which would read as a 500 on a
    perfectly ordinary expired code.
    """
    now = datetime.now(timezone.utc)
    record = (
        db.query(EmailOtp)
        .filter(
            EmailOtp.user_id == user_id,
            EmailOtp.purpose == purpose,
            EmailOtp.consumed_at.is_(None),
        )
        .order_by(EmailOtp.created_at.desc())
        .first()
    )
    if record is None:
        raise OtpError("No active code. Request a new one.")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        record.consumed_at = now
        db.commit()
        raise OtpError("That code has expired. Request a new one.")

    if record.attempts >= OTP_MAX_ATTEMPTS:
        record.consumed_at = now
        db.commit()
        raise OtpError("Too many incorrect attempts. Request a new code.")

    if not verify_otp(code.strip(), record.code_hash):
        record.attempts += 1
        remaining = OTP_MAX_ATTEMPTS - record.attempts
        db.commit()
        if remaining <= 0:
            raise OtpError("Incorrect code. Request a new one.")
        raise OtpError(f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} left.")

    record.consumed_at = now
