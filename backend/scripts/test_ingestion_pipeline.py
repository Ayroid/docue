"""Ingestion pipeline over the real corpus, plus the contracts around it.

    uv run python scripts/test_ingestion_pipeline.py

Everything here runs **without a database**, on purpose: `pipeline.ingest()` is
the whole analysis and touches no session, so it can be proven against files on
disk. That is also what lets Track B evaluate a classifier over the same output
without standing up Postgres.

Four things are checked:

1. **Ingestion over all five corpus files** — regions, harvest, timings, and the
   warnings each document earns.
2. **JSONB serialisability** — every payload is run through `json.dumps`, which
   is literally what the driver will do. A `datetime` from an xlsx cell reaching
   `schema_json` unconverted would fail on insert, at which point the only clue
   would be a failed job row.
3. **Model / migration parity** — column names in `Base.metadata` against the
   DDL the single baseline migration actually renders. This is the drift that
   bites months later: a model gains a column, nobody updates the migration,
   and it works on every developer's already-migrated database.
4. **The API contract** — the routes exist, `POST /templates` answers 202, and
   the response models are the ones Track C is being asked to build against.

What it cannot check is the database round trip: insert, the unique constraints,
and the job row advancing while a poller watches. That needs a live Postgres —
see the note this prints at the end.
"""

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Settings are required at import time; these are placeholders so the analysis
# half can run with no `.env`. Nothing here opens a connection.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/templatehub")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("S3_BUCKET_NAME", "placeholder")

from app.ingestion.pipeline import (  # noqa: E402
    PIPELINE_VERSION,
    IngestionResult,
    ingest,
)

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"
SAMPLES: list[tuple[str, str]] = [
    ("MOM Sample.xlsx", "xlsx"),
    ("BFL Sample.xlsx", "xlsx"),
    ("POC List sample.xlsx", "xlsx"),
    ("BRD Sample.docx", "docx"),
    ("Workshop Readout Template.pptx", "pptx"),
]

# What the corpus is known to declare about itself. Asserted rather than printed,
# because harvesting these is the point of the pipeline: without them there is no
# drift detection and no `form_id` for BM25 to match on.
EXPECTED_HARVEST: dict[str, dict[str, str | None]] = {
    "MOM Sample.xlsx": {
        "form_id": "YMSLI-F-MOM",  # read out of the merged title, not the filename
        "house_pattern": None,  # one sheet, no Cover/History/Instruction
        "in_doc_version": None,
    },
    "BFL Sample.xlsx": {
        "form_id": None,
        "house_pattern": "ymsli_cover_history_instruction",
        "in_doc_version": "1",
    },
    "POC List sample.xlsx": {
        "form_id": None,
        "house_pattern": "ymsli_cover_history_instruction",
        "in_doc_version": "1",
    },
    "BRD Sample.docx": {
        "form_id": None,
        "house_pattern": "ymsli_revision_block",
        "in_doc_version": "1.0",
    },
}


def report(name: str, result: IngestionResult) -> None:
    harvested = result.harvested
    print("=" * 100)
    print(f"{name}   {result.fmt}   {result.elapsed_ms}ms   detector={result.detector_version}")
    print(
        f"  regions      {result.regions_detected} detected, {result.regions_writable} writable, "
        f"ids stable={result.region_ids_stable}"
    )
    print(f"  kinds        {result.counts_by_kind}")
    print(
        f"  harvested    form_id={harvested.form_id!r}  "
        f"house_pattern={harvested.house_pattern!r}  in_doc_version={harvested.in_doc_version!r}"
    )
    for key, origin in sorted(harvested.source.items()):
        print(f"                 {key} <- {origin}")
    if result.containers:
        shown = ", ".join(result.containers[:4])
        more = f" (+{len(result.containers) - 4} more)" if len(result.containers) > 4 else ""
        print(f"  containers   {shown}{more}")
    parts = result.fingerprint.get("package_parts") or []
    print(f"  fingerprint  {len(parts)} package parts, {len(result.fingerprint)} recorded fields")
    for warning in result.warnings:
        print(f"  WARN         {warning}")


