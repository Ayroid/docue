"""Ingestion pipeline: fingerprint -> detect -> harvest -> persist -> verify.

One call per format, and the only place that knows how a detected schema becomes
rows. Split deliberately into a pure half and a database half:

* `ingest(data, fmt)` touches no database. It is the whole analysis, so it can
  be run against a file on disk -- which is how it is tested, and how Track B
  can evaluate a classifier over the same output without standing up Postgres.
* `persist(db, ...)` takes that result and writes it. Nothing is computed there.

**Harvesting is the point of this module, not a side effect.** Detection already
finds the things the hub most wants to know and then throws them away: YMSLI's
own `Form ID`, the Cover/History/Instruction house pattern, and the `Ver.` the
document claims about itself. That last one is drift detection with no diffing
at all (plan §1.3) -- a personal copy still saying `Ver. 1` against a hub at 3.0
is provably two versions behind. All three are read back out of the schema here
rather than re-parsed, so nothing re-implements detection.
"""

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ingestion.detect import (
    detect,
    fingerprint,
    fingerprint_dict,
    locator_dict,
    region_containers,
)
from app.models.document_region import DocumentRegion
from app.models.document_schema import DocumentSchemaRow
from app.models.template import Template
from app.models.template_version import TemplateVersion

logger = logging.getLogger("app.ingestion")

PIPELINE_VERSION = "ingestion/1.0.0"

# Plan §14: a 30s parse timeout. BFL's `Business Function List` sheet declares
# max_row=1048575 and once killed a worker outright, so the budget is not
# theoretical -- though `regions.py` bounding its scans is what actually fixed
# that, and this is the backstop.
DETECT_TIMEOUT_S = 30.0
# The whole pipeline, including a second detection pass. Ingestion is allowed
# 15-40s by plan §6, and the request has already returned 202 by now.
PIPELINE_BUDGET_S = 90.0

# Progress per stage, for the job the frontend polls.
STAGES: tuple[tuple[str, int], ...] = (
    ("fingerprint", 10),
    ("detect", 45),
    ("harvest", 60),
    ("verify", 75),
    ("persist", 95),
)

# `Form ID:YMSLI-F-MOM` in the MOM's `D3`, and the spaced/colon-less variants.
# The value is everything after the separator: form ids in this corpus are one
# token, but a fallback that grabbed the rest of the line would swallow prose.
_FORM_ID_RE = re.compile(r"form\s*id\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9._/\-]{2,60})", re.IGNORECASE)
_VERSION_TOKENS = frozenset({"ver", "version", "verno", "versionno"})
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

HOUSE_COVER_HISTORY_INSTRUCTION = "ymsli_cover_history_instruction"
HOUSE_REVISION_BLOCK = "ymsli_revision_block"


class IngestionError(RuntimeError):
    """Ingestion could not complete. The job records it; the upload survives."""


@dataclass
class Harvested:
    """What detection found and used to discard."""

    form_id: str | None = None
    house_pattern: str | None = None
    in_doc_version: str | None = None
    source: dict[str, str] = field(default_factory=dict)  # field -> where it came from


@dataclass
class IngestionResult:
    fmt: str
    pipeline_version: str
    detector_version: str
    fingerprint: dict[str, Any]
    schema_json: dict[str, Any]
    regions: list[dict[str, Any]]  # ready for `document_regions`
    harvested: Harvested
    counts_by_kind: dict[str, int]
    regions_detected: int
    regions_writable: int
    region_ids_stable: bool
    containers: list[str]
    warnings: list[str]
    elapsed_ms: int

    def job_result(self) -> dict[str, Any]:
        """The summary the job row carries, minus the fingerprint (which lives
        on `template_versions` and would double the row for nothing)."""
        return {
            "pipeline_version": self.pipeline_version,
            "detector_version": self.detector_version,
            "regions_detected": self.regions_detected,
            "regions_writable": self.regions_writable,
            "counts_by_kind": self.counts_by_kind,
            "containers": self.containers,
            "house_pattern_matched": self.harvested.house_pattern,
            "form_id": self.harvested.form_id,
            "in_doc_version": self.harvested.in_doc_version,
            "harvest_source": self.harvested.source,
            "region_ids_stable": self.region_ids_stable,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
        }


# ── JSON safety ───────────────────────────────────────────────────────────


