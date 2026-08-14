import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str
    full_name: str | None = None
    role: str
    status: str
    email_verified: bool
    created_at: datetime

    # `password_hash` is deliberately absent, and this schema is the only thing
    # any route returns a user through -- which is what guarantees it cannot
    # leak by someone returning the ORM object directly.


class RegisterIn(BaseModel):
    email: EmailStr
    # Optional: omit it and one is derived from the email address. The length
    # and character rules are deliberately *not* declared here -- they live in
    # `security.username_problem`, which explains which rule was broken and
    # why. Pydantic's own "String should have at least 3 characters" would
    # otherwise win the race and say less.
    username: str | None = None
    password: str = Field(min_length=8)
    full_name: str | None = Field(default=None, max_length=160)


class OtpSentOut(BaseModel):
    """The answer to anything that sends a code.

    `email_sent` distinguishes "check your inbox" from "the server logged it",
    so the UI can tell a tester where to look instead of claiming mail was sent
    when SMTP is unconfigured.

    `debug_code` is populated only when `settings.expose_otp_in_response` is
    true -- local, non-production, no SMTP. It is how the flow is testable
    without a mailbox, and it is null everywhere else.
    """

    message: str
    email: EmailStr
    expires_at: datetime
    email_sent: bool
    debug_code: str | None = None


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class ResendOtpIn(BaseModel):
    email: EmailStr
    # 'email_verification' | 'password_reset'
    purpose: str = "email_verification"


class LoginIn(BaseModel):
    # Either the username or the email address -- the form has one field and
    # the server works out which it got.
    identifier: str = Field(min_length=3, max_length=320)
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=8)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class MessageOut(BaseModel):
    message: str
