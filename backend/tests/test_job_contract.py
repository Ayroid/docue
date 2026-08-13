"""Everything a job records must be reachable through the API.

The job-status route flattens the job's stored summary into named fields on
`JobStatusOut`. That is a good shape for the frontend and a silent trap for the
backend: a key added to `job_result()` is written to the database and then
dropped on the way out, with no error anywhere. It cost us exactly once --
the enrichment block was persisted for a while and invisible to every client,
so Track C had no way to know whether a template was searchable yet -- and it
was found by an end-to-end test that had to upload a real file to notice.

This is the same check for a hundredth of the cost: compare the keys each
`job_result()` actually produces against the fields the response models expose.
It runs offline, in milliseconds, and fails the moment the two drift.

Deliberately compares *produced* keys rather than a hand-written list. A list
would need updating in the same commit that introduces the drift, which is the
commit that forgets.
"""

from dataclasses import dataclass

import pytest

from app.ingestion.enrich import EnrichmentResult
from app.ingestion.metadata import TemplateMetadata
from app.ingestion.pipeline import Harvested, IngestionResult
from app.schemas.ingestion import EnrichmentOut, JobStatusOut


def _ingestion_result() -> IngestionResult:
    """A filled result, so `job_result()` emits every key it ever emits."""
    return IngestionResult(
        fmt="xlsx",
        pipeline_version="ingestion/1.0.0",
        detector_version="structural/1.0.0",
        fingerprint={"package_parts": []},
        schema_json={},
        regions=[],
        harvested=Harvested(
            form_id="YMSLI-F-MOM",
            house_pattern=None,
            in_doc_version=None,
            source={"form_id": "title-cell"},
        ),
        counts_by_kind={"field": 4},
        regions_detected=11,
        regions_writable=8,
        region_ids_stable=True,
        containers=["Sheet1"],
        warnings=[],
        elapsed_ms=420,
    )


def _enrichment_result() -> EnrichmentResult:
    from app.ingestion.classify import ClassificationResult

    return EnrichmentResult(
        metadata=TemplateMetadata(
            title="Minutes of Meeting (MOM) Form",
            purpose="Captures the record of a meeting.",
            when_to_use="After a meeting.",
            audience="Meeting organiser",
            tags=["MOM"],
            category="Meeting",
        ),
        classification=ClassificationResult(),
        embedding=[0.1] * 4,
        embedding_source="text",
        regions_labelled=11,
        regions_write_refused=3,
        model_id="us.anthropic.claude-sonnet-5",
        elapsed_ms=15802,
    )


def test_every_ingestion_summary_key_reaches_the_api() -> None:
    produced = set(_ingestion_result().job_result())
    exposed = set(JobStatusOut.model_fields)
    dropped = produced - exposed
    assert not dropped, (
        f"{sorted(dropped)} are written to the jobs row and never reach a client. "
        f"Add them to JobStatusOut and map them in the ingestion_status route."
    )


def test_every_enrichment_key_reaches_the_api() -> None:
    produced = set(_enrichment_result().job_result())
    exposed = set(EnrichmentOut.model_fields)
    dropped = produced - exposed
    assert not dropped, (
        f"{sorted(dropped)} are recorded by enrichment and never reach a client. "
        f"Add them to EnrichmentOut."
    )


def test_enrichment_is_optional_on_a_succeeded_job() -> None:
    """A succeeded job with no enrichment is an outage, not an error.

    Enrichment runs after the structural result is committed and cannot fail
    it, so this combination is expected and the frontend must be able to render
    it. If `enrichment` ever became required, a Bedrock outage would start
    returning 500s from a route about a job that succeeded.
    """
    assert JobStatusOut.model_fields["enrichment"].is_required() is False


@pytest.mark.parametrize("field", ["semantic_role", "editable", "protected", "notes"])
def test_region_output_carries_what_track_c_needs(field: str) -> None:
    """The region map is what the frontend renders, and what generation targets."""
    from app.schemas.ingestion import RegionOut

    assert field in RegionOut.model_fields


def test_template_output_exposes_the_generated_metadata() -> None:
    """The library card's whole job is saying what a template is *for*.

    Same class of bug as the dropped enrichment block: the columns exist, the
    enrichment pass fills them, and a response model that omits them makes them
    invisible to the frontend with no error anywhere.
    """
    from app.schemas.template import TemplateOut

    for field in ("purpose", "when_to_use", "audience", "category", "tags", "searchable"):
        assert field in TemplateOut.model_fields, f"TemplateOut drops {field}"


def test_semantic_role_is_clamped_to_the_column_width() -> None:
    """An over-long role is not cosmetic — it kills the whole enrichment.

    `document_regions.semantic_role` is VARCHAR(100). A model that answers with
    a sentence overflows it, Postgres fails the statement, and a failed
    statement poisons the transaction: the observed result was an ingestion job
    stuck at `running` forever. Caught in production on the BFL, whose role came
    back at 106 characters.
    """
    from app.ingestion.enrich import SEMANTIC_ROLE_MAX, _role
    from app.models.document_region import DocumentRegion

    column = DocumentRegion.__table__.columns["semantic_role"].type.length
    assert SEMANTIC_ROLE_MAX <= column, "the clamp is wider than the column it protects"

    real_overflow = (
        "detailed inventory of business functions with process, IO, ownership, "
        "frequency, and fit/gap classification"
    )
    assert len(real_overflow) > column
    assert len(_role(real_overflow)) <= column
    assert _role("meeting date") == "meeting date"
    assert _role("  padded  ") == "padded"
