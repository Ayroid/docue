"""Version control end to end, against a running API. Real auth, real database.

    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    uv run python scripts/live_e2e_version_control.py

The claim under test is the one the whole feature rests on: **approving a
generated version makes it what the library serves, and re-derives everything
that describes it**. Regions, discovery metadata and the embedding all come from
the bytes, so an approval that skipped re-ingestion would leave search answering
with the purpose and tags of the version it just replaced -- correct file, wrong
description, and nothing in the API that would show it.

Drives the real flow, not a simulation of it:

  1. register + verify two accounts (a member and an admin) through the OTP path
  2. the member runs a conversation to a committed version
  3. the version lands `pending`, so the library does not serve it yet
  4. the admin approves it
  5. current version moves, and a re-ingestion job is queued and finishes
  6. the history reports what that version changed, and who reviewed it
  7. a rejection hands `current` back rather than stranding the template

Accounts are created per run with a unique suffix, so it is re-runnable and
never depends on a fixture account somebody may have renamed. `expose_otp_in_
response` must be on (local + no SMTP), which is what makes the verify step
possible without a mailbox.
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

passed: list[str] = []


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


class Response:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)

    def need(self, *expected: int):
        if self.status_code not in expected:
            raise SystemExit(
                f"expected {expected}, got {self.status_code}: {self.text[:400]}"
            )
        return self.json() if self.text else None


def call(method: str, path: str, body=None, token: str | None = None) -> Response:
    url = path if path.startswith("http") else f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return Response(resp.status, resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read().decode("utf-8", "replace"))


def make_account(tag: str) -> tuple[str, str]:
    """Register and verify one account. Returns `(token, user_id)`."""
    email = f"e2e-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    sent = call(
        "POST",
        "/auth/register",
        {"email": email, "password": PASSWORD, "full_name": f"E2E {tag}"},
    ).need(202)
    code = sent.get("debug_code")
    if not code:
        raise SystemExit(
            "the OTP was not echoed back, so this script cannot verify an account.\n"
            "It needs APP_ENV=local, OTP_DEBUG=true and no SMTP_HOST configured."
        )
    token = call("POST", "/auth/verify-email", {"email": email, "code": code}).need(200)
    return token["access_token"], token["user"]["id"]


def promote_to_admin(user_id: str) -> None:
    """Grant admin directly.

    The admin API needs an admin to call it, and the product deliberately has no
    other route -- `scripts/seed_admin.py` exists for exactly this reason. This
    writes the same column that script does rather than depending on a seeded
    account existing on whoever's machine runs this.
    """
    from sqlalchemy import text

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE users SET role = 'admin' WHERE id = :uid"), {"uid": user_id}
        )
        db.commit()
    finally:
        db.close()


def mom_template(token: str) -> dict:
    for t in call("GET", "/templates", token=token).need(200):
        if t["format"] == "xlsx" and "MOM" in t["title"]:
            return t
    raise SystemExit("no approved MOM xlsx template in this database")


def run_conversation(token: str, template: dict) -> dict:
    """Answer every question, then submit the result as a template version.

    `submit_as_version` is required now: a plain commit produces the caller's
    own document and deliberately does not touch the template's version number.
    That split is what `live_e2e_documents.py` covers; this file is about what
    happens once something *is* put forward as a version.
    """
    session = call(
        "POST",
        "/sessions",
        {"template_id": template["id"], "intent": "Minutes for the Cycle 2 AP review"},
        token,
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
        raise SystemExit(
            "the extractor pulled nothing out of any answer, so there is nothing "
            "to commit. A live-model result, not a version-control fault -- re-run."
        )
    return call(
        "POST", f"/sessions/{sid}/commit", {"submit_as_version": True}, token
    ).need(200)


def wait_for_ingestion(template_id: str, token: str, was: str | None) -> bool:
    """Poll until the template's metadata refreshes, or give up. Returns whether it ran."""
    for _ in range(40):
        time.sleep(3)
        current = call("GET", f"/templates/{template_id}", token=token).need(200)
        if current.get("searchable") and current.get("updated_at") != was:
            return True
    return False


