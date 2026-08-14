"""Registration, email verification, sign-in and password reset.

Two rules run through every handler here and are worth stating once:

**Nothing tells an anonymous caller whether an address is registered.**
`/forgot-password` answers the same 202 for an unknown email as for a known
one, and `/login` gives one message for a bad username and a bad password
alike. Otherwise these endpoints are a membership oracle for the whole company
directory.

**A code proves one thing only.** Verification and reset codes are separate
`purpose` rows, so a code mailed to confirm an address cannot be posted to the
reset endpoint to take the account over.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.otp import OtpError, issue_otp, redeem_otp
from app.core.security import (
    create_access_token,
    hash_password,
    normalize_email,
    normalize_username,
    password_problem,
    username_problem,
    verify_password,
)
from app.db.session import get_db
from app.models.email_otp import (
    OTP_TTL_MINUTES,
    PURPOSE_EMAIL_VERIFICATION,
    PURPOSE_PASSWORD_RESET,
    PURPOSES,
)
from app.models.user import ROLE_USER, STATUS_ACTIVE, STATUS_PENDING, User
from app.notifications.email import send_password_reset_otp, send_verification_otp
from app.notifications.service import display_name
from app.api.deps import current_user
from app.schemas.auth import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    MessageOut,
    OtpSentOut,
    RegisterIn,
    ResendOtpIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
    VerifyEmailIn,
)

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Said to anyone who asks for a reset, whether or not the address exists.
RESET_ACK = "If that address has an account, a reset code is on its way."


def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == normalize_email(email)).one_or_none()


def _otp_response(message: str, email: str, code: str, expires_at, sent: bool) -> OtpSentOut:
    return OtpSentOut(
        message=message,
        email=email,
        expires_at=expires_at,
        email_sent=sent,
        debug_code=code if settings.expose_otp_in_response else None,
    )


def _token_response(db: Session, user: User) -> TokenOut:
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return TokenOut(
        access_token=create_access_token(user.id, user.role, user.email),
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=OtpSentOut, status_code=status.HTTP_202_ACCEPTED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> OtpSentOut:
    """Create a `pending` account and mail it a verification code.

    The account exists immediately but cannot sign in until the code is
    entered. 202 rather than 201 because registration is not finished when this
    returns -- the caller's next step is `/verify-email`.
    """
    email = normalize_email(payload.email)
    username = normalize_username(payload.username)

    if (problem := username_problem(username)) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    if (problem := password_problem(payload.password)) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

    existing = (
        db.query(User).filter(or_(User.email == email, User.username == username)).first()
    )
    if existing is not None:
        # A registration form is not an anonymous endpoint in the way
        # `/forgot-password` is -- the person is choosing a handle and has to be
        # told it is taken, or they cannot proceed. What is withheld is *which*
        # account: "email" versus "username" is said, the rest is not.
        field = "email address" if existing.email == email else "username"
        if existing.email == email and existing.status == STATUS_PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email is already registered but not verified. Request a new code from the verification screen.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"That {field} is already registered."
        )

    user = User(
        email=email,
        username=username,
        full_name=(payload.full_name or "").strip() or None,
        password_hash=hash_password(payload.password),
        role=ROLE_USER,
        status=STATUS_PENDING,
    )
    db.add(user)
    try:
        db.flush()  # users row must exist before email_otps.user_id can reference it
        issued = issue_otp(db, user.id, PURPOSE_EMAIL_VERIFICATION)
        db.commit()
    except IntegrityError as exc:
        # Two registrations racing on the same address: the unique index is the
        # real arbiter, and the loser gets the same 409 as the check above.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email or username is already registered."
        ) from exc

    sent = send_verification_otp(email, display_name(user), issued.code, OTP_TTL_MINUTES)
    return _otp_response(
        "Account created. Enter the code we sent to your email to finish signing up.",
        email,
        issued.code,
        issued.expires_at,
        sent,
    )


@router.post("/verify-email", response_model=TokenOut)
def verify_email(payload: VerifyEmailIn, db: Session = Depends(get_db)) -> TokenOut:
    """Redeem a verification code and sign the user straight in.

    Returning a token here rather than bouncing to the login form is
    deliberate: the person has just proved both the password (at registration)
    and the address, so asking them to type the password again proves nothing.
    """
    user = _find_user_by_email(db, payload.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No pending account for that address."
        )
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already verified. Sign in."
        )

    try:
        redeem_otp(db, user.id, PURPOSE_EMAIL_VERIFICATION, payload.code)
    except OtpError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    # Only lift a `pending` account. A `disabled` one that still had an
    # outstanding code must not verify its way back in.
    if user.status == STATUS_PENDING:
        user.status = STATUS_ACTIVE
    db.commit()

    if user.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verified, but this account is not active. Contact doc control.",
        )
    return _token_response(db, user)


@router.post("/resend-otp", response_model=OtpSentOut, status_code=status.HTTP_202_ACCEPTED)
def resend_otp(payload: ResendOtpIn, db: Session = Depends(get_db)) -> OtpSentOut:
    if payload.purpose not in PURPOSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown purpose. Use one of {sorted(PURPOSES)}.",
        )

    user = _find_user_by_email(db, payload.email)
    email = normalize_email(payload.email)

    # An unknown address, or a verified one asking to re-verify, gets the same
    # shaped answer as the real thing -- with no code issued. This endpoint is
    # reachable anonymously, so a distinguishable response would leak who has
    # an account.
    if user is None or (
        payload.purpose == PURPOSE_EMAIL_VERIFICATION and user.email_verified
    ):
        return OtpSentOut(
            message="If that address needs a code, one is on its way.",
            email=email,
            expires_at=datetime.now(timezone.utc),
            email_sent=False,
            debug_code=None,
        )

    issued = issue_otp(db, user.id, payload.purpose)
    db.commit()

    if payload.purpose == PURPOSE_EMAIL_VERIFICATION:
        sent = send_verification_otp(user.email, display_name(user), issued.code, OTP_TTL_MINUTES)
    else:
        sent = send_password_reset_otp(user.email, display_name(user), issued.code, OTP_TTL_MINUTES)

    return _otp_response("A new code is on its way.", user.email, issued.code, issued.expires_at, sent)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    """Sign in with either the username or the email address.

    The password is verified even when no user matched, against a throwaway
    hash. Skipping it would make a miss measurably faster than a hit -- bcrypt
    is ~100ms and the difference is trivially observable -- turning this into
    the account oracle the generic error message is there to prevent.
    """
    identifier = payload.identifier.strip()
    user = (
        db.query(User)
        .filter(
            or_(
                User.email == normalize_email(identifier),
                User.username == normalize_username(identifier),
            )
        )
        .one_or_none()
    )

    if user is None:
        verify_password(payload.password, hash_password("timing-equaliser"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password."
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password."
        )

    # Past the password, so the caller has proved they own the account and can
    # be told exactly what is wrong with it.
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email address before signing in.",
        )
    if user.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active. Contact doc control.",
        )

    return _token_response(db, user)


@router.post("/forgot-password", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)) -> MessageOut:
    """Mail a reset code. Always 202, whether or not the address is known.

    Unlike the other OTP endpoints this one returns no `debug_code` even
    locally: the response shape must not vary with whether the account exists,
    and a field that is present for real users and absent for made-up ones is
    exactly the oracle this is avoiding. The code is in the server log.
    """
    user = _find_user_by_email(db, payload.email)
    if user is None:
        logger.info("Password reset requested for unknown address %s", normalize_email(payload.email))
        return MessageOut(message=RESET_ACK)

    issued = issue_otp(db, user.id, PURPOSE_PASSWORD_RESET)
    db.commit()
    send_password_reset_otp(user.email, display_name(user), issued.code, OTP_TTL_MINUTES)
    return MessageOut(message=RESET_ACK)


@router.post("/reset-password", response_model=MessageOut)
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)) -> MessageOut:
    """Set a new password against a reset code.

    A successful reset also verifies the address: the person just proved they
    read mail sent to it, which is the same proof `/verify-email` asks for. It
    does not lift a `disabled` account -- only `pending`.
    """
    if (problem := password_problem(payload.new_password)) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

    user = _find_user_by_email(db, payload.email)
    if user is None:
        # No code can exist for an address with no account, so this is the same
        # answer a wrong code gets -- it reveals nothing the attempt did not.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That code is not valid. Request a new one."
        )

    try:
        redeem_otp(db, user.id, PURPOSE_PASSWORD_RESET, payload.code)
    except OtpError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user.password_hash = hash_password(payload.new_password)
    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
    if user.status == STATUS_PENDING:
        user.status = STATUS_ACTIVE
    db.commit()

    return MessageOut(message="Password updated. Sign in with your new password.")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password", response_model=MessageOut)
def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect."
        )
    if (problem := password_problem(payload.new_password)) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return MessageOut(message="Password updated.")