def _jsonable(value: Any) -> Any:
    """Coerce a detector's output into something JSONB will accept.

    The detectors are honest about types -- an xlsx cell's value can arrive as a
    `datetime`, a `Decimal` or a tuple -- and `json.dumps` refuses the first two.
    Coercing here rather than configuring a custom serialiser on the engine keeps
    the change inside this module and out of `app/db/`.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    return str(value)


# ── harvest ───────────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    return _NON_ALNUM_RE.sub("", text.lower())


def _harvest_form_id(schema: Any) -> tuple[str | None, str | None]:
    """YMSLI's own identifier for the form, e.g. `YMSLI-F-MOM`.

    Read off the document rather than the filename. It matters more than it
    looks: it is the single most distinctive BM25 term in the corpus, and plan
    §9 is explicit that acronyms like this are what embeddings handle worst.

    A `field` whose label *is* `Form ID` gives the cleanest answer, so those are
    checked first; otherwise any region text carrying the pattern will do -- in
    the MOM it lives inside a merged title, `Form ID:YMSLI-F-MOM`.
    """
    for region in schema.regions:
        if region.label and _normalise(region.label) in {"formid", "formno", "formnumber"}:
            value = (region.current_content or "").strip()
            if value:
                return value, f"field:{region.region_id}"
    for region in schema.regions:
        for text in (region.current_content, region.label):
            if not text:
                continue
            match = _FORM_ID_RE.search(text)
            if match:
                return match.group(1).strip(), f"text:{region.region_id}"
    return None, None


def _harvest_house_pattern(schema: Any) -> tuple[str | None, str | None]:
    """Which YMSLI house shape this document follows (plan §1.3).

    Two shapes, and the difference is real rather than cosmetic: the workbooks
    carry whole `Cover` / `History` / `Instruction` *sheets* -- in BFL's case the
    Instruction sheet documents every column, which is a hand-written placeholder
    schema -- while the docx carries only the revision block. A caller that knows
    which one it has knows whether an Instruction sheet is there to parse.
    """
    roles = {
        sheet.role
        for sheet in getattr(schema, "sheets", [])
        if getattr(sheet, "role", None)
    }
    if "history" in roles and (roles & {"cover", "instruction"}):
        return HOUSE_COVER_HISTORY_INSTRUCTION, f"sheet_roles:{sorted(roles)}"

    declared = (getattr(schema, "notes", {}) or {}).get("house_pattern")
    if declared:
        return declared, "schema.notes"
    if any(region.kind == "history" for region in schema.regions):
        return HOUSE_REVISION_BLOCK, "history_region"
    if roles:
        return HOUSE_COVER_HISTORY_INSTRUCTION, f"sheet_roles:{sorted(roles)}"
    return None, None


def _history_region(schema: Any) -> Any | None:
    return next((region for region in schema.regions if region.kind == "history"), None)


def _harvest_in_doc_version(schema: Any, data: bytes, fmt: str) -> tuple[str | None, str | None]:
    """The last `Ver.` the document's own revision block declares.

    The docx detector already extracts this, so it is simply read. The xlsx
    detector records the revision block's geometry but not its contents, so the
    value is pulled from the cells the region points at -- `read_only=True` and
    bounded by the row count the region reports, never by `max_row`.
    """
    declared = (getattr(schema, "notes", {}) or {}).get("in_doc_version")
    if declared:
        return str(declared), "schema.notes"

    region = _history_region(schema)
    if region is None:
        return None, None
    from_notes = region.notes.get("in_doc_version")
    if from_notes:
        return str(from_notes), f"region.notes:{region.region_id}"

    if fmt != "xlsx":
        return None, None
    return _xlsx_history_version(region, data)


def _xlsx_history_version(region: Any, data: bytes) -> tuple[str | None, str | None]:
    """Read the revision block's `Ver.` column out of the workbook."""
    columns = region.notes.get("columns") or []
    version_column = next(
        (
            column.get("column")
            for column in columns
            if _normalise(str(column.get("name", ""))) in _VERSION_TOKENS
        ),
        None,
    )
    if not version_column:
        return None, None

    first_row = region.notes.get("first_data_row")
    row_count = region.notes.get("row_count") or 0
    if not first_row or row_count <= 0:
        return None, None

    import io

    import openpyxl
    from openpyxl.utils import column_index_from_string

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet_name = region.locator.sheet
        if sheet_name not in workbook.sheetnames:  # pragma: no cover - defensive
            return None, None
        worksheet = workbook[sheet_name]
        column_index = column_index_from_string(version_column)
        latest = None
        # Bounded by the region's own row count, so a sheet claiming a million
        # rows cannot turn this into a full scan.
        for row in worksheet.iter_rows(
            min_row=first_row,
            max_row=first_row + row_count - 1,
            min_col=column_index,
            max_col=column_index,
            values_only=True,
        ):
            value = row[0]
            if value is None:
                continue
            text = str(value).strip()
            if text:
                latest = text
    finally:
        workbook.close()

    if latest is None:
        return None, None
    return latest, f"cells:{region.locator.sheet}!{version_column}"