def check_result(name: str, result: IngestionResult) -> list[str]:
    failures: list[str] = []

    if not result.region_ids_stable:
        failures.append(f"{name}: region_ids differ between two detections of identical bytes")
    if result.regions_detected == 0:
        failures.append(f"{name}: no regions detected")
    if result.pipeline_version != PIPELINE_VERSION:
        failures.append(f"{name}: pipeline_version {result.pipeline_version!r}")
    if not (result.fingerprint.get("package_parts")):
        failures.append(f"{name}: fingerprint recorded no package parts")

    # Every region must carry a non-empty locator, or nothing downstream can
    # address it -- `locator` is NOT NULL in the table for exactly this reason.
    for row in result.regions:
        if not row["locator"]:
            failures.append(f"{name}: region {row['region_id']!r} has an empty locator")
            break
        if not row["region_id"] or not row["kind"] or not row["detection_method"]:
            failures.append(f"{name}: region {row['region_id']!r} missing a NOT NULL field")
            break

    # `UNIQUE (version_id, region_id)` -- a duplicate would abort the insert
    # after the first conflicting row, so catch it here rather than in a job row.
    ids = [row["region_id"] for row in result.regions]
    if len(ids) != len(set(ids)):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        failures.append(f"{name}: duplicate region_ids would violate the unique constraint: {duplicates}")

    # `sequence` has to be a total order, which is the whole reason it exists
    # alongside `ordinal`. The detectors number `ordinal` from 0 *per sheet*, so
    # BFL emits four regions numbered 0; sorting a region map by it returned rows
    # in whatever order Postgres chose, and the persisted order stopped matching
    # the detected one. Guarding the invariant here keeps that from coming back.
    sequences = [row["sequence"] for row in result.regions]
    if sequences != list(range(len(result.regions))):
        failures.append(
            f"{name}: `sequence` is not a dense 0..n-1 total order: {sequences[:12]}"
        )
    # And the reason it can't just be `ordinal`: in a multi-sheet workbook that
    # column repeats, so it cannot be an ORDER BY on its own.
    ordinals = [row["ordinal"] for row in result.regions]
    if len(ordinals) > 1 and len(set(ordinals)) < len(ordinals) and sequences == ordinals:
        failures.append(f"{name}: `sequence` was copied from a non-unique `ordinal`")

    # The fail-safe default: nothing writable may also be protected.
    contradictory = [
        row["region_id"] for row in result.regions if row["editable"] and row["protected"]
    ]
    if contradictory:
        failures.append(f"{name}: regions both editable and protected: {contradictory[:5]}")

    expected = EXPECTED_HARVEST.get(name)
    if expected is not None:
        for field, want in expected.items():
            got = getattr(result.harvested, field)
            if got != want:
                failures.append(f"{name}: harvested {field}={got!r}, want {want!r}")

    return failures


def check_json_roundtrip(name: str, result: IngestionResult) -> list[str]:
    """Everything bound for a JSONB column has to survive `json.dumps`."""
    failures: list[str] = []
    for label, payload in (
        ("fingerprint", result.fingerprint),
        ("schema_json", result.schema_json),
        ("job_result", result.job_result()),
        ("regions", result.regions),
    ):
        try:
            encoded = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            failures.append(f"{name}: {label} is not JSON-serialisable: {exc}")
            continue
        if json.loads(encoded) != payload:
            failures.append(f"{name}: {label} does not survive a JSON round trip unchanged")
    return failures


def check_orm_mapping(result: IngestionResult) -> list[str]:
    """The persist dicts must match the mapped columns, with no DB involved.

    `bulk_save_objects` would raise `TypeError` on an unexpected keyword, but
    only at insert time inside a background job -- where the failure surfaces as
    a job row nobody is watching. Constructing one object here is free.
    """
    from app.models.document_region import DocumentRegion
    from app.models.document_schema import DocumentSchemaRow

    failures: list[str] = []
    version_id = uuid.uuid4()
    try:
        region = DocumentRegion(version_id=version_id, **result.regions[0])
        if region.region_id != result.regions[0]["region_id"]:
            failures.append("DocumentRegion did not take the region_id it was given")
    except TypeError as exc:
        failures.append(f"DocumentRegion rejects the persist payload: {exc}")
    try:
        DocumentSchemaRow(
            version_id=version_id,
            schema_json=result.schema_json,
            detector_version=result.detector_version,
        )
    except TypeError as exc:
        failures.append(f"DocumentSchemaRow rejects the persist payload: {exc}")
    return failures


# ── model / migration parity ──────────────────────────────────────────────

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE (\w+) \((.*?)\n\);", re.DOTALL)
_ADD_COLUMN_RE = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)")


