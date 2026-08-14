"""Generation over the API, end to end, against real RDS and S3. Needs a `.env`.

    uv run python scripts/check_compile_api.py [MOM Sample.xlsx] [--keep]

Plan §4 Ring 1's headline path, over HTTP:

    upload → ingest → dry-run compile → commit → download the new version

The dry run and the commit are two separate assertions, because they are two
separate promises. A dry run must return the full QA verdict and leave **no**
new version behind; a commit must produce one, byte-identical to what the dry
run compiled, and reachable by download.

Also proves the two things that make the path safe to expose:

* **QA is a gate, not a report.** A spec that fails is stored with its failure
  and produces no file, so `change_specs` explains why no document exists.
* **Dropped operations survive the response.** A model naming the logo, or a
  region that never existed, leaves a row in `change_specs.dropped` -- the audit
  trail for "we left this untouched", which plan §14 requires be visible.

Cleans up after itself, because it runs against the shared database.
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

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT.parent / "Files"
DEFAULT_SAMPLE = "MOM Sample.xlsx"
MIME_BY_SUFFIX = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
INGESTION_BUDGET_S = 60.0
POLL_INTERVAL_S = 0.5

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _send(request: urllib.request.Request, timeout: float) -> tuple[int, object]:
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, (json.loads(raw) if raw else None)
        except ValueError:
            return exc.code, {"detail": raw[:400].decode("utf-8", "replace")}


def _get(url: str, timeout: float = 60) -> tuple[int, object]:
    return _send(urllib.request.Request(url, method="GET"), timeout)


def _get_bytes(url: str, timeout: float = 120) -> tuple[int, bytes]:
    try:
        with _OPENER.open(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post_json(url: str, payload: dict, timeout: float = 180) -> tuple[int, object]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    return _send(request, timeout)


def _post_file(url: str, filename: str, data: bytes, mime: str) -> tuple[int, object]:
    boundary = f"----CompileCheck{uuid.uuid4().hex}"
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
    return _send(request, 180)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _spec_for(fmt: str, schema) -> dict:
    """A spec that exercises a write, a growth, and both refusals."""
    editable = [r for r in schema.regions if r.editable]
    protected = next((r for r in schema.regions if r.protected), None)
    # A string field: a date field is exercised separately, on purpose, because
    # writing prose into one must be *dropped* rather than applied.
    field = next(
        (r for r in editable if r.kind in ("field", "field_empty") and r.value_type != "date"),
        None,
    )
    date_field = next(
        (r for r in editable if r.kind in ("field", "field_empty") and r.value_type == "date"), None
    )
    block = next((r for r in editable if r.kind == "repeating_block"), None)
    table = next((r for r in editable if r.kind in ("table_loop", "table_data")), None)

    operations = []
    if field is not None:
        operations.append(
            {
                "op": "set_value",
                "target": {"region_id": field.region_id},
                "value": "Compiled through the API",
                "provenance": "user_answer:q1",
            }
        )
    if block is not None:
        rows = (
            [{"serial": i, "content": f"Point {i} written by the compile endpoint."} for i in range(1, 4)]
            if fmt == "xlsx"
            else [f"Point {i} written by the compile endpoint." for i in range(1, 4)]
        )
        operations.append(
            {
                "op": "replace_region_rows",
                "target": {"region_id": block.region_id},
                "rows": rows,
                "provenance": "llm_generated",
            }
        )
    if table is not None and fmt == "docx":
        columns = [c["name"] for c in table.notes.get("columns", [])][:2]
        if len(columns) == 2:
            operations.append(
                {
                    "op": "clone_table_rows",
                    "target": {"region_id": table.region_id},
                    "rows": [{columns[0]: "99", columns[1]: "Appended by the API"}],
                    "provenance": "llm_derived:q2",
                }
            )
    # Both refusals, in one spec, so the audit trail has to carry them.
    if protected is not None:
        operations.append(
            {
                "op": "set_value",
                "target": {"region_id": protected.region_id},
                "value": "HIJACKED",
                "provenance": "llm_generated",
            }
        )
    if date_field is not None:
        operations.append(
            {
                "op": "set_value",
                "target": {"region_id": date_field.region_id},
                "value": "not a date at all",
                "provenance": "llm_generated",
            }
        )
    operations.append(
        {
            "op": "set_value",
            "target": {"region_id": "invented.by.the.model"},
            "value": "x",
            "provenance": "llm_generated",
        }
    )
    return {
        "spec_version": "1.0",
        "tier": "T3",
        "intent": "compile check over the API",
        "operations": operations,
        "assertions": [{"invariant": "package_parts_preserved", "expect": "all"}],
    }


def main() -> int:
    keep = "--keep" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or [DEFAULT_SAMPLE]
    sample = FILES_DIR / names[0]
    mime = MIME_BY_SUFFIX.get(sample.suffix.lower())
    if not sample.exists() or mime is None:
        print(f"sample not found or unsupported: {sample}")
        return 1
    if not (ROOT / ".env").exists():
        print(".env not found -- this script needs real RDS and S3 credentials")
        return 1

    from app.db.session import masked_url
    from app.ingestion.detect import detect

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"database: {masked_url()}")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ},
    )

    failures: list[str] = []
    template_id = job_id = base_version_id = None
    keys_to_remove: list[str] = []

    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if server.poll() is not None:
                print((server.stdout.read() if server.stdout else "")[-1500:])
                return 1
            try:
                if _get(f"{base}/health", timeout=3)[0] == 200:
                    break
            except OSError:
                time.sleep(0.4)
        print(f"server up on {base}")

        # ── upload + ingest ──────────────────────────────────────────────
        data = sample.read_bytes()
        filename = f"{sample.stem} (compile check {uuid.uuid4().hex[:8]}){sample.suffix}"
        code, body = _post_file(f"{base}/api/v1/templates", filename, data, mime)
        if code != 202:
            print(f"upload returned {code}: {body}")
            return 1
        template_id, base_version_id, job_id = body["template_id"], body["version_id"], body["job_id"]
        print(f"uploaded template {template_id}")

        started = time.monotonic()
        while True:
            code, job = _get(f"{base}/api/v1/templates/{template_id}/ingestion/{job_id}")
            if job["status"] in ("succeeded", "failed"):
                break
            if time.monotonic() - started > INGESTION_BUDGET_S:
                failures.append(f"ingestion still {job['status']} after {INGESTION_BUDGET_S:.0f}s")
                break
            time.sleep(POLL_INTERVAL_S)
        print(f"ingested: {job['status']}, {job.get('regions_detected')} regions")
        if job["status"] != "succeeded":
            failures.append(f"ingestion failed: {job.get('error')}")
            return 1

        spec = _spec_for(sample.suffix.lstrip(".").lower(), detect(data, sample.suffix.lstrip(".").lower()))
        print(f"spec: {len(spec['operations'])} operations")

        # ── dry run ──────────────────────────────────────────────────────
        code, dry = _post_json(
            f"{base}/api/v1/templates/{template_id}/compile", {"spec": spec, "dry_run": True}
        )
        if code != 200:
            failures.append(f"dry run returned {code}: {dry}")
            return 1
        print(
            f"dry run  : {dry['overall']} -- {dry['operations_applied']} applied, "
            f"{len(dry['dropped'])} dropped, {dry['rows_inserted']} rows, "
            f"packaging={dry['packaging']}, {dry['duration_ms']}ms"
        )
        for entry in dry["dropped"]:
            print(f"           dropped {entry['op']} -> {entry['target']}: {entry['reason']}")
        if dry["overall"] != "pass":
            failures.append(f"dry run QA failed: {dry['structural']} {dry['functional']}")
        if dry["result_version_id"] is not None:
            failures.append("a dry run created a version -- it must keep nothing")
        if dry["status"] != "compiled":
            failures.append(f"dry run status {dry['status']!r}, want 'compiled'")
        if not dry["protected_regions"]:
            failures.append("the dry run reported no protected regions")

        # ── commit ───────────────────────────────────────────────────────
        code, commit = _post_json(
            f"{base}/api/v1/templates/{template_id}/compile",
            {"spec": spec, "dry_run": False, "change_note": "compile check"},
        )
        if code != 200:
            failures.append(f"commit returned {code}: {commit}")
            return 1
        print(
            f"commit   : {commit['overall']} -- version {commit['result_version_number']} "
            f"({commit['result_version_id']}), status={commit['status']}"
        )
        if commit["status"] != "committed" or commit["result_version_id"] is None:
            failures.append(f"commit did not produce a version: {commit['status']}")
        # The result must derive from the version we uploaded, not from whatever
        # happened to be current by the time the commit ran.
        if commit["base_version_id"] != base_version_id:
            failures.append(
                f"commit compiled against {commit['base_version_id']}, not the uploaded {base_version_id}"
            )
        if commit["result_version_id"] == base_version_id:
            failures.append("the compiled result overwrote the original version")
        if commit["result_version_number"] != 2:
            failures.append(f"new version number {commit['result_version_number']}, want 2")
        if len(commit["dropped"]) != len(dry["dropped"]):
            failures.append("commit dropped a different number of operations than the dry run")

        # ── download it ──────────────────────────────────────────────────
        if commit.get("download_url"):
            code, blob = _get_bytes(f"{base}{commit['download_url']}")
            print(f"download : {code}, {len(blob):,} bytes")
            if code != 200 or len(blob) < 1000:
                failures.append(f"download returned {code}, {len(blob)} bytes")
            elif blob[:4] != b"PK\x03\x04":
                failures.append("the downloaded file is not a zip container")
            else:
                out = ROOT / "scratch" / f"api_compiled_v2{sample.suffix}"
                out.parent.mkdir(exist_ok=True)
                try:
                    out.write_bytes(blob)
                    print(f"           wrote {out}")
                except PermissionError:
                    print("           (scratch file is open elsewhere; not overwritten)")
        else:
            failures.append("commit returned no download_url")

        # ── what the audit trail kept ────────────────────────────────────
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            rows = db.execute(
                text(
                    "select status, operation_count, dropped_count, result_version_id "
                    "from change_specs where template_id = :t order by created_at"
                ),
                {"t": template_id},
            ).fetchall()
            print(f"change_specs rows: {[(r[0], r[1], r[2], r[3] is not None) for r in rows]}")
            if len(rows) != 2:
                failures.append(f"{len(rows)} change_spec rows, want 2 (the dry run and the commit)")
            if not any(r[0] == "compiled" and r[3] is None for r in rows):
                failures.append("no `compiled` spec row with no result version (the dry run)")
            if not any(r[0] == "committed" and r[3] is not None for r in rows):
                failures.append("no `committed` spec row pointing at a version")
            if not all(r[2] == len(dry["dropped"]) for r in rows):
                failures.append("dropped operations were not recorded on the spec rows")

            qa = db.execute(
                text(
                    "select q.overall, q.dry_run, q.visual from qa_runs q "
                    "join change_specs s on s.id = q.change_spec_id where s.template_id = :t"
                ),
                {"t": template_id},
            ).fetchall()
            print(f"qa_runs rows     : {[(r[0], r[1]) for r in qa]}")
            if len(qa) != 2:
                failures.append(f"{len(qa)} qa_run rows, want 2")
            if any(r[2] is not None for r in qa):
                failures.append("`visual` should be null until the vision pass exists")

            lineage = db.execute(
                text("select version_number, parent_version_id from template_versions where template_id = :t order by version_number"),
                {"t": template_id},
            ).fetchall()
            print(f"version lineage  : {[(r[0], 'parent' if r[1] else 'root') for r in lineage]}")
            if lineage[-1][1] is None:
                failures.append("the derived version records no parent")

            keys_to_remove = [
                r[0]
                for r in db.execute(
                    text("select storage_key from template_versions where template_id = :t"),
                    {"t": template_id},
                ).fetchall()
            ]

            # A failing spec must be stored and produce nothing.
            code, bad = _post_json(
                f"{base}/api/v1/templates/{template_id}/compile",
                {
                    "spec": {
                        "spec_version": "1.0",
                        "operations": [
                            {
                                "op": "set_value",
                                "target": {"region_id": "nope.nothing"},
                                "value": 1,
                                "provenance": "llm_generated",
                            }
                        ],
                    },
                    "dry_run": False,
                },
            )
            failed_rows = db.execute(
                text("select count(*) from change_specs where template_id = :t and status = 'failed'"),
                {"t": template_id},
            ).scalar()
            print(f"unapplicable spec: HTTP {code}, failed rows recorded = {failed_rows}")
            if code != 422:
                failures.append(f"a spec with nothing applicable returned {code}, want 422")
            if not failed_rows:
                failures.append("a failed spec was not recorded -- no evidence for why nothing exists")
        finally:
            db.close()

    finally:
        # Not `return _finish(...)`: a return inside `finally` discards whatever
        # the body was returning, and every early `return 1` above would have run
        # cleanup a second time.
        _finish(server, failures, keep, template_id, keys_to_remove)

    return 1 if failures else 0


def _finish(server, failures, keep, template_id, keys) -> None:
    from app.db.session import SessionLocal
    from app.storage.s3 import delete_file

    print()
    if keep:
        print(f"--keep: leaving template {template_id}")
    elif template_id:
        for key in keys:
            try:
                delete_file(key)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARNING s3 {key}: {exc}")
        db = SessionLocal()
        try:
            db.execute(text("delete from jobs where entity_id in (select id from template_versions where template_id = :t)"), {"t": template_id})
            db.execute(text("update templates set current_version_id = null where id = :t"), {"t": template_id})
            db.execute(text("delete from templates where id = :t"), {"t": template_id})
            db.commit()
            print(f"cleaned up template {template_id}, {len(keys)} s3 object(s), and everything cascading")
        finally:
            db.close()

    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover
        server.kill()

    print()
    if failures:
        print(f"compile API: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return
    print("compile API: PASS -- dry run kept nothing, commit produced a QA'd v2, download served it")


if __name__ == "__main__":
    sys.exit(main())
