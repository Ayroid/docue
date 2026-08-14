"""Live end-to-end check of the fill-conversation fixes. Needs a running API.

    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    uv run python scripts/live_e2e_fixes.py

Unlike `test_dropped_assertions.py`, which proves the compiler's behaviour with
no server, this drives the real HTTP surface against the real database -- which
is where the status transitions, the 422s and the commit-once guard actually
live. Both matter: the deterministic one tells you the rule is right, this one
tells you the endpoint enforces it.

Every check prints PASS or raises. Nothing is skipped silently.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 180.0

passed: list[str] = []


class Response:
    """The two things this script asks of an HTTP response."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise SystemExit(f"HTTP {self.status_code}: {self.text[:400]}")


class Client:
    """urllib, shaped like the requests API. stdlib only, on purpose -- this
    script must run against a checkout with nothing extra installed.

    Carries a bearer token: `/compile` and `/commit` take `current_user`, so an
    unauthenticated client gets a 401 where this script expects a 200 and the
    commit checks below prove nothing. The token is a throwaway account
    registered through the real OTP path, exactly as the other live scripts do.
    """

    def __init__(self) -> None:
        self.token: str | None = None

    def sign_in(self, tag: str) -> str:
        email = f"e2e-fixes-{tag}-{uuid.uuid4().hex[:8]}@example.com"
        sent = self.post(
            f"{BASE}/auth/register", {"email": email, "password": "Passw0rd!e2e"}
        )
        sent.raise_for_status()
        code = sent.json().get("debug_code")
        if not code:
            raise SystemExit(
                "OTP not echoed; needs APP_ENV=local, OTP_DEBUG=true and no SMTP_HOST."
            )
        verified = self.post(f"{BASE}/auth/verify-email", {"email": email, "code": code})
        verified.raise_for_status()
        self.token = verified.json()["access_token"]
        return email

    def request(self, method: str, url: str, json_body=None) -> Response:
        data = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return Response(resp.status, resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # A 422 is an expected outcome here, not an error.
            return Response(exc.code, exc.read().decode("utf-8", "replace"))

    def get(self, url: str) -> Response:
        return self.request("GET", url)

    def post(self, url: str, json: dict | None = None) -> Response:  # noqa: A002
        return self.request("POST", url, json)

    def patch(self, url: str, json: dict | None = None) -> Response:  # noqa: A002
        return self.request("PATCH", url, json)


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


def _mom(client: Client) -> dict:
    r = client.get(f"{BASE}/templates")
    r.raise_for_status()
    for t in r.json():
        if t["format"] == "xlsx" and "MOM" in t["title"]:
            return t
    raise SystemExit("no MOM xlsx template in this database")


def _start(client: Client, template: dict, intent: str) -> dict:
    r = client.post(
        f"{BASE}/sessions", json={"template_id": template["id"], "intent": intent}
    )
    r.raise_for_status()
    return r.json()


def _answer(client: Client, sid: str, qid: str, text: str = "", skip: bool = False):
    r = client.post(
        f"{BASE}/sessions/{sid}/answer",
        json={"question_id": qid, "answer": text, "skip": skip},
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    client = Client()

    if client.get("http://127.0.0.1:8000/health").status_code != 200:
        raise SystemExit("backend is not answering on 127.0.0.1:8000")

    print(f"Signed in as {client.sign_in('main')}")

    template = _mom(client)
    print(f"Template: {template['title']} ({template['format']})\n")

    # ── 1. skipped questions stay empty ───────────────────────────────────
    # Its own session: skipping a question here would otherwise remove the very
    # date operation the typed-edit checks below need to exist.
    print("Skip semantics:")
    session = _start(client, template, "Minutes for the Cycle 2 AP review")
    sid = session["session_id"]
    questions = session["questions"]
    assert questions, "the planner produced no questions"

    skipped_q = questions[0]
    skipped_regions = set(skipped_q["covers_regions"])
    _answer(client, sid, skipped_q["question_id"], skip=True)

    # Deliberately says nothing about the skipped cluster, so the only way those
    # regions could fill is by inference -- which is the thing skipping forbids.
    for q in questions[1:]:
        _answer(
            client,
            sid,
            q["question_id"],
            text="Cycle 2 of the AP automation workshop. Ravi is sharing the header "
            "field mapping by Friday.",
        )

    state = client.get(f"{BASE}/sessions/{sid}").json()
    leaked = skipped_regions & set(state["derived_values"])
    assert not leaked, f"skipped question's regions were derived anyway: {leaked}"
    ok(
        "a skipped question's regions are never derived",
        f"{len(skipped_regions)} region(s) skipped, none inferred",
    )

    # ...but the user outranks their own earlier skip. Skipping suppresses
    # *inference*, not the person: a value they go on to state explicitly must
    # land, or the system is discarding what someone typed in front of it. This
    # check and the one above are the two halves of the same rule and only make
    # sense together.
    target = sorted(skipped_regions)[0]
    field = target.split(".")[-1].replace("_", " ")
    value = "2026-09-01" if "date" in field else "Room 9"
    before_answered = state["progress"]["answered"]

    r = client.post(
        f"{BASE}/sessions/{sid}/instruct",
        json={"instruction": f"Change the {field} to {value}."},
    )
    assert r.status_code == 200, f"instruct returned {r.status_code}: {r.text[:200]}"
    after = client.get(f"{BASE}/sessions/{sid}").json()

    assert target in after["filled_values"], (
        f"'Change the {field} to {value}' did not reach {target}. filled="
        f"{sorted(after['filled_values'])}. This is a live-model result: the "
        "instruction was accepted but nothing was extracted from it."
    )
    ok(
        "an explicit instruction outranks an earlier skip",
        f"{target} = {after['filled_values'][target]!r}",
    )

    assert after["progress"]["answered"] == before_answered, (
        f"the instruction advanced the interview {before_answered} -> "
        f"{after['progress']['answered']}; a question would be skipped unasked"
    )
    ok("an instruction does not advance the interview", f"still {before_answered} answered")

    # ── 2. dry run does not change status ─────────────────────────────────
    # The invariant is about status, and it must hold whether the compile
    # succeeds or is refused -- a session that skipped its way down to nothing
    # writable gets a 422 here, and that must not move it either.
    print("\nDry run:")
    before = client.get(f"{BASE}/sessions/{sid}").json()["status"]
    dry = client.post(f"{BASE}/sessions/{sid}/compile", json={"dry_run": True})
    after = client.get(f"{BASE}/sessions/{sid}").json()["status"]
    assert before == after, f"dry run moved status {before} -> {after}"
    ok("dry run leaves status alone", f"still {after} (compile HTTP {dry.status_code})")

    if dry.status_code == 200:
        dry_body = dry.json()
        print(
            f"        overall={dry_body.get('overall')} "
            f"dropped={len(dry_body.get('dropped') or [])} "
            f"applied={dry_body.get('operations_applied')}"
        )
    else:
        print(f"        refused: {dry.json().get('detail')}")

    # ── A fully answered session, for the edit and commit checks ──────────
    print("\nA fully answered session:")
    full = _start(client, template, "Minutes for the Cycle 2 AP review")
    sid = full["session_id"]
    for q in full["questions"]:
        _answer(client, sid, q["question_id"], text="Conference Room 4 on 2026-08-22")
    filled = client.get(f"{BASE}/sessions/{sid}").json()
    print(
        f"        {len(filled['filled_values'])} filled, "
        f"{len(filled['derived_values'])} derived, status={filled['status']}"
    )
    assert filled["filled_values"] or filled["derived_values"], (
        "the extractor pulled nothing out of any answer -- the edit and commit "
        "checks below would prove nothing. This is a live-model result, not a "
        "compiler fault; re-run, or check Bedrock reachability."
    )

    # ── 3/4. the review screen's 422s ─────────────────────────────────────
    print("\nReview-screen edits:")
    spec = client.get(f"{BASE}/sessions/{sid}/spec").json()
    ops = spec["spec"]["operations"]

    protect_ix = next((i for i, o in enumerate(ops) if o["op"] == "protect"), None)
    assert protect_ix is not None, "no protect operation in this spec to test against"
    r = client.patch(
        f"{BASE}/sessions/{sid}/spec/{protect_ix}", json={"value": "overwrite the logo"}
    )
    assert r.status_code == 422, f"patching a protect op returned {r.status_code}, want 422"
    ok("patching a protect operation is refused", f"422: {r.json()['detail'][:58]}...")

    # A date operation, fed prose. The edit that started all of this.
    date_ix = None
    for i, o in enumerate(ops):
        if o["op"] != "set_value":
            continue
        rid = (o.get("target") or {}).get("region_id") or ""
        if rid.endswith(".date"):
            date_ix = i
            break

    if date_ix is None:
        print("        no date operation in this spec; typed-edit checks skipped")
    else:
        r = client.patch(
            f"{BASE}/sessions/{sid}/spec/{date_ix}", json={"value": "Edited on review"}
        )
        assert r.status_code == 422, (
            f"prose into a date region returned {r.status_code}, want 422"
        )
        ok("prose into a date region is refused", f"422: {r.json()['detail'][:58]}...")

        r = client.patch(
            f"{BASE}/sessions/{sid}/spec/{date_ix}", json={"value": "2026-08-22"}
        )
        assert r.status_code == 200, (
            f"a valid date edit returned {r.status_code}: {r.text[:200]}"
        )
        ok("a valid date edit is accepted", "200")

    # A valid text edit still works end to end.
    text_ix = next(
        (
            i
            for i, o in enumerate(ops)
            if o["op"] == "set_value"
            and not ((o.get("target") or {}).get("region_id") or "").endswith(".date")
        ),
        None,
    )
    if text_ix is not None:
        r = client.patch(
            f"{BASE}/sessions/{sid}/spec/{text_ix}", json={"value": "Conference Room 4"}
        )
        assert r.status_code == 200, f"a valid text edit returned {r.status_code}: {r.text[:200]}"
        ok("a valid text edit is accepted", "200")

    # ── 5. fields_filled never exceeds fields_total ───────────────────────
    print("\nProgress counter:")
    prog = client.get(f"{BASE}/sessions/{sid}").json()["progress"]
    assert prog["fields_filled"] <= prog["fields_total"], (
        f"fields_filled {prog['fields_filled']} > fields_total {prog['fields_total']}"
    )
    ok(
        "fields_filled <= fields_total",
        f"{prog['fields_filled']}/{prog['fields_total']}",
    )

    # ── 6. commit, and the commit-once guard ──────────────────────────────
    print("\nCommit:")
    r = client.post(f"{BASE}/sessions/{sid}/commit", json={"publish": False})
    assert r.status_code == 200, f"commit returned {r.status_code}: {r.text[:400]}"
    body = r.json()
    dropped = body.get("dropped") or []
    if body.get("overall") != "pass":
        failed = [a for a in body.get("assertions", []) if not a.get("passed")]
        raise AssertionError(
            "QA gate failed the commit.\n"
            f"        status={body.get('status')} structural={body.get('structural')}\n"
            f"        functional={body.get('functional')}\n"
            "        dropped: "
            + ("; ".join(f"{d['target']}: {d['reason']}" for d in dropped[:4]) or "none")
            + "\n        failed assertions: "
            + (
                "; ".join(
                    f"{a['subject']} expected {a.get('expected')!r} got {a.get('actual')!r}"
                    for a in failed[:4]
                )
                or "none"
            )
        )
    ok(
        "commit succeeds and QA passes",
        f"{len(dropped)} dropped, {body.get('operations_applied')} applied",
    )

    status_now = client.get(f"{BASE}/sessions/{sid}").json()["status"]
    assert status_now == "committed", f"status after commit is {status_now}"
    ok("status is committed", status_now)

    r = client.post(f"{BASE}/sessions/{sid}/commit", json={"publish": False})
    assert r.status_code == 409, f"a second commit returned {r.status_code}, want 409"
    ok("a second commit is refused", f"409: {r.json()['detail'][:58]}...")

    # A dry run on a committed session must not downgrade it.
    r = client.post(f"{BASE}/sessions/{sid}/compile", json={"dry_run": True})
    still = client.get(f"{BASE}/sessions/{sid}").json()["status"]
    assert still == "committed", f"a dry run downgraded a committed session to {still}"
    ok("dry run does not downgrade a committed session", still)

    # ── 7. unknown session is a 404, not a 500 ────────────────────────────
    print("\nEdges:")
    r = client.get(f"{BASE}/sessions/{uuid.uuid4()}")
    assert r.status_code == 404, f"unknown session returned {r.status_code}"
    ok("unknown session is 404", "404")

    # 404 by design: "this spec has N operations, there is no #9999" is a
    # not-found, not a malformed request.
    r = client.patch(f"{BASE}/sessions/{sid}/spec/9999", json={"value": "x"})
    assert r.status_code == 404, (
        f"an out-of-range op index returned {r.status_code}, want 404"
    )
    ok("out-of-range operation index is 404", r.json()["detail"][:50])

    print(f"\nOK - {len(passed)} live checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
