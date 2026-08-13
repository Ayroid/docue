"""End-to-end: upload a real document, let it enrich, then find it by meaning.

    TEMPLATEHUB_LIVE_LLM=1 uv run python scripts/check_search_api.py

This closes the one seam nothing else covers. Every piece of Track B has been
verified on its own -- the classifier over the corpus, the embeddings, the
fusion, the SQL -- but `run_enrichment`, `persist_enrichment` and the job wiring
that calls them had never executed, because the search test seeded rows with a
raw INSERT. Pieces that work individually and a seam with no test is the exact
shape of a demo failure.

So this drives the real thing: a real uvicorn server (not `TestClient`, which
runs `BackgroundTasks` inside the request and would prove nothing about the
background path), a real upload, a real S3 object, a real job, real Bedrock
calls, real pgvector search over HTTP. It cleans up after itself.

Reuses Track A's harness from `check_ingestion_api.py` rather than
reimplementing it -- the urllib-not-httpx choice there is deliberate (Zscaler
hangs on a proxied call to 127.0.0.1) and worth inheriting rather than
rediscovering.
"""

import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from check_ingestion_api import (  # noqa: E402
    FILES_DIR,
    MIME_BY_SUFFIX,
    _cleanup,
    _free_port,
    _get_json,
    _post_file,
    _start_server,
    _wait_for_health,
)

SAMPLE = "MOM Sample.xlsx"
# The semantic query from plan §13. It shares no word with "Minutes of Meeting",
# which is the point -- if this ranks the MOM first, the vector half is real.
QUERY = "record what we agreed and who's doing what"
JOB_BUDGET_S = 180.0
POLL_INTERVAL_S = 1.0


def _row(sql: str, params: dict) -> tuple | None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return db.execute(text(sql), params).fetchone()
    finally:
        db.close()


