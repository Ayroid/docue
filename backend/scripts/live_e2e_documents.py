"""A document is not a version of its template. Live, against a running API.

    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    uv run python scripts/live_e2e_documents.py

The distinction this proves is the one the schema was missing. Before it, every
compile minted a `template_versions` row: `MOM Sample` reached v7 because six
people made minutes from it, all seven landed in doc control's approval queue,
and one template in this database was replaced by a filled-in copy of itself.

So:

  1. generating a document does **not** move the template's version number
  2. it does **not** appear in the approval queue
  3. it is the author's, and downloadable, immediately
  4. submitting it as a version *does* mint one, and *does* queue it
  5. a second submission of the same document is refused
  6. uploading a replacement file also mints a version, and is refused outright
     if it is the wrong format

Re-runnable: it registers its own accounts per run.
"""

import io
import json
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 180.0
PASSWORD = "Sup3rSecret!23"

passed: list[str] = []


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


class Response:
    def __init__(self, code: int, text: str) -> None:
        self.status_code, self.text = code, text

    def json(self):
        return json.loads(self.text) if self.text else None

    def need(self, *expected: int):
        if self.status_code not in expected:
            raise SystemExit(f"expected {expected}, got {self.status_code}: {self.text[:400]}")
        return self.json()


def call(method: str, path: str, body=None, token=None, raw=None, content_type=None) -> Response:
    url = path if path.startswith("http") else f"{BASE}{path}"
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return Response(r.status, r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return Response(e.code, e.read().decode("utf-8", "replace"))


def fetch_bytes(path: str, token: str) -> bytes:
    """A binary GET. `call()` decodes to text, which would corrupt a zip."""
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def account(tag: str) -> tuple[str, str]:
    email = f"e2e-doc-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    sent = call("POST", "/auth/register", {"email": email, "password": PASSWORD}).need(202)
    code = sent.get("debug_code")
    if not code:
        raise SystemExit("OTP not echoed; needs APP_ENV=local, OTP_DEBUG=true, no SMTP_HOST.")
    tok = call("POST", "/auth/verify-email", {"email": email, "code": code}).need(200)
    return tok["access_token"], tok["user"]["id"]


def multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----e2e" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def versions_of(template_id: str, token: str) -> list[dict]:
    return call("GET", f"/templates/{template_id}/versions", token=token).need(200)["versions"]


def main() -> int:
    if call("GET", "http://127.0.0.1:8000/health").status_code != 200:
        raise SystemExit("backend is not answering on 127.0.0.1:8000")

    token, user_id = account("author")
    print(f"Author {user_id[:8]}\n")

    template = next(
        (t for t in call("GET", "/templates", token=token).need(200)
         if t["format"] == "xlsx" and "MOM" in t["title"]),
        None,
    )
    if template is None:
        raise SystemExit("no approved MOM xlsx template in this database")
    tid = template["id"]

    before = versions_of(tid, token)
    top_before = max((v["version_number"] for v in before), default=0)
    print(f"Template: {template['title']}  (highest version v{top_before})\n")

    # ── generating a document ─────────────────────────────────────────────
    print("Generating a document:")
    session = call(
        "POST", "/sessions", {"template_id": tid, "intent": "Cycle 2 AP review minutes"}, token
    ).need(201)
    sid = session["session_id"]
    for q in session["questions"]:
        call(
            "POST",
            f"/sessions/{sid}/answer",
            {"question_id": q["question_id"], "answer": "Conference Room 4 on 2026-08-22"},
            token,
        ).need(200)

    state = call("GET", f"/sessions/{sid}", token=token).need(200)
    if not (state["filled_values"] or state["derived_values"]):
        raise SystemExit("the extractor pulled nothing out; a live-model result, not a fault. Re-run.")

    result = call("POST", f"/sessions/{sid}/commit", {}, token).need(200)
    document_id = result["result_document_id"]
    assert document_id, f"the commit produced no document: {json.dumps(result)[:300]}"
    assert result["result_version_id"] is None, (
        "committing a session minted a template version -- the split is not in effect"
    )
    ok("a commit produces a document, not a version", f"doc {document_id[:8]}")

    after = versions_of(tid, token)
    top_after = max((v["version_number"] for v in after), default=0)
    assert top_after == top_before, (
        f"the template's version number moved {top_before} -> {top_after} because "
        "somebody made a document"
    )
    ok("the template's version number did not move", f"still v{top_before}")

    queue = call("GET", "/admin/approvals?status_filter=pending", token=token)
    # A member cannot read the queue; that it is 403 rather than containing the
    # document is the same claim from the other side.
    assert queue.status_code == 403, f"a member could read the approval queue ({queue.status_code})"
    ok("a document does not reach the member-visible queue", "403 as expected")

    mine = call("GET", "/documents", token=token).need(200)
    assert any(d["id"] == document_id for d in mine), "the document is not in My Documents"
    doc = next(d for d in mine if d["id"] == document_id)
    assert doc["promoted_version_id"] is None, "a fresh document claims to be a version"
    ok("it is listed in My Documents", f"{len(mine)} document(s), base v{doc['base_version_number']}")

    blob = fetch_bytes(f"/documents/{document_id}/download", token)
    assert blob[:4] == b"PK\x03\x04", "the download is not a valid Office package"
    ok("it downloads", f"{len(blob)} bytes, valid zip")

    other_token, _ = account("stranger")
    assert call("GET", f"/documents/{document_id}", token=other_token).status_code == 404, (
        "someone else could read this document"
    )
    ok("someone else cannot read it", "404")

    # ── submitting it as a version ────────────────────────────────────────
    print("\nSubmitting it as the next version:")
    submitted = call(
        "POST", f"/documents/{document_id}/submit-as-version", {"note": "Better layout."}, token
    ).need(200)
    assert submitted["promoted_version_id"], "submitting recorded no version"
    assert submitted["promoted_status"] == "pending"
    ok(
        "it becomes a pending version",
        f"v{submitted['promoted_version_number']}, {submitted['promoted_status']}",
    )

    # Counted, not arithmetic on version_number. Numbers are global to the
    # template while this history is filtered per caller -- a version somebody
    # else had rejected consumes a number this author can neither see nor reuse,
    # so "the next number" is legitimately not "mine + 1".
    now = versions_of(tid, token)
    assert len(now) == len(before) + 1, (
        f"submitting minted {len(now) - len(before)} versions, expected exactly 1"
    )
    minted = submitted["promoted_version_number"]
    assert any(v["version_number"] == minted for v in now), (
        "the minted version is not in the author's own history"
    )
    ok("exactly one version was minted", f"v{minted}, {len(before)} -> {len(now)} visible")

    again = call("POST", f"/documents/{document_id}/submit-as-version", {}, token)
    assert again.status_code == 409, f"a second submission returned {again.status_code}, want 409"
    ok("a second submission is refused", f"409: {again.json()['detail'][:52]}...")

    assert (
        call("POST", f"/documents/{document_id}/submit-as-version", {}, other_token).status_code
        == 404
    ), "someone else could submit this document"
    ok("someone else cannot submit it", "404")

    # ── uploading a replacement file ──────────────────────────────────────
    print("\nUploading a replacement file as the next version:")
    wrong = io.BytesIO()
    with zipfile.ZipFile(wrong, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    body, ctype = multipart("replacement.pptx", wrong.getvalue())
    res = call("POST", f"/templates/{tid}/versions", raw=body, content_type=ctype, token=token)
    assert res.status_code == 422, f"a .pptx into an .xlsx template returned {res.status_code}"
    ok("a format mismatch is refused", f"422: {res.json()['detail'][:56]}...")

    # Re-upload the template's own bytes: a real .xlsx the detector can read,
    # without needing a corpus file on the machine running this.
    original = fetch_bytes(f"/templates/{tid}/download", token)
    assert original[:4] == b"PK\x03\x04", "the template download is not a zip"
    body, ctype = multipart("replacement.xlsx", original)
    accepted = call(
        "POST", f"/templates/{tid}/versions", raw=body, content_type=ctype, token=token
    )
    assert accepted.status_code == 202, (
        f"uploading a new version returned {accepted.status_code}: {accepted.text[:200]}"
    )
    ok("a matching upload is accepted", f"202, job {accepted.json()['job_id'][:8]}")

    final = versions_of(tid, token)
    assert len(final) == len(now) + 1, (
        f"the upload minted {len(final) - len(now)} versions, expected exactly 1"
    )
    newest = max(final, key=lambda v: v["version_number"])
    assert newest["approval_status"] == "pending", "an uploaded version skipped the gate"
    ok("it lands pending, like any submission", f"v{newest['version_number']}")

    print(f"\nOK - {len(passed)} live checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
