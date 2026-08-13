import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TemplateVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    storage_bucket: str
    storage_key: str
    size_bytes: int
    mime_type: str
    file_hash: str
    upload_status: str
    created_at: datetime


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    format: str
    status: str
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    current_version: TemplateVersionOut | None = None