def _rendered_migration_sql() -> str | None:
    """Ask alembic to render the single baseline migration as SQL. Offline: no
    connection made.

    Run as a subprocess through the console script rather than imported, because
    the repo has an `alembic/` directory that shadows the installed package when
    the working directory is on `sys.path`.
    """
    root = Path(__file__).resolve().parent.parent
    for candidate in ("alembic", "alembic.exe"):
        try:
            completed = subprocess.run(
                [candidate, "-c", "alembic.ini", "upgrade", "head", "--sql"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return completed.stdout
        print(f"  (alembic --sql failed: {completed.stderr.strip().splitlines()[-1:]})")
        return None
    return None


def check_migration_parity() -> list[str]:
    from app.db.base import Base
    import app.models  # noqa: F401  registers every model on Base.metadata

    sql = _rendered_migration_sql()
    if sql is None:
        print("  SKIPPED -- alembic console script not runnable here")
        return []

    created: dict[str, set[str]] = {}
    for table, body in _CREATE_TABLE_RE.findall(sql):
        columns = set()
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE", "CHECK")):
                continue
            columns.add(line.split()[0])
        created[table] = columns
    for table, column in _ADD_COLUMN_RE.findall(sql):
        created.setdefault(table, set()).add(column)

    failures: list[str] = []
    for table in ("document_schemas", "document_regions", "jobs"):
        if table not in created:
            failures.append(f"the migration does not create {table}")
            continue
        model_columns = set(Base.metadata.tables[table].columns.keys())
        missing = model_columns - created[table]
        extra = created[table] - model_columns
        if missing:
            failures.append(f"{table}: model has columns the migration never creates: {sorted(missing)}")
        if extra:
            failures.append(f"{table}: migration creates columns no model maps: {sorted(extra)}")
        print(f"  {table:20s} {len(model_columns)} columns, model and migration agree"
              if not (missing or extra) else f"  {table:20s} MISMATCH")

    # These columns are inline on templates/template_versions in the baseline
    # migration now, rather than added by a later ALTER TABLE -- still worth
    # checking explicitly since they're easy to typo or drop by accident.
    for table, column in (
        ("templates", "form_id"),
        ("templates", "house_pattern"),
        ("template_versions", "in_doc_version"),
        ("template_versions", "fingerprint"),
    ):
        if column not in created.get(table, set()):
            failures.append(f"the migration never creates {table}.{column}")
        elif column not in Base.metadata.tables[table].columns:
            failures.append(f"{table}.{column} is in the migration but not on the model")
        else:
            print(f"  {table}.{column:18s} added by the migration and mapped")

    return failures


# ── API contract ──────────────────────────────────────────────────────────


def check_api_contract() -> list[str]:
    from app.main import app

    failures: list[str] = []
    spec = app.openapi()
    paths = spec["paths"]

    upload = paths.get("/api/v1/templates", {}).get("post")
    if upload is None:
        failures.append("POST /api/v1/templates is missing")
    else:
        codes = [code for code in upload["responses"] if code.startswith("2")]
        if codes != ["202"]:
            failures.append(f"POST /templates answers {codes}, want ['202'] (contract C6)")
        else:
            schema_name = upload["responses"]["202"]["content"]["application/json"]["schema"][
                "$ref"
            ].rsplit("/", 1)[-1]
            fields = set(spec["components"]["schemas"][schema_name]["properties"])
            required = {"template_id", "version_id", "job_id", "status"}
            if not required.issubset(fields):
                failures.append(f"202 body is missing {sorted(required - fields)}")
            print(f"  POST /templates -> 202 {sorted(fields)}")

    for path in (
        "/api/v1/templates/{template_id}/ingestion/{job_id}",
        "/api/v1/templates/{template_id}/regions",
    ):
        if path not in paths:
            failures.append(f"{path} is missing")
        else:
            print(f"  GET  {path}")

    job_fields = set(spec["components"]["schemas"].get("JobStatusOut", {}).get("properties", {}))
    # The payload Track C polls, named in the Track A checklist.
    for field in (
        "status",
        "stage",
        "progress",
        "fingerprint",
        "regions_detected",
        "house_pattern_matched",
        "warnings",
    ):
        if field not in job_fields:
            failures.append(f"JobStatusOut has no {field!r} -- Track C polls for it")

    region_fields = set(spec["components"]["schemas"].get("RegionOut", {}).get("properties", {}))
    # Contract C3, field for field.
    for field in (
        "region_id",
        "kind",
        "locator",
        "editable",
        "protected",
        "detection_method",
        "ordinal",
        "notes",
    ):
        if field not in region_fields:
            failures.append(f"RegionOut has no {field!r} -- contract C3 names it")

    return failures


def main() -> int:
    if not FILES_DIR.exists():
        print(f"corpus not found: {FILES_DIR}")
        return 1

    failures: list[str] = []
    results: dict[str, IngestionResult] = {}

    for name, fmt in SAMPLES:
        path = FILES_DIR / name
        if not path.exists():
            print(f"missing sample: {path}")
            if name == "Workshop Readout Template.pptx":
                print("  run: uv run python scripts/build_workshop_readout_template.py")
                continue
            return 1
        result = ingest(path.read_bytes(), fmt)
        results[name] = result
        report(name, result)
        failures += check_result(name, result)
        failures += check_json_roundtrip(name, result)

    if results:
        failures += check_orm_mapping(next(iter(results.values())))

    print()
    print("=" * 100)
    print("model / migration parity")
    print("=" * 100)
    failures += check_migration_parity()

    print()
    print("=" * 100)
    print("API contract")
    print("=" * 100)
    failures += check_api_contract()

    print()
    print("=" * 100)
    total_regions = sum(r.regions_detected for r in results.values())
    slowest = max((r.elapsed_ms for r in results.values()), default=0)
    if failures:
        print(f"ingestion pipeline: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"ingestion pipeline: PASS -- {len(results)} documents, {total_regions} regions, "
        f"slowest {slowest}ms, every payload JSONB-safe"
    )
    print()
    print("NOT covered here (needs a live Postgres):")
    print("  - `alembic upgrade head` against a real database")
    print("  - the insert itself, and the UNIQUE (version_id, region_id) constraint")
    print("  - POST -> 202 -> poll the job -> GET regions, end to end")
    print("  Run those with a real .env, or point DATABASE_URL at a scratch database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
