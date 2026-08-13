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
    # Harvested during ingestion: the `Ver.` the document declares about itself.
    # Comparing it to `version_number` is drift detection with no diffing.
    in_doc_version: str | None = None
    created_at: datetime

    # The fingerprint is deliberately *not* here. It carries the full
    # `package_parts` list, and this schema is embedded in every item of
    # `GET /templates`; it is served by the ingestion and regions endpoints
    # instead, where a caller has asked for one document.


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    format: str
    status: str
    # Both harvested from the document during ingestion, so both are null until
    # the ingestion job succeeds. `form_id` is YMSLI's own identifier for the
    # form ("YMSLI-F-MOM"); `house_pattern` records which house shape it follows.
    form_id: str | None = None
    house_pattern: str | None = None
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    current_version: TemplateVersionOut | None = None
