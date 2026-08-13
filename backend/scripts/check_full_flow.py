"""The whole product, driven through the frontend's own origin.

    uv run python scripts/check_full_flow.py --base http://localhost:5173

Every request a user's browser makes, in the order the UI makes them, against a
running Vite dev server proxying a running backend. It is not a substitute for
looking at the page -- it cannot see a layout -- but it proves the thing a
screenshot cannot: that each screen's data actually arrives, in the shape the
components read, from a real upload through a real model pass to a real search.

The steps mirror the screens:

    Library      GET  /templates
    Upload       POST /templates                        -> 202 + job_id
    Progress     GET  /templates/{id}/ingestion/{job}   -> polled to done
    Detail       GET  /templates/{id}
    Region map   GET  /templates/{id}/regions
    Viewer       GET  /templates/{id}/download
    Search       POST /search                           -> both demo queries

Run it against `--base http://localhost:8010` to skip the proxy and test the
backend alone; the difference between the two runs is the proxy's fault.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT.parent / "Files"
SAMPLE = "MOM Sample.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SEMANTIC_QUERY = "record what we agreed and who's doing what"
LEXICAL_QUERY = "BFL"
JOB_BUDGET_S = 180


def _request(method: str, url: str, body: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def get_json(url: str):
    status, raw = _request("GET", url)
    return status, (json.loads(raw) if raw and status < 400 else None)


def post_json(url: str, payload: dict):
    status, raw = _request(
        "POST", url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    return status, (json.loads(raw) if raw and status < 400 else None)


def post_file(url: str, path: Path):
    boundary = f"----FullFlow{uuid.uuid4().hex}"
    body = b"".join(
        (
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {XLSX_MIME}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        )
    )
    status, raw = _request(
        "POST",
        url,
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
    )
    return status, (json.loads(raw) if raw and status < 400 else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5173")
    parser.add_argument("--keep", action="store_true", help="leave the uploaded template in place")
    args = parser.parse_args()
    api = f"{args.base}/api/v1"

    failures: list[str] = []
    template_id = None

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")
        if not ok:
            failures.append(f"{label}{(': ' + detail) if detail else ''}")

    print(f"driving {args.base}\n")

    # 1. The app itself is being served (proves the proxy target is a dev server,
    #    not just a bare API).
    print("app shell")
    status, _ = _request("GET", f"{args.base}/")
    check("GET /", status == 200, f"status {status}")

    # 2. Library.
    print("\nlibrary")
    status, listing = get_json(f"{api}/templates")
    check("GET /templates", status == 200, f"status {status}")
    if listing is not None:
        indexed = [t for t in listing if t.get("searchable")]
        check(
            "cards carry the generated metadata",
            all("purpose" in t and "tags" in t and "searchable" in t for t in listing),
        )
        print(f"        {len(listing)} templates, {len(indexed)} searchable")

    # 3. Upload.
    print("\nupload")
    path = FILES_DIR / SAMPLE
    if not path.exists():
        print(f"  sample not found: {path}")
        return 1
    started = time.perf_counter()
    status, accepted = post_file(f"{api}/templates", path)
    check("POST /templates returns 202", status == 202, f"status {status}")
    if accepted is None:
        return 1
    template_id = accepted["template_id"]
    job_id = accepted["job_id"]
    check("202 carries a job id", bool(job_id))
    print(f"        {time.perf_counter() - started:.1f}s -> template {template_id}")

    # 4. Progress -- the panel the upload page renders.
    print("\ningestion progress")
    stages: list[str] = []
    job = None
    deadline = time.perf_counter() + JOB_BUDGET_S
    while time.perf_counter() < deadline:
        _, job = get_json(f"{api}/templates/{template_id}/ingestion/{job_id}")
        if job is None:
            break
        stage = job.get("stage")
        if stage and (not stages or stages[-1] != stage):
            stages.append(stage)
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(1.5)

    print(f"        stages: {' -> '.join(stages)}")
    check("job succeeded", job and job["status"] == "succeeded", (job or {}).get("error") or "")
    check("enrich stage ran", "enrich" in stages)
    enrichment = (job or {}).get("enrichment")
    check("enrichment reaches the client", enrichment is not None)
    if enrichment:
        check("template was embedded", enrichment["embedded"])
        print(
            f"        {enrichment['regions_labelled']} labelled, "
            f"{enrichment['regions_write_refused']} write-refused, {enrichment['elapsed_ms']}ms"
        )
        print(f"        tags: {enrichment['tags']}")
    check("harvest provenance is exposed", "harvest_source" in (job or {}))
    print(f"        total {time.perf_counter() - started:.1f}s from upload to done")

    # 5. Detail page.
    print("\ntemplate detail")
    status, detail = get_json(f"{api}/templates/{template_id}")
    check("GET /templates/{id}", status == 200, f"status {status}")
    if detail:
        check("purpose is populated", bool(detail.get("purpose")))
        check("tags are populated", bool(detail.get("tags")))
        check("marked searchable", detail.get("searchable") is True)
        check("form id harvested", detail.get("form_id") == "YMSLI-F-MOM", str(detail.get("form_id")))
        print(f"        {detail['title']!r}")
        print(f"        {(detail.get('purpose') or '')[:100]}")

    # 6. Region map.
    print("\nregion map")
    status, regions_out = get_json(f"{api}/templates/{template_id}/regions")
    check("GET /regions", status == 200, f"status {status}")
    if regions_out:
        regions = regions_out["regions"]
        labelled = [r for r in regions if r.get("semantic_role")]
        check("every region carries a semantic role", len(labelled) == len(regions),
              f"{len(labelled)}/{len(regions)}")
        sequences = [r["sequence"] for r in regions]
        check("sequence is a total order", len(set(sequences)) == len(sequences))
        protected_editable = [r for r in regions if r["protected"] and r["editable"]]
        check("no protected region is editable", not protected_editable)
        for region in regions[:3]:
            print(f"        {region['region_id']:<28} {region['kind']:<14} {region['semantic_role']}")

    # 7. Viewer.
    print("\nviewer download")
    status, raw = _request("GET", f"{api}/templates/{template_id}/download")
    check("GET /download", status == 200, f"status {status}")
    check("bytes are a real Office package", raw[:2] == b"PK" if raw else False,
          f"{len(raw) if raw else 0} bytes")

    # 8. Search -- the two queries the demo turns on.
    print("\nsearch")
    for query, expect_id, why in (
        (SEMANTIC_QUERY, template_id, "semantic: no word overlap with the title"),
        (LEXICAL_QUERY, None, "lexical: an acronym embeddings handle badly"),
    ):
        status, results = post_json(f"{api}/search", {"query": query, "top_k": 3})
        check(f"POST /search {query!r}", status == 200, f"status {status}")
        if not results:
            continue
        print(f"        {why}, {results['latency_ms']}ms, degraded={results['degraded']}")
        for position, hit in enumerate(results["results"], start=1):
            print(f"        {position}. {hit['title'][:44]:<44} {hit['match_explanation']}")
        check(f"{query!r} returned something", bool(results["results"]))
        if expect_id and results["results"]:
            check("the uploaded document ranks first", results["results"][0]["template_id"] == expect_id,
                  results["results"][0]["title"])
        if results["results"]:
            top = results["results"][0]
            check("hit carries an explanation", bool(top["match_explanation"]))
            check("hit carries per-signal ranks", "vector_rank" in top["scores"])

    # 9. Clean up, unless asked to leave it for a human to look at.
    if not args.keep and template_id:
        print("\ncleanup")
        sys.path.insert(0, str(ROOT))
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from sqlalchemy import text

        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("update templates set current_version_id = null where id = :i"),
                       {"i": template_id})
            db.execute(text("delete from templates where id = :i"), {"i": template_id})
            db.commit()
            print(f"  removed {template_id}")
        finally:
            db.close()

    print()
    if failures:
        print(f"full flow: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("full flow: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