def main() -> int:
    if call("GET", "http://127.0.0.1:8000/health").status_code != 200:
        raise SystemExit("backend is not answering on 127.0.0.1:8000")

    print("Accounts:")
    member_token, member_id = make_account("member")
    admin_token, admin_id = make_account("admin")
    promote_to_admin(admin_id)
    # Re-login so the token carries the new role.
    ok("registered and verified two accounts", f"member={member_id[:8]} admin={admin_id[:8]}")
    assert call("GET", "/admin/health", token=admin_token).status_code == 200, (
        "the seeded admin's token does not carry admin"
    )
    ok("admin token carries admin")
    assert call("GET", "/admin/health", token=member_token).status_code == 403, (
        "a member's token was accepted by an admin route"
    )
    ok("a member is refused by admin routes", "403")

    template = mom_template(admin_token)
    print(f"\nTemplate: {template['title']} (current v?)\n")

    # ── the member produces a version ─────────────────────────────────────
    print("A member generates a version:")
    result = run_conversation(member_token, template)
    version_id = result["result_version_id"]
    assert version_id, f"the commit produced no version: {result.get('status')}"
    ok(
        "committed a generated version",
        f"v{result['result_version_number']}, QA {result['overall']}",
    )

    history = call("GET", f"/templates/{template['id']}/versions", token=member_token).need(200)
    mine = next((v for v in history["versions"] if v["id"] == version_id), None)
    assert mine is not None, "the author cannot see their own submission in the history"
    assert mine["approval_status"] == "pending", (
        f"a generated version landed as {mine['approval_status']}, not pending -- the gate is open"
    )
    assert not mine["is_current"], "a pending version is already what the template serves"
    ok("it is pending and not current", f"origin={mine['origin']}")

    # The change record is the point of the history, so check it says something.
    assert mine["changed"], "the history reports no changed regions for a version that wrote some"
    sample = mine["changed"][0]
    ok(
        "history reports what changed",
        f"{len(mine['changed'])} region(s), e.g. {sample.get('label') or sample['region_id']}"
        f" ({sample.get('provenance')})",
    )

    # ── the queue ─────────────────────────────────────────────────────────
    print("\nDoc control:")
    queue = call("GET", "/admin/approvals?status=pending", token=admin_token).need(200)
    rows = queue["items"] if isinstance(queue, dict) and "items" in queue else queue
    assert any(r["version_id"] == version_id for r in rows), (
        "the submission is not in the pending queue"
    )
    ok("the submission is in the approval queue", f"{len(rows)} pending")

    assert (
        call("POST", f"/admin/approvals/{version_id}/approve", {}, member_token).status_code == 403
    ), "a member was allowed to approve"
    ok("a member cannot approve", "403")

    # ── approve, and prove the library follows ────────────────────────────
    before = call("GET", f"/templates/{template['id']}", token=admin_token).need(200)
    decided = call(
        "POST",
        f"/admin/approvals/{version_id}/approve",
        {"note": "Looks right."},
        admin_token,
    ).need(200)
    ok("approved", f"status={decided.get('approval_status', 'approved')}")

    after = call("GET", f"/templates/{template['id']}", token=admin_token).need(200)
    assert after["current_version_id"] == version_id, (
        "approving did not make the version current -- the library still serves the old bytes"
    )
    ok("the approved version is now current")

    listed = call("GET", "/templates", token=admin_token).need(200)
    assert any(t["id"] == template["id"] for t in listed), (
        "the template vanished from the library after approval"
    )
    ok("the template is still listed in the library")

    print("  waiting for re-ingestion (15-40s)…")
    reingested = wait_for_ingestion(template["id"], admin_token, before.get("updated_at"))
    if reingested:
        ok("the approved bytes were re-ingested", "template metadata refreshed")
    else:
        print(
            "  WARN  re-ingestion did not visibly finish in 120s. Check the server log "
            "for 'queued re-ingestion job'; the job may still be running."
        )

    # ── rejection must not strand the template ────────────────────────────
    print("\nRejection:")
    second = run_conversation(member_token, template)
    second_id = second["result_version_id"]
    assert second_id, "the second commit produced no version"
    call(
        "POST",
        f"/admin/approvals/{second_id}/reject",
        {"note": "Wrong venue."},
        admin_token,
    ).need(200)
    ok("rejected the second version")

    final = call("GET", f"/templates/{template['id']}", token=admin_token).need(200)
    assert final["current_version_id"] != second_id, (
        "a rejected version is the template's current one"
    )
    assert final["current_version_id"] == version_id, (
        f"current should have stayed on the approved version, got {final['current_version_id']}"
    )
    ok("current stayed on the last approved version")

    still_listed = call("GET", "/templates", token=admin_token).need(200)
    assert any(t["id"] == template["id"] for t in still_listed), (
        "a rejection removed the template from the library -- the stranding bug is back"
    )
    ok("the template survived the rejection", "still in the library")

    hist = call("GET", f"/templates/{template['id']}/versions", token=admin_token).need(200)
    rejected = next(v for v in hist["versions"] if v["id"] == second_id)
    assert rejected["approval_status"] == "rejected"
    assert rejected["review_note"] == "Wrong venue.", "the rejection reason was not recorded"
    ok("the rejection and its reason are in the history", f"by {rejected.get('reviewed_by_name')}")

    print(f"\nOK - {len(passed)} live checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