def harvest(schema: Any, data: bytes, fmt: str) -> Harvested:
    form_id, form_source = _harvest_form_id(schema)
    house_pattern, house_source = _harvest_house_pattern(schema)
    in_doc_version, version_source = _harvest_in_doc_version(schema, data, fmt)

    source = {}
    for name, origin in (
        ("form_id", form_source),
        ("house_pattern", house_source),
        ("in_doc_version", version_source),
    ):
        if origin:
            source[name] = origin

    return Harvested(
        form_id=form_id,
        house_pattern=house_pattern,
        in_doc_version=in_doc_version,
        source=source,
    )


# ── warnings ──────────────────────────────────────────────────────────────


def _collect_warnings(schema: Any, fingerprint_data: dict[str, Any], fmt: str) -> list[str]:
    """Facts about *this run* worth surfacing, none of them fatal.

    Deliberately not exceptions: plan §14's rule is that a region we could not
    read is left untouched and *shown*, never guessed at. A warning is how it
    gets shown.
    """
    warnings: list[str] = []

    if not schema.regions:
        warnings.append("no regions detected -- nothing in this document is addressable")
    elif not schema.writable():
        warnings.append(
            "no writable regions -- every region came out immutable, so generation "
            "would have nothing to fill"
        )

    unknown = sum(1 for region in schema.regions if region.kind == "immutable")
    if schema.regions and unknown == len(schema.regions):
        warnings.append("every region is `immutable`; structure was not recognised")

    for sheet in getattr(schema, "sheets", []):
        sentinels = (getattr(sheet, "notes", {}) or {}).get("sentinel_cells")
        if sentinels:
            warnings.append(
                f"sheet {sheet.name!r}: {sentinels} print-extent '*' sentinel cell(s) "
                "ignored rather than counted as content"
            )

    dangling = fingerprint_data.get("dangling_relationships")
    if dangling:
        warnings.append(
            f"{len(dangling)} dangling relationship reference(s) in the uploaded file: "
            f"{dangling[:5]} -- Word may offer to repair it"
        )

    if fmt == "docx":
        hyperlink_paragraphs = (getattr(schema, "notes", {}) or {}).get("hyperlink_paragraphs")
        if hyperlink_paragraphs:
            warnings.append(
                f"{hyperlink_paragraphs} paragraph(s) hold text inside a hyperlink and "
                "cannot be rewritten at run level; they are marked immutable"
            )

    if not fingerprint_data.get("package_parts"):
        warnings.append("fingerprint recorded no package parts")

    return warnings


# ── the pure half ─────────────────────────────────────────────────────────


def _with_timeout(work: Callable[[], Any], seconds: float, what: str) -> Any:
    """Run `work`, giving up after `seconds`.

    Honest about what this does and does not do: it stops *waiting*, it does not
    kill the thread -- Python cannot. A genuinely wedged parse would leak one
    thread until the process restarts. That is an acceptable trade here because
    the request has already returned 202 and the job is marked failed, so the
    user sees a failure rather than a hang; the real fix is the worker process
    plan §6 calls for, and this is the interim guard.
    """
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest") as pool:
        future = pool.submit(work)
        try:
            return future.result(timeout=seconds)
        except FutureTimeoutError as exc:
            raise IngestionError(
                f"{what} exceeded {seconds:.0f}s and was abandoned"
            ) from exc


