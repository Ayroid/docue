"""Outbound email, over SMTP when it is configured and to the log when it isn't.

The fallback is the default, and it is not a stub: the whole OTP and approval
flow is exercisable on a fresh checkout with no mail credentials, because every
message that would have been sent is printed in full. Setting `SMTP_HOST` turns
the same calls into real mail with no other change.

**Sending never fails a request.** `send_email` catches everything and reports
a boolean. A registration that stored the user and then raised on a refused
SMTP connection would leave an account nobody can verify and no way to retry
except registering again -- the resend-OTP endpoint exists precisely so a
delivery failure is recoverable, and that only works if the write survives it.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("app.notifications.email")


def _log_message(to: str, subject: str, body: str) -> None:
    logger.info(
        "EMAIL (not sent -- SMTP_HOST unset)\n"
        "  to:      %s\n"
        "  subject: %s\n"
        "  body:\n%s",
        to,
        subject,
        "\n".join(f"    {line}" for line in body.splitlines()),
    )


def send_email(to: str, subject: str, body: str) -> bool:
    """True if it went out over SMTP, False if it was logged or failed.

    The caller uses the result to tell the user "check your inbox" versus
    "ask an admin", never to decide whether the operation succeeded.
    """
    if not settings.email_configured:
        _log_message(to, subject, body)
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception:
        # Logged with the body so a failed delivery is still recoverable by a
        # human reading the server output -- which is the only copy left.
        logger.exception("SMTP delivery to %s failed; message follows", to)
        _log_message(to, subject, body)
        return False

    logger.info("Sent %r to %s", subject, to)
    return True


# ── message bodies ────────────────────────────────────────────────────────
# Plain text on purpose. These go to corporate Outlook, where a hand-rolled
# HTML mail is as likely to be mangled or quarantined as rendered, and every
# one of these messages is four lines of fact.


def send_verification_otp(to: str, name: str, code: str, ttl_minutes: int) -> bool:
    return send_email(
        to,
        "Your Docue verification code",
        f"Hi {name},\n\n"
        f"Your Docue email verification code is:\n\n"
        f"    {code}\n\n"
        f"It expires in {ttl_minutes} minutes. If you did not create a Docue "
        f"account, you can ignore this message.\n\n"
        f"-- Docue, YMSLI\n",
    )


def send_password_reset_otp(to: str, name: str, code: str, ttl_minutes: int) -> bool:
    return send_email(
        to,
        "Your Docue password reset code",
        f"Hi {name},\n\n"
        f"Use this code to reset your Docue password:\n\n"
        f"    {code}\n\n"
        f"It expires in {ttl_minutes} minutes. If you did not ask to reset your "
        f"password, ignore this message -- your current password still works.\n\n"
        f"-- Docue, YMSLI\n",
    )


def send_approval_requested(to: str, admin_name: str, title: str, submitter: str) -> bool:
    return send_email(
        to,
        f"Approval needed: {title}",
        f"Hi {admin_name},\n\n"
        f"{submitter} submitted a template version for approval:\n\n"
        f"    {title}\n\n"
        f"Review it in the Docue admin panel. It is not visible in the "
        f"library until it is approved.\n\n"
        f"-- Docue, YMSLI\n",
    )


def send_template_approved(to: str, name: str, title: str, reviewer: str, note: str | None) -> bool:
    tail = f"\nReviewer's note: {note}\n" if note else ""
    return send_email(
        to,
        f"Approved: {title}",
        f"Hi {name},\n\n"
        f"{reviewer} approved your template:\n\n"
        f"    {title}\n"
        f"{tail}\n"
        f"It is now published in the Docue library.\n\n"
        f"-- Docue, YMSLI\n",
    )


def send_template_rejected(to: str, name: str, title: str, reviewer: str, note: str) -> bool:
    return send_email(
        to,
        f"Rejected: {title}",
        f"Hi {name},\n\n"
        f"{reviewer} reviewed your template and rejected it:\n\n"
        f"    {title}\n\n"
        f"Reason: {note}\n\n"
        f"It has not been published. Upload a corrected version when it is ready.\n\n"
        f"-- Docue, YMSLI\n",
    )
