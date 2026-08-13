import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestionAccepted(BaseModel):
    """The 202 body for `POST /templates`.

    Contract C6: async work answers with a job id, never with the finished
    result. Ingestion takes 15-40s, so the alternative is a request that blocks
    for most of a minute and a frontend with nothing to show while it does.

    Deliberately just these four fields. The template's own detail is a `GET
    /templates/{id}` away and duplicating it here would give Track C two shapes
    to keep in step.
    """

    template_id: uuid.UUID
    version_id: uuid.UUID
    job_id: uuid.UUID
    status: str = Field(description="Always 'ingesting' -- the job has been queued.")


class EnrichmentOut(BaseModel):
    """What the AI half of ingestion produced, for the same poll.

    Separate from the structural fields above because it can legitimately be
    `null` on a succeeded job: enrichment runs after the structural result is
    committed and is not allowed to fail it, so a Bedrock outage leaves a
    perfectly good template that simply is not searchable by meaning yet. A
    frontend should render this section as pending rather than as an error.
    """

    model_config = ConfigDict(from_attributes=True)

    enrichment_version: str
    model_id: str
    classifier_prompt: str
    metadata_prompt: str
    regions_labelled: int
    regions_write_refused: int = Field(
        description="Regions the model judged should not be written by a generation agent."
    )
    metadata_generated: bool = Field(
        description="False when the model call failed and the filename was used instead."
    )
    embedded: bool = Field(description="Whether the template is findable by semantic search.")
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    elapsed_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)


class JobStatusOut(BaseModel):
    """What `GET /templates/{id}/ingestion/{job_id}` returns, for polling.

    Everything below `progress` is null until the job succeeds, so a poller can
    render a progress bar from the first response and the result from the last
    one without special-casing anything in between.
    """

    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    kind: str
    status: str = Field(description="queued | running | succeeded | failed")
    stage: str | None = Field(
        default=None,
        description="fingerprint | detect | harvest | verify | persist | enrich | done",
    )
    progress: int = Field(ge=0, le=100)
    error: str | None = None

    # Populated on success.
    fingerprint: dict[str, Any] | None = Field(
        default=None,
        description="Package fingerprint of the ingested bytes, `package_parts` included.",
    )
    pipeline_version: str | None = None
    detector_version: str | None = Field(
        default=None, description="Which detector produced this schema, for drift and re-ingest."
    )
    regions_detected: int | None = None
    regions_writable: int | None = None
    counts_by_kind: dict[str, int] | None = None
    containers: list[str] | None = Field(
        default=None, description="Sheet or slide names the regions are grouped into."
    )
    house_pattern_matched: str | None = None
    form_id: str | None = None
    in_doc_version: str | None = Field(
        default=None, description="The `Ver.` the document claims about itself."
    )
    harvest_source: dict[str, Any] | str | None = Field(
        default=None, description="Where each harvested value was read from, for provenance."
    )
    region_ids_stable: bool | None = None
    enrichment: EnrichmentOut | None = Field(
        default=None,
        description="Semantic labels, discovery metadata and the embedding. Null while "
        "pending, and also when the model call failed -- the template is still usable.",
    )
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int | None = None

    created_at: datetime
    updated_at: datetime


class RegionOut(BaseModel):
    """One persisted region. Field-for-field the detector's `Region` (C3)."""

    model_config = ConfigDict(from_attributes=True)

    region_id: str
    kind: str
    label: str | None = None
    semantic_role: str | None = None
    value_type: str | None = None
    locator: dict[str, Any] = Field(
        description="Polymorphic: {sheet, ref} | {para_index, run_span} | {slide_index, shape_id}."
    )
    current_content: str | None = None
    editable: bool
    protected: bool
    required: bool
    detection_method: str
    question_group: int | None = None
    ordinal: int = Field(
        description="The detector's own numbering. Restarts per sheet; not a total order."
    )
    sequence: int = Field(description="Position within the whole document. Sort by this.")
    notes: dict[str, Any] | None = Field(
        default=None,
        description=(
            "What the compiler needs to act on the region: a table's `columns` and "
            "`template_row`, a block's `insert_at_row`, a caption's count template."
        ),
    )


class DocumentSchemaOut(BaseModel):
    """The persisted Document Schema for one version."""

    template_id: uuid.UUID
    version_id: uuid.UUID
    format: str
    detector_version: str
    regions_detected: int
    regions_writable: int
    counts_by_kind: dict[str, int]
    form_id: str | None = None
    house_pattern: str | None = None
    in_doc_version: str | None = None
    created_at: datetime
    regions: list[RegionOut]