def ingest(
    data: bytes,
    fmt: str,
    *,
    on_stage: Callable[[str, int], None] | None = None,
    verify_stability: bool = True,
) -> IngestionResult:
    """Analyse a document end to end. No database, no I/O beyond the bytes given.

    `verify_stability` re-runs detection and compares the `region_id`s. They are
    the primary key every downstream operation addresses (`UNIQUE (version_id,
    region_id)`), so an id that moved between two runs over identical bytes would
    silently break every stored spec. It costs one more detection pass, which is
    tens of milliseconds against a 15-40s budget.
    """
    started = time.perf_counter()

    def report(stage: str) -> None:
        progress = dict(STAGES).get(stage, 0)
        if on_stage is not None:
            on_stage(stage, progress)

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def check_budget(stage: str) -> None:
        if time.perf_counter() - started > PIPELINE_BUDGET_S:
            raise IngestionError(
                f"ingestion exceeded its {PIPELINE_BUDGET_S:.0f}s budget at stage {stage!r}"
            )

    report("fingerprint")
    fingerprint_data = _jsonable(fingerprint_dict(_with_timeout(
        lambda: fingerprint(data, fmt), DETECT_TIMEOUT_S, "fingerprinting"
    )))
    check_budget("fingerprint")

    report("detect")
    schema = _with_timeout(lambda: detect(data, fmt), DETECT_TIMEOUT_S, "region detection")
    check_budget("detect")

    report("harvest")
    harvested = harvest(schema, data, fmt)
    check_budget("harvest")

    report("verify")
    region_ids = [region.region_id for region in schema.regions]
    region_ids_stable = True
    if verify_stability:
        second = _with_timeout(
            lambda: detect(data, fmt), DETECT_TIMEOUT_S, "region detection (re-detect)"
        )
        region_ids_stable = [region.region_id for region in second.regions] == region_ids
    check_budget("verify")

    warnings = _collect_warnings(schema, fingerprint_data, fmt)
    if not region_ids_stable:
        # Not fatal, but it invalidates the assumption every stored Change Spec
        # rests on, so it must be visible rather than inferred later.
        warnings.append(
            "region_ids are NOT stable across two detections of identical bytes -- "
            "stored specs addressing them cannot be trusted"
        )

    # `sequence` is the document-wide position. The detector's `ordinal` restarts
    # at 0 on every sheet, so four regions in BFL share ordinal 0 and sorting a
    # region map by it returns them in arbitrary order. `schema.regions` is
    # already in document order -- sheet by sheet, slide by slide -- so the
    # enumeration index is the total order, and `ordinal` is left untouched
    # because contract C3 says it is the detector's field.
    regions = [
        {
            "region_id": region.region_id,
            "kind": region.kind,
            "label": region.label,
            "value_type": region.value_type,
            "locator": _jsonable(locator_dict(region.locator)),
            "current_content": region.current_content,
            "editable": bool(region.editable),
            "protected": bool(region.protected),
            "required": bool(region.required),
            "detection_method": region.detection_method,
            "ordinal": region.ordinal,
            "sequence": sequence,
            "notes": _jsonable(region.notes) or None,
        }
        for sequence, region in enumerate(schema.regions)
    ]

    return IngestionResult(
        fmt=fmt,
        pipeline_version=PIPELINE_VERSION,
        detector_version=schema.detector_version,
        fingerprint=fingerprint_data,
        schema_json=_jsonable(asdict(schema)) if is_dataclass(schema) else {},
        regions=regions,
        harvested=harvested,
        counts_by_kind=schema.counts_by_kind(),
        regions_detected=len(schema.regions),
        regions_writable=len(schema.writable()),
        region_ids_stable=region_ids_stable,
        containers=[name for name, _ in region_containers(schema) if name],
        warnings=warnings,
        elapsed_ms=elapsed_ms(),
    )


# ── the database half ─────────────────────────────────────────────────────


def persist(
    db: Session,
    template: Template,
    version: TemplateVersion,
    result: IngestionResult,
) -> None:
    """Write an `IngestionResult` to the three tables plus the harvest columns.

    Idempotent: re-ingesting a version deletes its previous schema and regions
    first. `document_schemas` is `UNIQUE (version_id)` and `document_regions` is
    `UNIQUE (version_id, region_id)`, so without that a second run would fail on
    a constraint rather than replace the schema -- and re-ingestion is exactly
    what happens after a detector improves.
    """
    db.query(DocumentRegion).filter(DocumentRegion.version_id == version.id).delete(
        synchronize_session=False
    )
    db.query(DocumentSchemaRow).filter(DocumentSchemaRow.version_id == version.id).delete(
        synchronize_session=False
    )

    db.add(
        DocumentSchemaRow(
            version_id=version.id,
            schema_json=result.schema_json,
            detector_version=result.detector_version,
        )
    )
    db.bulk_save_objects(
        [DocumentRegion(version_id=version.id, **row) for row in result.regions]
    )

    version.fingerprint = result.fingerprint
    if result.harvested.in_doc_version:
        version.in_doc_version = result.harvested.in_doc_version
    if result.harvested.form_id:
        template.form_id = result.harvested.form_id
    if result.harvested.house_pattern:
        template.house_pattern = result.harvested.house_pattern

    db.flush()


def run_ingestion(
    db: Session,
    template: Template,
    version: TemplateVersion,
    data: bytes,
    *,
    on_stage: Callable[[str, int], None] | None = None,
) -> IngestionResult:
    """Analyse and persist one version. Commits nothing -- the caller owns the
    transaction, because the job row's final status has to land in the same one."""
    result = ingest(data, template.format, on_stage=on_stage)
    if on_stage is not None:
        on_stage("persist", dict(STAGES)["persist"])
    persist(db, template, version, result)
    logger.info(
        "ingested version %s (%s): %d regions, %d writable, house_pattern=%s, "
        "form_id=%s, in_doc_version=%s, %dms",
        version.id,
        template.format,
        result.regions_detected,
        result.regions_writable,
        result.harvested.house_pattern,
        result.harvested.form_id,
        result.harvested.in_doc_version,
        result.elapsed_ms,
    )
    return result
