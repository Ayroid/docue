"""The AI half of ingestion: semantic labels, discovery metadata, one vector.

Structure comes first and stands alone. `pipeline.ingest()` is documented as
doing no I/O beyond the bytes it is given, and an LLM call is network I/O, so
this is a **separate stage that runs after the structural result is already
committed**. That ordering is the design, not an accident of layering:

* Structural ingestion has a 90s budget and finishes in well under a second.
  These two model calls take 25-50s for a document the size of the BRD. Putting
  them inside `ingest()` would put a slow third-party service on the critical
  path of a result that had already succeeded.
* A model outage, a rate limit or a bad response then costs the *labels*, not
  the schema. The template still has its regions, still compiles, still
  downloads. It is simply not yet findable by meaning -- a visible gap, which
  plan §14 prefers to a half-finished document that looks complete.

Mirrors the shape of `pipeline.py` deliberately: `enrich()` does the work and
touches no database, `persist_enrichment()` writes it, `run_enrichment()` does
both and commits nothing. Anyone who has read one can read the other.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai.bedrock import BedrockError, embed
from app.ai.prompts import CLASSIFIER_VERSION, METADATA_VERSION
from app.core.config import settings
from app.ingestion.classify import ClassificationResult, classify_regions
from app.ingestion.detect import detect
from app.ingestion.metadata import TemplateMetadata, embedding_text, write_metadata
from app.models.document_region import DocumentRegion
from app.models.document_schema import DocumentSchemaRow
from app.models.template import Template
from app.models.template_version import TemplateVersion

logger = logging.getLogger(__name__)

__all__ = ["EnrichmentResult", "enrich", "persist_enrichment", "run_enrichment"]

ENRICHMENT_VERSION = "enrichment/1.0.0"


@dataclass
class EnrichmentResult:
    metadata: TemplateMetadata
    classification: ClassificationResult
    embedding: list[float] | None
    embedding_source: str
    regions_labelled: int
    regions_write_refused: int
    model_id: str
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.embedding is not None and self.metadata.generated

    def job_result(self) -> dict[str, Any]:
        return {
            "enrichment_version": ENRICHMENT_VERSION,
            "model_id": self.model_id,
            "classifier_prompt": CLASSIFIER_VERSION,
            "metadata_prompt": METADATA_VERSION,
            "regions_labelled": self.regions_labelled,
            "regions_write_refused": self.regions_write_refused,
            "metadata_generated": self.metadata.generated,
            "embedded": self.embedding is not None,
            "title": self.metadata.title,
            "tags": self.metadata.tags,
            "elapsed_ms": self.elapsed_ms,
            "warnings": self.warnings,
        }


def enrich(data: bytes, fmt: str, *, filename: str, form_id: str | None = None) -> EnrichmentResult:
    """Classify, describe and embed one document. No database.

    Re-runs `detect()` rather than taking the persisted region rows. It costs
    tens of milliseconds against a budget measured in tens of seconds, and it
    buys working on the detector's own objects -- with `notes`, column names and
    the sheet/slide grouping the classifier reads -- instead of reconstructing
    them from JSONB. The `region_id`s are the same either way; `ingest()`
    already proves that by re-detecting and comparing.
    """
    started = time.perf_counter()
    warnings: list[str] = []
    schema = detect(data, fmt)

    classification = classify_regions(schema, filename=filename)
    labelled = classification.apply_to(schema)
    warnings.extend(classification.errors)
    if classification.dropped_ids:
        warnings.append(
            f"classifier named {len(classification.dropped_ids)} region_id(s) that do not exist"
        )

    metadata = write_metadata(schema, filename=filename)
    if not metadata.generated:
        warnings.append("metadata fell back to the filename; the model call failed")

    # Embedded even when the metadata fell back, because a filename plus
    # headings is still more searchable than nothing -- but recorded as such, so
    # a re-run after the outage can find the rows worth redoing.
    text = embedding_text(metadata, form_id=form_id)
    vector: list[float] | None = None
    try:
        vector = embed([text])[0]
    except BedrockError as exc:
        logger.warning("embedding failed for %s: %s", filename, exc)
        warnings.append(f"embedding failed: {exc}")

    return EnrichmentResult(
        metadata=metadata,
        classification=classification,
        embedding=vector,
        embedding_source=text,
        regions_labelled=labelled,
        regions_write_refused=len(classification.refused_writes),
        model_id=settings.bedrock_model_id,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        warnings=warnings,
    )


def persist_enrichment(
    db: Session,
    template: Template,
    version: TemplateVersion,
    result: EnrichmentResult,
) -> None:
    """Write labels onto the stored regions and metadata onto the template.

    Updates rows rather than replacing them: the structural pass owns
    `document_regions`, and re-running enrichment must not renumber, reorder or
    delete anything it wrote. Only the columns the structural pass leaves null
    because it cannot know meaning are touched.
    """
    labels = result.classification.labels
    if labels:
        stored = (
            db.query(DocumentRegion)
            .filter(DocumentRegion.version_id == version.id)
            .all()
        )
        for row in stored:
            label = labels.get(row.region_id)
            if label is None:
                continue
            row.semantic_role = label.semantic_role
            if label.label:
                row.label = label.label
            if label.value_type != "none":
                row.value_type = label.value_type
            row.required = label.required
            # Narrowing only, in the database too. A stored region that the
            # structural pass marked unwritable can never be re-opened here.
            if label.should_not_write and row.editable:
                row.editable = False
            notes = dict(row.notes or {})
            notes["semantic_role"] = label.semantic_role
            notes["llm_confidence"] = label.confidence
            notes["classified_by"] = CLASSIFIER_VERSION
            row.notes = notes

    db.execute(
        update(DocumentSchemaRow)
        .where(DocumentSchemaRow.version_id == version.id)
        .values(
            llm_model=result.model_id,
            prompt_version=CLASSIFIER_VERSION,
            confidence=_mean_confidence(result.classification),
        )
    )

    metadata = result.metadata
    template.title = metadata.title or template.title
    template.purpose = metadata.purpose
    template.when_to_use = metadata.when_to_use
    template.audience = metadata.audience
    template.category = metadata.category
    template.tags = metadata.tags
    template.metadata_model = result.model_id
    template.metadata_prompt_version = metadata.prompt_version
    if result.embedding is not None:
        template.embedding = result.embedding
        template.embedded_at = datetime.now(timezone.utc)


def _mean_confidence(classification: ClassificationResult) -> float | None:
    if not classification.labels:
        return None
    scores = [label.confidence for label in classification.labels.values()]
    return round(sum(scores) / len(scores), 3)


def run_enrichment(
    db: Session,
    template: Template,
    version: TemplateVersion,
    data: bytes,
) -> EnrichmentResult:
    """Enrich and persist one version. Commits nothing -- the caller owns the
    transaction, exactly as `run_ingestion` does."""
    result = enrich(
        data,
        template.format,
        filename=template.original_filename,
        form_id=template.form_id,
    )
    persist_enrichment(db, template, version, result)
    logger.info(
        "enriched version %s: %d regions labelled, %d write-refused, embedded=%s, %dms",
        version.id,
        result.regions_labelled,
        result.regions_write_refused,
        result.embedding is not None,
        result.elapsed_ms,
    )
    return result
