import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    template_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListOut(BaseModel):
    """The bell's entire payload in one call.

    `unread` is counted server-side rather than derived from `items`, because
    the list is paginated and a badge computed from the first page would be
    wrong the moment there were more unread than fit in it.
    """

    items: list[NotificationOut]
    unread: int
    total: int