def main() -> int:
    if not os.environ.get("TEMPLATEHUB_LIVE_LLM"):
        print("SKIPPED -- set TEMPLATEHUB_LIVE_LLM=1 (real upload, Bedrock calls, ~$0.06)")
        return 0

    path = FILES_DIR / SAMPLE
    if not path.exists():
        print(f"sample not found: {path}")
        return 1

    failures: list[str] = []
    template_id = version_id = job_id = None
    storage_key = None

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"starting uvicorn on {base} ...")
    server = _start_server(port)
    try:
        if not _wait_for_health(base, server):
            print("server did not become healthy")
            return 1

        # ── upload ────────────────────────────────────────────────────────
        started = time.perf_counter()
        status, body = _post_file(
            f"{base}/api/v1/templates", SAMPLE, path.read_bytes(), MIME_BY_SUFFIX[".xlsx"]
        )
        upload_s = time.perf_counter() - started
        if status != 202:
            print(f"upload returned {status}: {body}")
            return 1
        template_id = uuid.UUID(body["template_id"])
        version_id = uuid.UUID(body["version_id"])
        job_id = uuid.UUID(body["job_id"])
        print(f"  202 in {upload_s:.2f}s -- template {template_id}")

        # ── wait for the job, including the enrich stage ──────────────────
        stages_seen: list[str] = []
        deadline = time.perf_counter() + JOB_BUDGET_S
        job = None
        while time.perf_counter() < deadline:
            _, job = _get_json(f"{base}/api/v1/templates/{template_id}/ingestion/{job_id}")
            stage = job.get("stage")
            if stage and (not stages_seen or stages_seen[-1] != stage):
                stages_seen.append(stage)
            if job.get("status") in ("succeeded", "failed"):
                break
            time.sleep(POLL_INTERVAL_S)

        print(f"  job {job.get('status')} after {time.perf_counter() - started:.1f}s")
        print(f"  stages: {' -> '.join(stages_seen)}")
        if job.get("status") != "succeeded":
            failures.append(f"job did not succeed: {job.get('error')}")
        if "enrich" not in stages_seen:
            failures.append("the enrich stage never ran")

        # Top-level on the response, not nested under `result`: the route
        # flattens the job's stored summary into named fields, so anything not
        # named there is invisible to a client no matter what the job row holds.
        enrichment = job.get("enrichment")
        if not enrichment:
            failures.append("the job status response carries no enrichment block")
        else:
            print(
                f"  enrichment: {enrichment['regions_labelled']} labelled, "
                f"{enrichment['regions_write_refused']} write-refused, "
                f"embedded={enrichment['embedded']}, {enrichment['elapsed_ms']}ms"
            )
            print(f"  title: {enrichment['title']!r}")
            print(f"  tags:  {enrichment['tags']}")
            if not enrichment["embedded"]:
                failures.append("the template was not embedded")

        # ── persist_enrichment actually wrote ─────────────────────────────
        row = _row(
            "select purpose, tags, embedding is not null, metadata_model, "
            "metadata_prompt_version, embedded_at is not null "
            "from templates where id = :i",
            {"i": str(template_id)},
        )
        if row is None or not row[0]:
            failures.append("templates.purpose was not written")
        if row and not row[2]:
            failures.append("templates.embedding was not written")
        if row and not row[5]:
            failures.append("templates.embedded_at was not written")
        print(f"  templates row: purpose={bool(row and row[0])}, tags={len(row[1] or []) if row else 0}, "
              f"embedding={bool(row and row[2])}, model={row[3] if row else None}")

        labelled = _row(
            "select count(*), count(semantic_role) from document_regions where version_id = :v",
            {"v": str(version_id)},
        )
        print(f"  document_regions: {labelled[0]} rows, {labelled[1]} with a semantic_role")
        if not labelled[1]:
            failures.append("no region got a semantic_role -- persist_enrichment did not write")

        schema_row = _row(
            "select llm_model, prompt_version, confidence from document_schemas where version_id = :v",
            {"v": str(version_id)},
        )
        print(f"  document_schemas: model={schema_row[0]}, prompt={schema_row[1]}, confidence={schema_row[2]}")
        if schema_row is None or not schema_row[0]:
            failures.append("document_schemas.llm_model was not written")

        # Narrowing-only, checked in the database this time.
        widened = _row(
            "select count(*) from document_regions where version_id = :v "
            "and editable = true and protected = true",
            {"v": str(version_id)},
        )
        if widened and widened[0]:
            failures.append(f"{widened[0]} protected region(s) are marked editable")

        # ── find it by meaning, over HTTP ─────────────────────────────────
        import json
        import urllib.request

        request = urllib.request.Request(
            f"{base}/api/v1/search",
            data=json.dumps({"query": QUERY, "top_k": 3}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        search_started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            results = json.loads(response.read())
        search_s = time.perf_counter() - search_started

        print(f'\n  POST /search "{QUERY}" -- {search_s:.2f}s, {len(results["results"])} results')
        for position, hit in enumerate(results["results"], start=1):
            print(f"    {position}. {hit['title'][:52]:<52} rrf={hit['score']:.5f}")
            print(f"       {hit['match_explanation']}")
            for highlight in hit["highlights"]:
                print(f"       {highlight[:130]}")

        if not results["results"]:
            failures.append("search returned nothing for the semantic query")
        else:
            top = results["results"][0]
            if top["template_id"] != str(template_id):
                failures.append(
                    f"search ranked {top['title']!r} first, expected the document just uploaded"
                )
            if not top["match_explanation"]:
                failures.append("the top hit carries no match explanation")
            if top["scores"]["vector_rank"] is None:
                failures.append("the top hit was not found by the vector half at all")

    finally:
        print("\ncleaning up ...")
        row = _row("select storage_key from template_versions where id = :i", {"i": str(version_id)}) if version_id else None
        storage_key = row[0] if row else None
        _cleanup(template_id, version_id, job_id, storage_key)
        server.terminate()
        try:
            server.wait(timeout=15)
        except Exception:  # noqa: BLE001 - best effort
            server.kill()

    print()
    if failures:
        print(f"search api: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("search api: PASS -- uploaded, enriched, persisted and found by meaning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
