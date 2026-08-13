"""End-to-end ingestion against the real API, RDS and S3. Needs a real `.env`.

    uv run python scripts/check_ingestion_api.py [--keep]

Named `check_` rather than `test_` to match `check_db.py` / `check_s3.py`: the
`test_` scripts run offline against files on disk, these need live credentials.

This is Track A's definition of done, measured rather than asserted:

  upload a MOM through the API, poll the job, and get back a fingerprint, a
  house-pattern match, and every detected region persisted with `region_id`s
  that survive a re-detect -- in under 40s, without blocking the request.

It starts a real uvicorn server rather than using `TestClient` on purpose.
`TestClient` runs `BackgroundTasks` inside the request, so it can prove the flow
but never that the upload returned *before* ingestion finished -- which is the
whole reason the endpoint answers 202. With a real server the 202 latency and
the job's own duration are two separate measurements.

Cleans up after itself: the template, its version, its schema, its regions, the
job row and the S3 object are all removed, because this runs against the shared
database. Pass `--keep` to leave them for inspection.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

# Deliberately the standard library rather than httpx or requests. This script
# would otherwise be the only thing in the repo needing a dependency that is in
# neither `pyproject.toml` nor `uv.lock` -- which is how `python-docx` once
# reached `main` declared but unlocked, passing for everyone who happened to
# have it installed (working agreement §5).
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _send(request: urllib.request.Request, timeout: float) -> tuple[int, object]:
    """Send a request, returning (status, decoded JSON). Never raises on 4xx/5xx.

    Proxies are bypassed explicitly: on a corporate machine `http_proxy` is set,
    and routing a call to 127.0.0.1 through Zscaler hangs rather than failing.
    """
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, (json.loads(raw) if raw else None)
        except ValueError:
            return exc.code, {"detail": raw[:400].decode("utf-8", "replace")}


def _get_json(url: str, timeout: float = 30) -> tuple[int, object]:
    return _send(urllib.request.Request(url, method="GET"), timeout)


def _post_file(
    url: str, filename: str, data: bytes, mime: str, timeout: float = 120
) -> tuple[int, object]:
    """POST one file as multipart/form-data under the field name `file`."""
    boundary = f"----TrackACheck{uuid.uuid4().hex}"
    body = b"".join(
        (
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        )
    )
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    return _send(request, timeout)

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT.parent / "Files"
DEFAULT_SAMPLE = "MOM Sample.xlsx"

MIME_BY_SUFFIX = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# What each document is known to declare about itself, asserted through the API
# rather than in-process. The MOM has no house pattern -- it is a single-sheet
# form with no History sheet -- and that absence is as much a fact to check as
# BFL's presence, because harvesting must not invent one.
EXPECTED: dict[str, dict[str, object]] = {
    "MOM Sample.xlsx": {
        "form_id": "YMSLI-F-MOM",
        "house_pattern": None,
        "in_doc_version": None,
        "merged_ranges": 27,
        "sensitivity_label": True,
        "regions": 11,
    },
    "BFL Sample.xlsx": {
        "form_id": None,
        "house_pattern": "ymsli_cover_history_instruction",
        "in_doc_version": "1",
        "regions": 10,
    },
    "BRD Sample.docx": {
        "form_id": None,
        "house_pattern": "ymsli_revision_block",
        "in_doc_version": "1.0",
        "regions": 61,
    },
}

# Plan §6's budget for ingestion, and the number in Track A's definition of done.
INGESTION_BUDGET_S = 40.0
# A 202 that took this long would mean the work had not really been deferred.
UPLOAD_LATENCY_BUDGET_S = 10.0
POLL_INTERVAL_S = 0.4
SERVER_START_TIMEOUT_S = 60.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ},
    )


def _wait_for_health(base: str, server: subprocess.Popen) -> bool:
    deadline = time.monotonic() + SERVER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if server.poll() is not None:
            print("server exited during startup:")
            print((server.stdout.read() if server.stdout else "")[-2000:])
            return False
        try:
            if _get_json(f"{base}/health", timeout=3)[0] == 200:
                return True
        except OSError:
            time.sleep(0.4)
    return False


def _cleanup(template_id: uuid.UUID | None, version_id: uuid.UUID | None, job_id: uuid.UUID | None, storage_key: str | None) -> None:
    from app.db.session import SessionLocal
    from app.storage.s3 import delete_file

    if storage_key:
        try:
            delete_file(storage_key)
            print(f"  removed s3 object {storage_key}")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING could not remove s3 object {storage_key}: {exc}")

    db = SessionLocal()
    try:
        if job_id:
            db.execute(text("delete from jobs where id = :i"), {"i": str(job_id)})
        if template_id:
            # current_version_id -> template_versions.id has to let go before the
            # cascade can take the versions with it.
            db.execute(
                text("update templates set current_version_id = null where id = :i"),
                {"i": str(template_id)},
            )
            db.execute(text("delete from templates where id = :i"), {"i": str(template_id)})
        db.commit()
        print(f"  removed template {template_id} and everything cascading from it")
    finally:
        db.close()


def _db_counts(version_id: uuid.UUID) -> dict[str, int]:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return {
            "document_schemas": db.execute(
                text("select count(*) from document_schemas where version_id = :v"),
                {"v": str(version_id)},
            ).scalar_one(),
            "document_regions": db.execute(
                text("select count(*) from document_regions where version_id = :v"),
                {"v": str(version_id)},
            ).scalar_one(),
        }
    finally:
        db.close()


def main() -> int:
    keep = "--keep" in sys.argv
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--")] or [DEFAULT_SAMPLE]
    if len(names) > 1:
        print("one sample at a time; pass a single filename from ../Files/")
        return 1
    sample_name = names[0]
    sample = FILES_DIR / sample_name
    expected = EXPECTED.get(sample_name, {})
    mime = MIME_BY_SUFFIX.get(sample.suffix.lower())
    if mime is None:
        print(f"unsupported sample type: {sample.suffix}")
        return 1
    if not sample.exists():
        print(f"sample not found: {sample}")
        return 1
    if not (ROOT / ".env").exists():
        print(".env not found -- this script needs real RDS and S3 credentials")
        return 1

    from app.db.session import masked_url

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"database: {masked_url()}")
    print(f"starting uvicorn on {base} ...")
    server = _start_server(port)

    failures: list[str] = []
    template_id = version_id = job_id = None
    storage_key = None

    try:
        if not _wait_for_health(base, server):
            print("server did not become healthy")
            return 1
        print("server healthy")
        print()

        # ── upload ───────────────────────────────────────────────────────
        data = sample.read_bytes()
        # Named so a row left behind by a failed run is obvious in the shared
        # database, and unique so repeat runs don't collide on the storage key.
        filename = f"{sample.stem} (track-a check {uuid.uuid4().hex[:8]}){sample.suffix}"
        started = time.monotonic()
        status_code, body = _post_file(
            f"{base}/api/v1/templates", filename, data, mime, timeout=120
        )
        upload_latency = time.monotonic() - started

        if status_code != 202:
            print(f"upload returned {status_code}: {body}")
            return 1
        template_id = uuid.UUID(body["template_id"])
        version_id = uuid.UUID(body["version_id"])
        job_id = uuid.UUID(body["job_id"])
        print(f"POST /templates -> 202 in {upload_latency * 1000:.0f}ms  status={body['status']!r}")
        print(f"  template {template_id}")
        print(f"  version  {version_id}")
        print(f"  job      {job_id}")
        if body["status"] != "ingesting":
            failures.append(f"202 status was {body['status']!r}, want 'ingesting'")
        if upload_latency > UPLOAD_LATENCY_BUDGET_S:
            failures.append(
                f"the 202 took {upload_latency:.1f}s -- ingestion is not really deferred"
            )

        # ── poll ─────────────────────────────────────────────────────────
        print()
        print("polling the job ...")
        poll_started = time.monotonic()
        seen_stages: list[str] = []
        payload: dict = {}
        while True:
            elapsed = time.monotonic() - poll_started
            status_code, payload = _get_json(
                f"{base}/api/v1/templates/{template_id}/ingestion/{job_id}", timeout=30
            )
            if status_code != 200:
                failures.append(f"job poll returned {status_code}: {payload}")
                break
            stage = payload.get("stage")
            if stage and stage not in seen_stages:
                seen_stages.append(stage)
                print(f"  {elapsed:5.1f}s  {payload['status']:<10} {stage:<12} {payload['progress']:3d}%")
            if payload["status"] in ("succeeded", "failed"):
                break
            if elapsed > INGESTION_BUDGET_S:
                failures.append(f"ingestion still {payload['status']} after {elapsed:.0f}s")
                break
            time.sleep(POLL_INTERVAL_S)
        ingestion_seconds = time.monotonic() - poll_started

        if payload.get("status") != "succeeded":
            failures.append(f"job ended {payload.get('status')!r}: {payload.get('error')}")
        print(f"  job {payload.get('status')} in {ingestion_seconds:.1f}s (stages: {' -> '.join(seen_stages)})")

        # ── what the job reported ────────────────────────────────────────
        print()
        fingerprint = payload.get("fingerprint") or {}
        print(f"  fingerprint          {len(fingerprint.get('package_parts') or [])} package parts, "
              f"{fingerprint.get('merged_ranges')} merges, "
              f"sensitivity_label={fingerprint.get('sensitivity_label')}")
        print(f"  regions_detected     {payload.get('regions_detected')} "
              f"({payload.get('regions_writable')} writable)")
        print(f"  counts_by_kind       {payload.get('counts_by_kind')}")
        print(f"  form_id              {payload.get('form_id')!r}")
        print(f"  house_pattern        {payload.get('house_pattern_matched')!r}")
        print(f"  in_doc_version       {payload.get('in_doc_version')!r}")
        print(f"  region_ids_stable    {payload.get('region_ids_stable')}")
        print(f"  warnings             {payload.get('warnings')}")

        if not fingerprint.get("package_parts"):
            failures.append("the job reported no fingerprint")
        # Asserted from the table, so an absent house pattern is checked as
        # firmly as a present one: harvesting must not invent what isn't there.
        for field, want in (
            ("form_id", expected.get("form_id", ...)),
            ("house_pattern_matched", expected.get("house_pattern", ...)),
            ("in_doc_version", expected.get("in_doc_version", ...)),
            ("regions_detected", expected.get("regions", ...)),
        ):
            if want is ...:
                continue
            got = payload.get(field)
            if got != want:
                failures.append(f"{field} came back {got!r}, want {want!r}")
        for field in ("merged_ranges", "sensitivity_label"):
            want = expected.get(field, ...)
            if want is not ... and fingerprint.get(field) != want:
                failures.append(
                    f"fingerprint.{field} came back {fingerprint.get(field)!r}, want {want!r}"
                )
        if payload.get("region_ids_stable") is not True:
            failures.append("region_ids were not stable across the re-detect")
        if ingestion_seconds > INGESTION_BUDGET_S:
            failures.append(f"ingestion took {ingestion_seconds:.0f}s, budget is {INGESTION_BUDGET_S:.0f}s")

        # ── the persisted schema ─────────────────────────────────────────
        print()
        status_code, schema = _get_json(
            f"{base}/api/v1/templates/{template_id}/regions", timeout=30
        )
        if status_code != 200:
            failures.append(f"GET /regions returned {status_code}: {schema}")
        else:
            print(f"GET /regions -> {schema['regions_detected']} regions "
                  f"({schema['regions_writable']} writable), detector={schema['detector_version']}")
            print(f"  form_id={schema['form_id']!r} house_pattern={schema['house_pattern']!r} "
                  f"in_doc_version={schema['in_doc_version']!r}")

            # The persisted region_ids must equal a fresh local detection's --
            # they are the primary key every stored Change Spec addresses, so a
            # round trip through JSONB that reordered or renamed one would break
            # specs silently.
            from app.ingestion.detect import detect

            detected_ids = [region.region_id for region in detect(data, sample.suffix.lstrip(".")).regions]
            persisted_ids = [region["region_id"] for region in schema["regions"]]
            if persisted_ids != detected_ids:
                failures.append(
                    f"persisted region_ids differ from a fresh detect:\n"
                    f"      persisted {persisted_ids[:8]}\n      detected  {detected_ids[:8]}"
                )
            else:
                print(f"  region_ids identical to a fresh local detect ({len(persisted_ids)} ids)")

            # `notes` is what the compiler bridge reads to act on a region, so a
            # table that came back without its columns is persisted but unusable.
            tables = [
                r for r in schema["regions"] if r["kind"] in ("table_loop", "table_data", "history")
            ]
            if not tables:
                print("  (no table regions in this document)")
            else:
                for table in tables:
                    notes = table.get("notes") or {}
                    if not notes.get("columns"):
                        failures.append(
                            f"{table['region_id']}: `columns` notes did not survive persistence"
                        )
                    # Only an *empty* table carries an explicit insertion point.
                    # A populated xlsx `table_data` or `history` doesn't: the
                    # compiler derives `at_row` from the locator's last row
                    # instead (`region_ops.add_table_rows`), so requiring one
                    # here would be asserting a contract that doesn't exist.
                    elif table["kind"] == "table_loop" and (
                        notes.get("insert_at_row") is None and notes.get("template_row") is None
                    ):
                        failures.append(
                            f"{table['region_id']}: an empty table kept no insertion point"
                        )
                    elif notes.get("first_data_row") is None:
                        failures.append(
                            f"{table['region_id']}: `first_data_row` did not survive persistence"
                        )
                print(
                    f"  {len(tables)} table region(s) kept their notes, e.g. "
                    f"{tables[0]['region_id']}: {len(tables[0]['notes']['columns'])} columns"
                )

            protected = [r for r in schema["regions"] if r["protected"]]
            if any(r["editable"] for r in protected):
                failures.append("a persisted protected region came back editable")
            else:
                print(f"  {len(protected)} protected region(s) persisted, none editable")

        counts = _db_counts(version_id)
        print(f"  rows in the database: {counts}")
        if counts["document_schemas"] != 1:
            failures.append(f"document_schemas has {counts['document_schemas']} rows for this version, want 1")
        if counts["document_regions"] != payload.get("regions_detected"):
            failures.append(
                f"document_regions has {counts['document_regions']} rows, "
                f"job reported {payload.get('regions_detected')}"
            )

        # ── re-ingesting must replace, not collide ───────────────────────
        # `UNIQUE (version_id, region_id)` means a second pass has to delete
        # first; this is the assertion that `persist` is idempotent.
        print()
        print("re-ingesting the same version (idempotency of persist) ...")
        from app.db.session import SessionLocal
        from app.ingestion.pipeline import run_ingestion
        from app.models.template import Template
        from app.models.template_version import TemplateVersion

        db = SessionLocal()
        try:
            template = db.get(Template, template_id)
            version = db.get(TemplateVersion, version_id)
            run_ingestion(db, template, version, data)
            db.commit()
            after = _db_counts(version_id)
            print(f"  rows after re-ingest: {after}")
            if after != counts:
                failures.append(f"re-ingest changed row counts {counts} -> {after}")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failures.append(f"re-ingesting the same version failed: {type(exc).__name__}: {exc}")
        finally:
            db.close()

        storage_key = None
        db = SessionLocal()
        try:
            storage_key = db.execute(
                text("select storage_key from template_versions where id = :i"),
                {"i": str(version_id)},
            ).scalar()
        finally:
            db.close()

    finally:
        print()
        if keep:
            print(f"--keep: leaving template {template_id} in place")
        elif template_id is not None:
            print("cleaning up (this runs against the shared database) ...")
            try:
                _cleanup(template_id, version_id, job_id, storage_key)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARNING cleanup failed: {exc}")
                print(f"  remove by hand: template {template_id}, job {job_id}, s3 {storage_key}")
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()

    print()
    if failures:
        print(f"ingestion API: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"ingestion API: PASS -- 202 in {upload_latency * 1000:.0f}ms, "
        f"ingested in {ingestion_seconds:.1f}s (budget {INGESTION_BUDGET_S:.0f}s), "
        f"schema and regions persisted and re-readable"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
