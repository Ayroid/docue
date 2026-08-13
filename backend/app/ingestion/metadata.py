"""LLM pass B: the metadata a searcher actually matches against (plan §10 ②).

This is the text that gets embedded. Plan §9 argues the case and it is worth
restating because it is a scoring point rather than an implementation detail:
**we embed generated metadata, not document chunks.** The BFL's body is thirty
rows of Fit/Gap classifications; the MOM's body is one specific fixed-asset
workshop. Neither matches what someone types when they need that template. A
generated purpose statement does -- it is dense, distinctive, and written in
the vocabulary the searcher uses.

The model sees the document's *structure and labels*, not its filled-in values,
for the same reason: a template is described by its slots, and this copy's
project data is an accident of which file was uploaded.

Failure mode is the plan's: fall back to the filename plus the sheet or section
headings. Search degrades to lexical, which is the corpus's acronyms anyway.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai.bedrock import BedrockError, complete_json
from app.ai.prompts import METADATA_SYSTEM, METADATA_VERSION

logger = logging.getLogger(__name__)

__all__ = ["TemplateMetadata", "embedding_text", "write_metadata"]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "purpose": {"type": "string"},
        "when_to_use": {"type": "string"},
        "audience": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
    },
    "required": ["title", "purpose", "when_to_use", "audience", "tags", "category"],
    "additionalProperties": False,
}


@dataclass
class TemplateMetadata:
    """Maps onto the `templates` columns of plan §8."""

    title: str
    purpose: str
    when_to_use: str
    audience: str
    tags: list[str] = field(default_factory=list)
    category: str = ""
    generated: bool = True
    prompt_version: str = METADATA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def embedding_text(metadata: TemplateMetadata, *, form_id: str | None = None) -> str:
    """The exact string that gets embedded (plan §9).

    Assembled in one place so the search side can never drift from the
    ingestion side -- an index built on a different concatenation than the
    query path assumes is the kind of bug that shows up only as bad relevance.
    """
    parts = [
        metadata.title,
        form_id or "",
        metadata.purpose,
        metadata.when_to_use,
        metadata.audience,
        " ".join(metadata.tags),
    ]
    return "\n".join(part for part in parts if part).strip()


def _evidence(schema: Any, filename: str) -> dict[str, Any]:
    """Structure and labels, not values.

    Titles and field labels come through because they name the slots; a
    `field`'s current content does not, because it belongs to whichever project
    happened to fill this copy in.
    """
    regions = list(schema.regions)
    titles = [r.label for r in regions if r.kind == "title" and r.label]
    fields = [r.label for r in regions if r.kind in ("field", "field_empty") and r.label]
    tables = [
        {
            "label": r.label,
            "columns": [c["name"] for c in (r.notes.get("columns") or []) if c.get("name")][:12],
        }
        for r in regions
        if r.kind in ("table_loop", "table_data")
    ]
    blocks = [r.label for r in regions if r.kind == "repeating_block" and r.label]

    evidence: dict[str, Any] = {
        "filename": filename,
        "format": schema.format,
        "titles": titles[:12],
        "field_labels": fields[:40],
        "tables": tables[:10],
        "section_labels": blocks[:25],
        "region_counts": schema.counts_by_kind(),
    }
    notes = getattr(schema, "notes", {}) or {}
    for key in ("house_pattern", "in_doc_version"):
        if notes.get(key):
            evidence[key] = notes[key]
    sheets = getattr(schema, "sheets", None)
    if sheets:
        evidence["sheets"] = [{"name": s.name, "role": s.role} for s in sheets]
    slides = getattr(schema, "slides", None)
    if slides:
        evidence["slide_titles"] = [s.title for s in slides if s.title][:15]
    return evidence


def _fallback(schema: Any, filename: str) -> TemplateMetadata:
    """Filename plus headings. The plan's stated degradation for this stage."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
    headings = [r.label for r in schema.regions if r.kind == "title" and r.label][:5]
    sheets = [s.name for s in getattr(schema, "sheets", []) or []]
    tags = [t for t in [*stem.split(), *sheets] if len(t) > 1][:10]
    return TemplateMetadata(
        title=stem or "Untitled template",
        purpose=" / ".join(headings) if headings else stem,
        when_to_use="",
        audience="",
        tags=tags,
        category="",
        generated=False,
        prompt_version="fallback/none",
    )


def write_metadata(schema: Any, *, filename: str) -> TemplateMetadata:
    """Generate discovery metadata for one template. Never raises."""
    try:
        payload = complete_json(
            purpose="write_metadata",
            system=METADATA_SYSTEM,
            user=json.dumps(_evidence(schema, filename), ensure_ascii=False, indent=1),
            schema=_SCHEMA,
            prompt_version=METADATA_VERSION,
            max_tokens=2000,
        )
    except BedrockError as exc:
        logger.warning("metadata generation failed for %s: %s", filename, exc)
        return _fallback(schema, filename)

    return TemplateMetadata(
        title=payload["title"],
        purpose=payload["purpose"],
        when_to_use=payload["when_to_use"],
        audience=payload["audience"],
        tags=_tags(payload.get("tags")),
        category=payload["category"],
    )


def _tags(raw: Any) -> list[str]:
    """Coerce whatever came back into a list of tags.

    The schema says `array of string` and Bedrock validates tool arguments
    against it -- but not strictly enough to rely on: three of five corpus
    documents came back with `tags` as one comma-separated *string*, which a
    plain list comprehension then iterates character by character. The stored
    tags became `['M', 'O', 'M', ',', ' ', ...]`, and since tags are part of
    the embedded text, that silently poisons search rather than failing.

    Validate at the boundary; never trust a model's container type.
    """
    if isinstance(raw, str):
        text = raw.strip()
        # Seen in the wild from the same schema: a real JSON array delivered as
        # a string. Parse it as one before falling back to splitting, or every
        # tag keeps a stray quote and the first and last keep a bracket.
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = text.split(",")
        else:
            raw = text.split(",")
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().strip("[]\"'").strip()
        # A one-character tag is either debris from a split string or a tag too
        # short to retrieve anything.
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
    return tags[:12]
