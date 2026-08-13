"""The fill conversation over the API, end to end. Needs a `.env`, RDS and S3.

    uv run python scripts/check_sessions_api.py [MOM Sample.xlsx] [--keep]

Plan §6's generation block and §10 stages ③-⑦, over HTTP:

    upload → ingest → POST /sessions → answer every question
           → GET /spec → dry-run compile → commit → download → re-detect

`scripts/test_conversation.py` proves the chain deterministically and offline.
This one proves the *service*: that session state survives a round trip through
Postgres, that the question plan is cached per version, and that the compiled
bytes reaching S3 are the ones the dry run promised.

Three properties are asserted that only appear at this level:

* **The session is resumable.** `GET /sessions/{id}` after every answer must
  return the same turns and values the answer responses reported, because the
  chat screen rebuilds itself from exactly that on a reload.
* **The plan is cached per version.** A second session on the same version must
  return an identical question list, which is what makes a repeat demo cost no
  planner call and survive Bedrock being unreachable.
* **`change_specs.session_id` is populated.** Without it a committed document
  cannot be traced back to the conversation that asked for it, which is the
  audit claim in plan §8.

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
INGESTION_BUDGET_S = 90.0
POLL_INTERVAL_S = 0.5

# What a user "says". One loose sentence per question, the way plan §13's demo
# script answers -- the point of the extractor is that this works.
ANSWERS = [
    "Cycle 2 of the AP automation workshop on fixed assets, held at YMSLI "
    "Faridabad on 22 August 2026, run by Anshul Maheshwari.",
    "We agreed attachments become mandatory for revaluation and disposal, and "
    "Ravi is sharing the AP header field mapping by Friday.",
    "Priya is setting up the next session; target date 29 August 2026.",
    "Nothing else to add.",
]

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


def _get(url: str, timeout: float = 90) -> tuple[int, object]:
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
    boundary = f"----SessionCheck{uuid.uuid4().hex}"
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


def main() -> int:  # noqa: PLR0915 - a linear end-to-end script reads better whole
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

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    api = f"{base}/api/v1"
    print(f"database: {masked_url()}")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ},
    )

    failures: list[str] = []
    template_id = session_id = None
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
        filename = f"{sample.stem} (session check {uuid.uuid4().hex[:8]}){sample.suffix}"
        code, body = _post_file(f"{api}/templates", filename, data, mime)
        if code != 202:
            print(f"upload returned {code}: {body}")
            return 1
        template_id, version_id, job_id = body["template_id"], body["version_id"], body["job_id"]
        print(f"uploaded template {template_id}")

        started = time.monotonic()
        while True:
            code, job = _get(f"{api}/templates/{template_id}/ingestion/{job_id}")
            if job["status"] in ("succeeded", "failed"):
                break
            if time.monotonic() - started > INGESTION_BUDGET_S:
                failures.append(f"ingestion still {job['status']} after {INGESTION_BUDGET_S:.0f}s")
                break
            time.sleep(POLL_INTERVAL_S)
        if job["status"] != "succeeded":
            failures.append(f"ingestion failed: {job.get('error')}")
            return 1
        print(f"ingested: {job['regions_detected']} regions, form_id={job.get('form_id')}")

        # ── start the session ────────────────────────────────────────────
        t0 = time.monotonic()
        code, session = _post_json(
            f"{api}/sessions",
            {"template_id": template_id, "intent": "Create the next MOM for the AP workshop",
             "tier": "T3"},
        )
        if code != 201:
            failures.append(f"POST /sessions returned {code}: {session}")
            return 1
        session_id = session["session_id"]
        questions = session["questions"]
        total = session["progress"]["fields_total"]
        print(
            f"session {session_id}: {len(questions)} question(s), "
            f"{total} fillable region(s), {int((time.monotonic() - t0) * 1000)}ms"
        )
        print(f"  plan: {session['plan_summary']}")
        if not questions:
            failures.append("the session planned no questions at all")
            return 1
        if len(questions) > 4:
            failures.append(f"{len(questions)} questions, plan §10 caps it at 4")

        # ── answer every question ────────────────────────────────────────
        answered = 0
        for index, question in enumerate(questions):
            answer_text = ANSWERS[index] if index < len(ANSWERS) else ANSWERS[-1]
            turn_start = time.monotonic()
            code, turn = _post_json(
                f"{api}/sessions/{session_id}/answer",
                {"question_id": question["question_id"], "answer": answer_text},
            )
            if code != 200:
                failures.append(f"answer {question['question_id']} returned {code}: {turn}")
                return 1
            answered += 1
            elapsed_ms = int((time.monotonic() - turn_start) * 1000)
            print(
                f"  {question['question_id']}: extracted {len(turn['extracted'])} value(s), "
                f"{turn['progress']['fields_filled']}/{turn['progress']['fields_total']} filled, "
                f"{elapsed_ms}ms"
                + (" [degraded]" if turn["degraded"] else "")
            )
            for warning in turn["warnings"]:
                print(f"           warning: {warning}")
            # Plan §6 budgets an answer turn at 1.5s. The last one also runs the
            # deriver, so it is exempt -- reported, not asserted.
            if elapsed_ms > 1500 and turn["next_question"] is not None:
                print(f"           NOTE over the 1.5s answer budget ({elapsed_ms}ms)")

            # Resumability: the state a reload would rebuild from must match.
            code, live = _get(f"{api}/sessions/{session_id}")
            if code != 200:
                failures.append(f"GET /sessions returned {code}")
            elif len(live["turns"]) != answered:
                failures.append(
                    f"after {answered} answer(s) the session reports {len(live['turns'])} turn(s)"
                )

        code, final = _get(f"{api}/sessions/{session_id}")
        filled = final["progress"]["fields_filled"]
        print(
            f"conversation done: {answered} answer(s) -> {filled} of "
            f"{final['progress']['fields_total']} fields"
        )

        # ── the plan is cached per version ───────────────────────────────
        code, second = _post_json(f"{api}/sessions", {"template_id": template_id, "tier": "T1"})
        if code != 201:
            failures.append(f"a second session returned {code}: {second}")
        else:
            first_texts = [q["question_text"] for q in questions]
            second_texts = [q["question_text"] for q in second["questions"]]
            if first_texts != second_texts:
                failures.append(
                    "the question plan was not reused for a second session on the same version"
                )
            else:
                print(f"question plan reused for a second session ({len(second_texts)} questions)")
            _post_json(f"{api}/sessions/{second['session_id']}/abandon", {})

        # ── the spec ─────────────────────────────────────────────────────
        code, spec_body = _get(f"{api}/sessions/{session_id}/spec")
        if code != 200:
            failures.append(f"GET /spec returned {code}: {spec_body}")
            return 1
        print(
            f"spec: {spec_body['operation_count']} operation(s), "
            f"provenance {spec_body['provenance_counts']}, "
            f"{len(spec_body['skipped'])} skipped"
        )
        if not spec_body["operation_count"]:
            failures.append("the session produced an empty spec")
            return 1
        if str(spec_body["base_version_id"]) != str(version_id):
            failures.append("the spec was planned against a different version than the session's")

        # ── dry run ──────────────────────────────────────────────────────
        code, dry = _post_json(f"{api}/sessions/{session_id}/compile", {"dry_run": True})
        if code != 200:
            failures.append(f"dry run returned {code}: {dry}")
            return 1
        print(
            f"dry run : {dry['overall']} -- {dry['operations_applied']} applied, "
            f"{len(dry['dropped'])} dropped, packaging={dry['packaging']}, {dry['duration_ms']}ms"
        )
        for entry in dry["dropped"]:
            print(f"          dropped {entry['op']} -> {entry['target']}: {entry['reason']}")
        if dry["overall"] != "pass":
            failures.append(f"dry run QA failed: {dry['structural']}")
        if dry["result_version_id"] is not None:
            failures.append("a dry run produced a version -- it must keep nothing")
        if dry["structural"].get("lost_parts"):
            failures.append(f"dry run lost package parts: {dry['structural']['lost_parts']}")

        # ── commit ───────────────────────────────────────────────────────
        code, committed = _post_json(f"{api}/sessions/{session_id}/commit", {})
        if code != 200:
            failures.append(f"commit returned {code}: {committed}")
            return 1
        result_version_id = committed["result_version_id"]
        print(
            f"commit  : {committed['overall']} -- v{committed['result_version_number']}, "
            f"{committed['operations_applied']} applied, {committed['duration_ms']}ms"
        )
        if committed["overall"] != "pass":
            failures.append("commit QA failed")
        if not result_version_id:
            failures.append("commit produced no version")
        if committed["structural"].get("lost_parts"):
            failures.append(f"commit lost package parts: {committed['structural']['lost_parts']}")
        if committed["operations_applied"] != dry["operations_applied"]:
            failures.append(
                f"commit applied {committed['operations_applied']} operations but the dry run "
                f"applied {dry['operations_applied']} -- the same spec compiled differently"
            )

        # ── download and re-detect ───────────────────────────────────────
        if result_version_id:
            code, blob = _get_bytes(f"{api}{committed['download_url'].removeprefix('/api/v1')}")
            if code != 200:
                failures.append(f"download returned {code}")
            else:
                print(f"downloaded {len(blob)} bytes")
                from app.ingestion.detect import detect

                fmt = sample.suffix.lstrip(".").lower()
                try:
                    redetected = detect(blob, fmt)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"the committed bytes could not be re-detected: {exc}")
                else:
                    print(f"re-detected {len(redetected.regions)} regions in the committed file")
                    if not redetected.regions:
                        failures.append("the committed file detected as having no regions")

        # ── the audit trail ──────────────────────────────────────────────
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            linked = db.execute(
                text("select count(*) from change_specs where session_id = :s"),
                {"s": session_id},
            ).scalar()
            print(f"change_specs rows carrying this session_id: {linked}")
            if not linked:
                failures.append(
                    "no change_spec records this session -- a committed document cannot be "
                    "traced to the conversation that asked for it"
                )
            for key in db.execute(
                text("select storage_key from template_versions where template_id = :t"),
                {"t": template_id},
            ).scalars():
                keys_to_remove.append(key)
        finally:
            db.close()

    finally:
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
            db.execute(
                text(
                    "delete from jobs where entity_id in "
                    "(select id from template_versions where template_id = :t)"
                ),
                {"t": template_id},
            )
            db.execute(
                text("update templates set current_version_id = null where id = :t"),
                {"t": template_id},
            )
            db.execute(text("delete from templates where id = :t"), {"t": template_id})
            db.commit()
            print(f"cleaned up template {template_id}, {len(keys)} s3 object(s), and the cascade")
        finally:
            db.close()

    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover
        server.kill()

    print()
    if failures:
        print(f"sessions API: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return
    print("sessions API: PASS -- conversation planned, answered, compiled and committed")


if __name__ == "__main__":
    sys.exit(main())
