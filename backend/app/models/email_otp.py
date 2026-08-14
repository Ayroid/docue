import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# What the code proves. Kept separate so a verification code cannot be replayed
# against the password-reset endpoint: both are six digits sent to the same
# address, and only the purpose distinguishes them.
PURPOSE_EMAIL_VERIFICATION = "email_verification"
PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSES = (PURPOSE_EMAIL_VERIFICATION, PURPOSE_PASSWORD_RESET)

# Short enough that a stolen mailbox has a small window, long enough that a
# corporate mail relay's delay doesn't expire the code before it arrives.
OTP_TTL_MINUTES = 10
# A six-digit code has a million values; five guesses keeps online brute force
# at 5-in-a-million per issued code, and issuing a new code resets the counter
# rather than extending the budget.
OTP_MAX_ATTEMPTS = 5


class EmailOtp(Base):
    """A one-time code emailed to a user, stored only as a hash.

    The plaintext code exists in exactly two places: the email, and the
    response of the send endpoint when `otp_debug` is on for local work. It is
    never persisted -- a database dump therefore cannot be used to verify
    anyone's email or reset anyone's password.

    Codes are consumed rather than deleted so that "this code was already used"
    is distinguishable from "this code never existed", which is what lets the
    verify endpoints give an honest error instead of a generic one.
    """

    __tablename__ = "email_otps"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')", name="ck_email_otps_purpose"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # sha256 of the code. Not bcrypt: the input is six digits from a CSPRNG with
    # a ten-minute life and a five-attempt cap, so the slow-hash property buys
    # nothing here, and verification happens on a request path.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
