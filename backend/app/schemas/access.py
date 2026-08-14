"""Request and response shapes for template access administration."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class GrantOut(BaseModel):
    """One person's access to one restricted template.

    Carries the recipient's email and name rather than only `user_id`: the share
    dialog is a list of people, and a UUID is not a person. `granted_by_name`
    likewise -- "who let them in" is the first question anyone asks of an access
    list, and answering it from a second request would make the dialog render in
    two stages.
    """

    user_id: uuid.UUID
    email: EmailStr
    username: str
    full_name: str | None = None
    # Present so the UI can warn that a grant is not yet usable: a person who
    # has registered but not verified their address cannot sign in, and a share
    # that appears to work but does not is worse than a refused one.
    user_status: str
    permission: str
    granted_by: uuid.UUID | None = None
    granted_by_name: str | None = None
    granted_at: datetime
    expires_at: datetime | None = None
    # Derived, not stored. An expired grant is kept and shown as expired rather
    # than hidden, so an admin can see why someone lost access.
    expired: bool = False


class TemplateAccessOut(BaseModel):
    """Everything the share dialog needs, in one response."""

    template_id: uuid.UUID
    title: str
    visibility: str
    owner_id: uuid.UUID | None = None
    owner_email: EmailStr | None = None
    # Always returned, even when `visibility` is 'public' and they therefore
    # grant nothing. Rows kept through a public/restricted round trip are the
    # reason: an admin who restricts, shares, un-restricts and re-restricts
    # should not have to rebuild the list.
    grants: list[GrantOut] = Field(default_factory=list)


class VisibilityIn(BaseModel):
    visibility: str


class GrantIn(BaseModel):
    """Share with one registered address.

    Email rather than `user_id`, because that is what an admin knows and what
    the product promised -- "provide access to any user on their registered
    email". An address with no account is refused rather than stored as a
    pending invitation: nothing in this product sends one, and a grant waiting
    on a registration that never happens looks identical to a grant that works.
    """

    email: EmailStr
    permission: str = "view"
    expires_at: datetime | None = None
