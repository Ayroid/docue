"""Per-template access control, live against a running API.

    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    python scripts/check_access_control.py

`tests/test_access_rule.py` proves the rule offline over its whole input matrix,
but it can only check the two SQL forms *structurally* -- which clauses appear
for which class of caller. Postgres is the thing that actually evaluates them,
and a filter that is correct in Python and subtly wrong in SQL would pass that
suite and fail here. This is the half that needs a database.

What it proves, in order:

  1. restricting a template removes it from a stranger's library listing
  2. ...and from their **search results**, both halves -- the gate that was
     missing for longest and the one that matters most, because the search box
     is how anyone actually finds a template
  3. ...and from every direct read: GET, download, regions, versions, and
     `POST /sessions`, which used to hand over the stored bytes to anyone
  4. a grant restores all of it
  5. revoking takes it away again
  6. the owner and admins never lose access, grant or no grant
  7. `visibility: public` restores the pre-feature behaviour exactly
  8. a non-admin cannot reach any of the four administrative routes
  9. sharing to an unregistered address is refused, not silently stored

Re-runnable: it registers its own accounts and uploads its own template, then
deletes what it made. It needs `APP_ENV=local`, `OTP_DEBUG=true` and no
`SMTP_HOST`, so registration echoes the OTP instead of mailing it.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 180.0
PASSWORD = "Sup3rSecret!23"
ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT.parent / "Files"
SAMPLE = "MOM Sample.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INGEST_BUDGET_S = 120.0

passed: list[str] = []
failed: list[str] = []


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


def bad(label: str, detail: str = "") -> None:
    failed.append(label)
    print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))


def check(label: str, condition: bool, detail: str = "") -> None:
    (ok if condition else bad)(label, detail)


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


def account(tag: str) -> tuple[str, str, str]:
    """Register and verify one account. Returns `(token, user_id, email)`."""
    email = f"e2e-acl-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    sent = call("POST", "/auth/register", {"email": email, "password": PASSWORD}).need(202)
    code = sent.get("debug_code")
    if not code:
        raise SystemExit("OTP not echoed; needs APP_ENV=local, OTP_DEBUG=true, no SMTP_HOST.")
    tok = call("POST", "/auth/verify-email", {"email": email, "code": code}).need(200)
    return tok["access_token"], tok["user"]["id"], email


def multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----acl" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {XLSX_MIME}\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def visible_ids(token: str | None) -> set[str]:
    rows = call("GET", "/templates", token=token).need(200)
    return {row["id"] for row in rows}


def search_ids(query: str, token: str | None) -> set[str]:
    body = call("POST", "/search", {"query": query, "top_k": 25}, token=token).need(200)
    return {hit["template_id"] for hit in body["results"]}


def main() -> int:  # noqa: PLR0915 - a linear end-to-end check reads better whole
    if call("GET", "http://127.0.0.1:8000/health").status_code != 200:
        raise SystemExit("backend is not answering on 127.0.0.1:8000")
    sample = FILES_DIR / SAMPLE
    if not sample.exists():
        raise SystemExit(f"corpus file not on this machine: {sample}")

    # ── cast ──────────────────────────────────────────────────────────────
    # The owner uploads; an admin approves and shares; the stranger is who the
    # gate is actually about. A second stranger proves a grant is per person
    # rather than "anyone who is not the first stranger".
    owner_token, owner_id, owner_email = account("owner")
    stranger_token, stranger_id, stranger_email = account("stranger")
    other_token, _, _ = account("other")
    print(f"Owner {owner_id[:8]}, stranger {stranger_id[:8]}\n")

    admin_token = admin_login()
    if admin_token is None:
        raise SystemExit(
            "no admin account available. Seed one with `python scripts/seed_admin.py` "
            "and set ADMIN_EMAIL / ADMIN_PASSWORD in the environment."
        )

    # ── a template of our own, approved so it is in the library ──────────
    print("Setting up a template:")
    body, ctype = multipart(SAMPLE, sample.read_bytes())
    accepted = call("POST", "/templates", token=owner_token, raw=body, content_type=ctype).need(202)
    tid, vid = accepted["template_id"], accepted["version_id"]
    unique = f"aclprobe{uuid.uuid4().hex[:8]}"

    deadline = time.time() + INGEST_BUDGET_S
    while time.time() < deadline:
        job = call(
            "GET", f"/templates/{tid}/ingestion/{accepted['job_id']}", token=owner_token
        ).need(200)
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(1.0)
    call("POST", f"/admin/approvals/{vid}/approve", {"note": "acl check"}, token=admin_token).need(200)
    ok("template uploaded and approved", tid[:8])

    try:
        # ── 1. public is the pre-feature behaviour ───────────────────────
        print("\nWhile public:")
        check("stranger sees it in the library", tid in visible_ids(stranger_token))
        check("anonymous sees it in the library", tid in visible_ids(None))
        check(
            "stranger can open it",
            call("GET", f"/templates/{tid}", token=stranger_token).status_code == 200,
        )
        check(
            "stranger can start a session",
            call(
                "POST", "/sessions", {"template_id": tid, "intent": "acl probe"},
                token=stranger_token,
            ).status_code == 201,
        )
        state = call("GET", f"/admin/templates/{tid}/access", token=admin_token).need(200)
        check("visibility defaults to public", state["visibility"] == "public",
              state["visibility"])

        # ── 2. restricting closes every door ─────────────────────────────
        print("\nAfter restricting:")
        call("PUT", f"/admin/templates/{tid}/visibility", {"visibility": "restricted"},
             token=admin_token).need(200)

        check("gone from the stranger's library", tid not in visible_ids(stranger_token))
        check("gone from the anonymous library", tid not in visible_ids(None))
        # The search box is the gate that was missing for longest. Searched by
        # the template's own title, so a miss here is the filter working rather
        # than a weak query.
        check("gone from the stranger's search", tid not in search_ids("MOM minutes of meeting",
                                                                      stranger_token))
        check("gone from anonymous search", tid not in search_ids("MOM minutes of meeting", None))
        for label, method, path in (
            ("GET /templates/{id}", "GET", f"/templates/{tid}"),
            ("download", "GET", f"/templates/{tid}/download"),
            ("regions", "GET", f"/templates/{tid}/regions"),
            ("version history", "GET", f"/templates/{tid}/versions"),
        ):
            got = call(method, path, token=stranger_token).status_code
            check(f"stranger refused: {label}", got == 404, f"got {got}")
        started = call("POST", "/sessions", {"template_id": tid, "intent": "probe"},
                       token=stranger_token)
        check("stranger refused: POST /sessions", started.status_code == 404,
              f"got {started.status_code}")

        # ── 3. the people who must never lose access ─────────────────────
        check("owner still sees it", call("GET", f"/templates/{tid}",
                                          token=owner_token).status_code == 200)
        check("admin still sees it", call("GET", f"/templates/{tid}",
                                          token=admin_token).status_code == 200)
        check("owner still finds it in search", tid in search_ids("MOM minutes of meeting",
                                                                  owner_token))

        # ── 4. a grant restores it, for that person only ─────────────────
        print("\nAfter granting to the stranger:")
        call("POST", f"/admin/templates/{tid}/grants", {"email": stranger_email},
             token=admin_token).need(200)

        check("back in the stranger's library", tid in visible_ids(stranger_token))
        check("back in the stranger's search", tid in search_ids("MOM minutes of meeting",
                                                                 stranger_token))
        check("stranger can open it", call("GET", f"/templates/{tid}",
                                           token=stranger_token).status_code == 200)
        check(
            "stranger can start a session",
            call("POST", "/sessions", {"template_id": tid, "intent": "probe"},
                 token=stranger_token).status_code == 201,
        )
        # The grant is one person's, not a general unlocking.
        check("the other account is still refused", tid not in visible_ids(other_token))
        check("the other account still cannot search it",
              tid not in search_ids("MOM minutes of meeting", other_token))

        # Idempotent: re-sharing updates rather than duplicating.
        again = call("POST", f"/admin/templates/{tid}/grants", {"email": stranger_email},
                     token=admin_token).need(200)
        check("re-sharing does not duplicate the grant", len(again["grants"]) == 1,
              f"{len(again['grants'])} grants")
        # Case is normalised on write, so a capitalised address is the same person.
        upper = call("POST", f"/admin/templates/{tid}/grants",
                     {"email": stranger_email.upper()}, token=admin_token)
        check("a capitalised address resolves to the same account",
              upper.status_code == 200 and len(upper.json()["grants"]) == 1,
              f"got {upper.status_code}")

        # ── 5. revoking ──────────────────────────────────────────────────
        print("\nAfter revoking:")
        call("DELETE", f"/admin/templates/{tid}/grants/{stranger_id}", token=admin_token).need(200)
        check("gone from the stranger's library again", tid not in visible_ids(stranger_token))
        check("gone from the stranger's search again",
              tid not in search_ids("MOM minutes of meeting", stranger_token))

        # ── 6. back to public ────────────────────────────────────────────
        print("\nBack to public:")
        call("PUT", f"/admin/templates/{tid}/visibility", {"visibility": "public"},
             token=admin_token).need(200)
        check("stranger sees it again", tid in visible_ids(stranger_token))
        check("anonymous sees it again", tid in visible_ids(None))
        check("stranger finds it in search again",
              tid in search_ids("MOM minutes of meeting", stranger_token))

        # ── 7. the administrative routes are admin-only ──────────────────
        print("\nAdministrative routes:")
        for label, method, path, payload in (
            ("read access", "GET", f"/admin/templates/{tid}/access", None),
            ("set visibility", "PUT", f"/admin/templates/{tid}/visibility",
             {"visibility": "restricted"}),
            ("grant", "POST", f"/admin/templates/{tid}/grants", {"email": owner_email}),
            ("revoke", "DELETE", f"/admin/templates/{tid}/grants/{stranger_id}", None),
        ):
            got = call(method, path, payload, token=stranger_token).status_code
            check(f"non-admin refused: {label}", got == 403, f"got {got}")
            anon = call(method, path, payload).status_code
            check(f"anonymous refused: {label}", anon in (401, 403), f"got {anon}")

        # ── 8. sharing to an address with no account ─────────────────────
        nobody = call("POST", f"/admin/templates/{tid}/grants",
                      {"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com"}, token=admin_token)
        check("unregistered address is refused", nobody.status_code == 404,
              f"got {nobody.status_code}")
        owner_grant = call("POST", f"/admin/templates/{tid}/grants", {"email": owner_email},
                           token=admin_token)
        check("granting to the owner is refused as redundant", owner_grant.status_code == 409,
              f"got {owner_grant.status_code}")

    finally:
        # Runs against a shared database, so it cleans up whatever it made even
        # when an assertion above failed.
        print("\nCleaning up:")
        removed = cleanup(tid)
        print(f"  removed template {tid[:8]} ({removed})")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        for label in failed:
            print(f"  FAILED: {label}")
        return 1
    return 0


def admin_login() -> str | None:
    """Sign in as an admin, from the environment.

    Deliberately not created here: promoting an account to admin is exactly the
    thing this check is testing the boundary of, and a script that could mint
    its own admin would be proving less than it appears to.
    """
    import os

    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return None
    res = call("POST", "/auth/login", {"identifier": email, "password": password})
    if res.status_code != 200:
        return None
    return res.json()["access_token"]


def cleanup(template_id: str) -> str:
    """Delete the template this run created, and everything hanging off it.

    Straight to the database: there is no delete endpoint, and leaving a probe
    template in a shared library would put `MOM Sample` in the demo twice.
    """
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("delete from template_grants where template_id = :t"),
                     {"t": template_id})
        conn.execute(
            text(
                "delete from generated_documents where template_id = :t"
            ),
            {"t": template_id},
        )
        conn.execute(
            text(
                "delete from qa_runs where change_spec_id in "
                "(select id from change_specs where template_id = :t)"
            ),
            {"t": template_id},
        )
        conn.execute(text("delete from change_specs where template_id = :t"), {"t": template_id})
        conn.execute(
            text(
                "delete from question_plans where version_id in "
                "(select id from template_versions where template_id = :t)"
            ),
            {"t": template_id},
        )
        conn.execute(text("delete from generation_sessions where template_id = :t"),
                     {"t": template_id})
        conn.execute(
            text(
                "delete from document_regions where version_id in "
                "(select id from template_versions where template_id = :t)"
            ),
            {"t": template_id},
        )
        conn.execute(
            text(
                "delete from document_schemas where version_id in "
                "(select id from template_versions where template_id = :t)"
            ),
            {"t": template_id},
        )
        conn.execute(text("update templates set current_version_id = null where id = :t"),
                     {"t": template_id})
        conn.execute(text("delete from template_versions where template_id = :t"),
                     {"t": template_id})
        conn.execute(text("delete from templates where id = :t"), {"t": template_id})
    return "ok"


if __name__ == "__main__":
    raise SystemExit(main())
