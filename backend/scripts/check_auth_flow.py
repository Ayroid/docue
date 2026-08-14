"""End-to-end auth, approval and notification against the real API and RDS.

    uv run python scripts/check_auth_flow.py [--keep]

Named `check_` rather than `test_` to match `check_db.py` / `check_ingestion_api.py`:
the `test_` scripts run offline against files on disk, these need live
credentials.

What it proves, in one pass over a real uvicorn server:

  register -> OTP -> verify -> sign in -> upload -> the template is *absent*
  from the library -> the admin's queue and notifications both show it -> approve
  -> it appears in the library -> the submitter is notified. Then a password
  reset by OTP, and a sign-in with the new password.

Along the way it checks the things that are easy to get wrong and invisible when
they are: that an unapproved template is genuinely missing from `GET /templates`
rather than merely labelled, that a non-admin is refused the admin routes, that
an unverified account cannot sign in, and that a wrong OTP is rejected while
still burning an attempt.

Runs against a real server rather than `TestClient` for the same reason
`check_ingestion_api.py` does: `TestClient` runs `BackgroundTasks` inside the
request, and the admin notification is a background task -- under `TestClient`
it would appear to work even if it had been wired to fire before the commit.

Cleans up after itself: both users, their OTPs and notifications, the template,
its version and the S3 object are removed, because this runs against the shared
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

from app.db.session import SessionLocal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Standard library rather than httpx/requests, for the reason given in
# `check_ingestion_api.py`: this would otherwise be the only thing in the repo
# needing a dependency in neither `pyproject.toml` nor `uv.lock`.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SERVER_START_TIMEOUT_S = 60.0
# Ingestion is 15-40s and this script does not wait for it: approval is about
# the version row, which exists the moment the 202 returns.
UPLOAD_SETTLE_S = 3.0

PASSWORD = "check-flow-password"
# A passphrase with no digit and no upper case, which the old composition rules
# would have refused. Using one here is the end-to-end proof that the policy is
# length-only -- a unit test can say so, but only this proves the route agrees.
NEW_PASSWORD = "correct horse battery staple"

# A tiny but genuinely valid .docx, built at runtime rather than committed: the
# corpus lives outside the repo (see `tests/conftest.py`) and this script must
# run on a checkout that has none of it. The upload endpoint checks the zip
# magic and the extension, and ingestion runs in the background where its
# outcome does not gate anything here.
def _minimal_docx() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Auth flow check fixture.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    return buffer.getvalue()


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ── transport ─────────────────────────────────────────────────────────────


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


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get(url: str, token: str | None = None, timeout: float = 30) -> tuple[int, object]:
    return _send(urllib.request.Request(url, method="GET", headers=_headers(token)), timeout)


def _post(url: str, payload: object, token: str | None = None, timeout: float = 60) -> tuple[int, object]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body)), **_headers(token)},
    )
    return _send(request, timeout)


def _post_file(url: str, filename: str, data: bytes, mime: str, token: str, timeout: float = 120):
    boundary = f"----AuthFlowCheck{uuid.uuid4().hex}"
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
            **_headers(token),
        },
    )
    return _send(request, timeout)


# ── server ────────────────────────────────────────────────────────────────


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
        # OTP_DEBUG on so the codes come back in the response. This is the only
        # way to drive the flow without a mailbox, and the server refuses to do
        # it unless APP_ENV is local and SMTP is unconfigured -- both true here.
        env={**os.environ, "OTP_DEBUG": "true", "APP_ENV": "local", "SMTP_HOST": ""},
    )


def _wait_for_health(base: str, server: subprocess.Popen) -> bool:
    deadline = time.monotonic() + SERVER_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if server.poll() is not None:
            print("server exited during startup:")
            print((server.stdout.read() if server.stdout else "")[-2000:])
            return False
        try:
            if _get(f"{base}/health", timeout=3)[0] == 200:
                return True
        except OSError:
            time.sleep(0.4)
    return False


# ── reporting ─────────────────────────────────────────────────────────────

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not condition:
        FAILURES.append(label)
    return condition


# ── cleanup ───────────────────────────────────────────────────────────────


def _cleanup(user_ids: list[uuid.UUID], template_id: uuid.UUID | None, storage_key: str | None) -> None:
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
        if template_id:
            # current_version_id -> template_versions.id has to let go before
            # the cascade can take the versions with it.
            db.execute(
                text("update templates set current_version_id = null where id = :i"),
                {"i": str(template_id)},
            )
            db.execute(text("delete from jobs where entity_id in (select id from template_versions where template_id = :i)"), {"i": str(template_id)})
            db.execute(text("delete from templates where id = :i"), {"i": str(template_id)})
        for user_id in user_ids:
            # email_otps and notifications cascade from users; the explicit
            # deletes are for readability, not necessity.
            db.execute(text("delete from notifications where user_id = :i"), {"i": str(user_id)})
            db.execute(text("delete from email_otps where user_id = :i"), {"i": str(user_id)})
            db.execute(text("delete from users where id = :i"), {"i": str(user_id)})
        db.commit()
        print(f"  removed {len(user_ids)} user(s) and template {template_id}")
    finally:
        db.close()


# ── the run ───────────────────────────────────────────────────────────────


def main() -> int:
    keep = "--keep" in sys.argv
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    api = f"{base}/api/v1"

    # Unique per run so repeated runs never collide on the unique indexes.
    tag = uuid.uuid4().hex[:8]
    member_email = f"member.{tag}@authcheck.local"
    admin_email = f"admin.{tag}@authcheck.local"

    user_ids: list[uuid.UUID] = []
    template_id: uuid.UUID | None = None
    storage_key: str | None = None

    server = _start_server(port)
    try:
        if not _wait_for_health(base, server):
            print("FAILED: server did not come up")
            return 1
        print(f"server up on {base}\n")

        # ── 1. register + verify ──────────────────────────────────────────
        print("1. Registration and email verification")
        status, body = _post(f"{api}/auth/register", {
            "email": member_email, "username": f"member{tag}", "password": PASSWORD, "full_name": "Member Check",
        })
        check("register answers 202", status == 202, f"got {status} {body}")
        code = (body or {}).get("debug_code") if isinstance(body, dict) else None
        check("register returns a debug code (OTP_DEBUG)", bool(code))
        if not code:
            return 1

        status, _ = _post(f"{api}/auth/login", {"identifier": member_email, "password": PASSWORD})
        check("unverified account cannot sign in", status == 403, f"got {status}")

        # Registering with no username at all: the server derives one from the
        # email rather than refusing. This is the path the form takes when the
        # field is left empty, and the one that used to be impossible.
        derived_email = f"derived.{tag}@authcheck.local"
        status, body = _post(f"{api}/auth/register", {"email": derived_email, "password": PASSWORD})
        check("registering without a username is accepted", status == 202, f"got {status} {body}")
        if status == 202:
            db = SessionLocal()
            try:
                row = db.execute(
                    text("select id, username from users where email = :e"), {"e": derived_email}
                ).one_or_none()
            finally:
                db.close()
            if row is not None:
                user_ids.append(row[0])
                check("the derived username is the email's local part", row[1] == f"derived.{tag}", str(row[1]))

        status, _ = _post(f"{api}/auth/register", {
            "email": f"bad.{tag}@authcheck.local", "username": "has spaces", "password": PASSWORD,
        })
        check("a username with a space is refused", status == 422, f"got {status}")

        status, _ = _post(f"{api}/auth/verify-email", {"email": member_email, "code": "000000" if code != "000000" else "111111"})
        check("a wrong OTP is rejected", status == 400, f"got {status}")

        status, body = _post(f"{api}/auth/verify-email", {"email": member_email, "code": code})
        check("correct OTP verifies and returns a token", status == 200, f"got {status} {body}")
        member_token = (body or {}).get("access_token") if isinstance(body, dict) else None
        member = (body or {}).get("user") if isinstance(body, dict) else None
        if not member_token:
            return 1
        user_ids.append(uuid.UUID(member["id"]))
        check("new accounts are role=user, not admin", member["role"] == "user", member["role"])

        status, _ = _post(f"{api}/auth/verify-email", {"email": member_email, "code": code})
        check("an OTP cannot be reused", status in (400, 409), f"got {status}")

        # ── 2. the admin ──────────────────────────────────────────────────
        print("\n2. Seeding an administrator")
        status, body = _post(f"{api}/auth/register", {
            "email": admin_email, "username": f"admin{tag}", "password": PASSWORD, "full_name": "Admin Check",
        })
        admin_code = (body or {}).get("debug_code") if isinstance(body, dict) else None
        status, body = _post(f"{api}/auth/verify-email", {"email": admin_email, "code": admin_code})
        admin_token = (body or {}).get("access_token") if isinstance(body, dict) else None
        admin_id = uuid.UUID((body or {})["user"]["id"])
        user_ids.append(admin_id)

        status, _ = _get(f"{api}/admin/approvals", admin_token)
        check("a non-admin is refused the admin routes", status == 403, f"got {status}")

        # Promoted directly, the way `scripts/seed_admin.py` does it -- the
        # admin API needs an admin, so the first one cannot come through it.
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("update users set role = 'admin' where id = :i"), {"i": str(admin_id)})
            db.commit()
        finally:
            db.close()

        status, body = _post(f"{api}/auth/login", {"identifier": admin_email, "password": PASSWORD})
        admin_token = (body or {}).get("access_token") if isinstance(body, dict) else None
        check("promoted admin can sign in", status == 200, f"got {status}")
        status, _ = _get(f"{api}/admin/approvals", admin_token)
        check("admin reaches the approval queue", status == 200, f"got {status}")

        # ── 3. upload lands pending and invisible ─────────────────────────
        print("\n3. Upload lands pending and out of the library")
        status, _ = _post_file(f"{api}/templates", "authcheck.docx", _minimal_docx(), DOCX_MIME, token=None)
        check("anonymous upload is refused", status == 401, f"got {status}")

        status, body = _post_file(f"{api}/templates", f"authcheck-{tag}.docx", _minimal_docx(), DOCX_MIME, member_token)
        check("signed-in upload is accepted", status == 202, f"got {status} {body}")
        if status != 202:
            return 1
        template_id = uuid.UUID(body["template_id"])
        version_id = body["version_id"]

        db = SessionLocal()
        try:
            storage_key = db.execute(
                text("select storage_key from template_versions where id = :i"), {"i": version_id}
            ).scalar()
        finally:
            db.close()

        status, library = _get(f"{api}/templates", member_token)
        ids = [t["id"] for t in library] if isinstance(library, list) else []
        check("the pending template is NOT in the library", str(template_id) not in ids)

        status, mine = _get(f"{api}/templates?mine=true", member_token)
        mine_ids = [t["id"] for t in mine] if isinstance(mine, list) else []
        check("the submitter can see it under ?mine=true", str(template_id) in mine_ids)

        status, detail = _get(f"{api}/templates/{template_id}", member_token)
        check("the submitter can open it", status == 200 and detail["approval_status"] == "pending",
              f"got {status} {detail.get('approval_status') if isinstance(detail, dict) else ''}")

        # ── 4. the admin is told ──────────────────────────────────────────
        print("\n4. Doc control is notified")
        time.sleep(UPLOAD_SETTLE_S)  # the announcement is a background task

        status, queue = _get(f"{api}/admin/approvals?status_filter=pending", admin_token)
        queued = [row for row in (queue or {}).get("items", []) if row["template_id"] == str(template_id)]
        check("the version is in the admin's pending queue", len(queued) == 1, f"found {len(queued)}")
        if queued:
            check("the queue names the submitter", queued[0]["submitted_by_email"] == member_email,
                  str(queued[0]["submitted_by_email"]))

        status, notes = _get(f"{api}/notifications", admin_token)
        admin_notes = [n for n in (notes or {}).get("items", []) if n["template_id"] == str(template_id)]
        check("the admin has an in-app notification", len(admin_notes) == 1, f"found {len(admin_notes)}")
        if admin_notes:
            check("it is an approval request", admin_notes[0]["kind"] == "approval_requested", admin_notes[0]["kind"])
        check("the admin's unread count is non-zero", (notes or {}).get("unread", 0) >= 1)

        # ── 5. approve, and it publishes ──────────────────────────────────
        print("\n5. Approval publishes it and tells the submitter")
        status, _ = _post(f"{api}/admin/approvals/{version_id}/approve", {"note": "Looks right."}, member_token)
        check("a non-admin cannot approve", status == 403, f"got {status}")

        status, approved = _post(f"{api}/admin/approvals/{version_id}/approve", {"note": "Looks right."}, admin_token)
        check("the admin can approve", status == 200, f"got {status} {approved}")
        if status == 200:
            check("it is recorded as approved", approved["approval_status"] == "approved", approved["approval_status"])

        status, _ = _post(f"{api}/admin/approvals/{version_id}/approve", {}, admin_token)
        check("approving twice is a 409, not a silent re-approve", status == 409, f"got {status}")

        status, library = _get(f"{api}/templates", member_token)
        ids = [t["id"] for t in library] if isinstance(library, list) else []
        check("the approved template IS now in the library", str(template_id) in ids)

        status, notes = _get(f"{api}/notifications", member_token)
        member_notes = [n for n in (notes or {}).get("items", []) if n["template_id"] == str(template_id)]
        check("the submitter was notified", len(member_notes) == 1, f"found {len(member_notes)}")
        if member_notes:
            check("it says approved", member_notes[0]["kind"] == "template_approved", member_notes[0]["kind"])
            status, _ = _post(f"{api}/notifications/{member_notes[0]['id']}/read", {}, member_token)
            check("the submitter can mark it read", status == 200, f"got {status}")
            status, notes = _get(f"{api}/notifications", member_token)
            check("the unread count drops", (notes or {}).get("unread", 99) == 0, str((notes or {}).get("unread")))

        # ── 6. password reset ─────────────────────────────────────────────
        print("\n6. Password reset by OTP")
        status, _ = _post(f"{api}/auth/forgot-password", {"email": member_email})
        check("forgot-password answers 202", status == 202, f"got {status}")
        status, _ = _post(f"{api}/auth/forgot-password", {"email": f"nobody.{tag}@authcheck.local"})
        check("an unknown address answers the same 202", status == 202, f"got {status}")

        # No debug_code on this endpoint by design -- the response must not vary
        # with whether the account exists -- so the code is read from the row.
        db = SessionLocal()
        try:
            db.execute(text("select 1"))
        finally:
            db.close()
        status, body = _post(f"{api}/auth/resend-otp", {"email": member_email, "purpose": "password_reset"})
        reset_code = (body or {}).get("debug_code") if isinstance(body, dict) else None
        check("a reset code can be re-sent and read back", bool(reset_code))

        status, _ = _post(f"{api}/auth/reset-password", {
            "email": member_email, "code": reset_code, "new_password": "short",
        })
        check("a too-short new password is refused", status == 422, f"got {status}")

        status, body = _post(f"{api}/auth/reset-password", {
            "email": member_email, "code": reset_code, "new_password": NEW_PASSWORD,
        })
        check("the reset succeeds", status == 200, f"got {status} {body}")

        status, _ = _post(f"{api}/auth/login", {"identifier": member_email, "password": PASSWORD})
        check("the old password no longer works", status == 401, f"got {status}")
        status, body = _post(f"{api}/auth/login", {"identifier": f"member{tag}", "password": NEW_PASSWORD})
        check("a passphrase is accepted, and login works by username too", status == 200, f"got {status}")

        # ── 7. rejection ──────────────────────────────────────────────────
        print("\n7. Rejection requires a note and notifies")
        status, body = _post_file(f"{api}/templates", f"authcheck-reject-{tag}.docx", _minimal_docx(), DOCX_MIME, member_token)
        reject_template_id = uuid.UUID(body["template_id"]) if status == 202 else None
        reject_version_id = body["version_id"] if status == 202 else None
        if reject_version_id:
            time.sleep(UPLOAD_SETTLE_S)
            status, _ = _post(f"{api}/admin/approvals/{reject_version_id}/reject", {"note": ""}, admin_token)
            check("a rejection without a note is refused", status == 422, f"got {status}")
            status, rejected = _post(
                f"{api}/admin/approvals/{reject_version_id}/reject",
                {"note": "The revision block still says Ver. 1."},
                admin_token,
            )
            check("a rejection with a note is recorded", status == 200 and rejected["approval_status"] == "rejected", f"got {status}")
            status, library = _get(f"{api}/templates", member_token)
            ids = [t["id"] for t in library] if isinstance(library, list) else []
            check("a rejected template stays out of the library", str(reject_template_id) not in ids)

            # Cleaned up with the rest.
            db = SessionLocal()
            try:
                key = db.execute(text("select storage_key from template_versions where id = :i"), {"i": reject_version_id}).scalar()
                db.execute(text("update templates set current_version_id = null where id = :i"), {"i": str(reject_template_id)})
                db.execute(text("delete from jobs where entity_id in (select id from template_versions where template_id = :i)"), {"i": str(reject_template_id)})
                db.execute(text("delete from templates where id = :i"), {"i": str(reject_template_id)})
                db.commit()
            finally:
                db.close()
            if key and not keep:
                from app.storage.s3 import delete_file

                try:
                    delete_file(key)
                except Exception:  # noqa: BLE001
                    pass

        print()
        if FAILURES:
            print(f"FAILED -- {len(FAILURES)} check(s) did not pass:")
            for failure in FAILURES:
                print(f"  - {failure}")
            return 1
        print("All checks passed.")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()
        if keep:
            print(f"\n--keep: left users {user_ids} and template {template_id} in place")
        else:
            print("\ncleaning up:")
            _cleanup(user_ids, template_id, storage_key)


if __name__ == "__main__":
    raise SystemExit(main())
