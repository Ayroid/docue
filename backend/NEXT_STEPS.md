# TemplateHub Backend — State & Next Steps

Handoff doc. Read this first if you're picking the project up cold.
Source of truth for *what* to build: `../Plan-Rules/PS08_Implementation_Plan_v2.md`.
Git workflow rules: `../Plan-Rules/GitRules.md` (never commit to `main`; `feature/{name}` branches only).

---

## 1. Where things stand

### Merged to `main` — upload flow (working, verified against real AWS)

- `uv`-managed FastAPI project (`pyproject.toml` + `uv.lock`, `[tool.uv] package = false`, flat `app/` layout — no `src/`).
- **DB schema** (`app/models/`): `templates` + `template_versions`, Alembic migration `0001_create_templates_and_versions.py`.
- **S3 storage** (`app/storage/s3.py`) incl. a corporate-TLS workaround (see §4).
- **Endpoints**: `POST /api/v1/templates` (upload), `GET /api/v1/templates/{id}`, `GET /health`.
- **Startup DB connectivity check** with masked-URL logging (`app/db/session.py`).
- **Smoke tests**: `scripts/check_db.py`, `scripts/check_s3.py`.
- Verified end-to-end: real file → S3 (`astramind-s3`) + real RDS row.

### Branch `feature/xlsx-surgical-compiler` — Milestone 1 (code complete, QA passing)

The plan's #1 sequencing rule is *"a correctly generated, logo-intact MOM must open in real Excel by hour 8"* — this branch is that.

- `app/ingestion/fingerprint.py` — structural fingerprint read straight from the zip/XML: part list, sheet names, merged-range count, formula count, drawings, `xl/richData/*` part count, media count, `docMetadata/LabelInfo.xml` (Purview sensitivity label) presence.
  - Note: reads raw XML on purpose. `openpyxl`'s read-only worksheets don't even expose `merged_cells`, and the whole point is not to trust one library's object model.
- `app/compiler/xlsx_surgical.py` — **the critical file.** Applies `SetValueOp`s by regex-replacing only the targeted `<c r="E5">` element inside `xl/worksheets/sheetN.xml`, then re-zips with *every other part copied byte-for-byte*. Never calls `openpyxl.save()`.
  - Strings are written as `t="inlineStr"` to avoid touching `sharedStrings.xml` bookkeeping.
  - The existing `s="N"` style index is preserved, which is what keeps number formats (e.g. `d-mmm-yy`) intact.
- `app/qa/structural.py` — `diff_fingerprints(before, after)`; raises `StructuralQAError` on any lost part / merge-count change / lost sensitivity label / lost richData part.
- `scripts/test_surgical_compile.py` — applies a hand-written Change Spec to `../Files/MOM Sample.xlsx` and writes `scratch/MOM_Sample_compiled.xlsx`.

**Verified result:** `18 parts → 18 parts`, `27 merges → 27 merges`, `sensitivity_label True → True`, `rich_value_parts 5 → 5`, structural QA **PASS**. Re-loading the output in openpyxl shows `E5` = new title, `B5` = real date `2026-08-16` still formatted `d-mmm-yy`.

> **⚠️ Outstanding manual check:** nobody has yet opened `scratch/MOM_Sample_compiled.xlsx` in *real Microsoft Excel* to confirm the YMSLI logo still renders in `A1`. That visual confirmation is the actual point of this milestone. Do it before merging this branch.

---

## 2. What the system can and cannot do today

**Can:** store an uploaded xlsx/docx/pptx original in S3 + RDS with a sha256 hash; edit individual named cells in an xlsx while provably preserving every package part; prove that preservation deterministically in ~50ms.

**Cannot yet:**
- Only `set_value` ops. No `replace_region_rows`, `clone_table_rows`, `clear_region`, or `protect` — so no table-row insertion (e.g. adding Action Plan rows) and no enforced write-protection on the logo/formula cells.
- No region schema — cell refs are hand-typed. Nothing stops a caller from targeting a protected range today.
- xlsx only. No docx/pptx compiler.
- The compiler is **not wired to the API**. It's a standalone module + script; compiled output isn't persisted as a new `TemplateVersion`.
- **No embeddings, no search, no LLM calls anywhere.** The DB has no `embedding`/`purpose`/`tags` columns and no `document_schemas`/`document_regions` tables. The system currently has no idea what's *inside* an uploaded document.

---

## 3. Next steps, in order

Ordering follows `PS08_Implementation_Plan_v2.md` §12. The plan is emphatic that building search before generation works is how you reach hour 24 with a failed submission.

### Step 0 — close out Milestone 1
Open `scratch/MOM_Sample_compiled.xlsx` in real Excel, confirm the logo renders. Then merge `feature/xlsx-surgical-compiler` → `main` per GitRules (sync main into the feature branch first, then `--no-ff` merge).

### Step 1 — deterministic region detector
New: `app/ingestion/regions.py`. **No LLM.** Structural signals only, per plan §1.4 / Appendix A:
- label cell + adjacent empty merged cell → `field`
- label with nothing adjacent → `field_empty`
- styled header row with 0 data rows beneath → `table_loop` (e.g. MOM row 27, Action Plan)
- header row + N data rows → `table_data`
- contiguous serial column + prose → `repeating_block` (MOM rows 11–24)
- merged range spanning width at top → `title` / `branding`
- formula cell → `derived`, never writable
- **anything unclassified → `immutable`** (fail-safe default; an unwritten region beats a wrongly-written one)

Test it against `../Files/MOM Sample.xlsx` first, then `BFL Sample.xlsx` and `POC List sample.xlsx`.
⚠️ `BFL Sample.xlsx` reports `max_row=1048575` / `max_col=16384` and will OOM a non-read-only `load_workbook`. Always `read_only=True` and bound scans by last-nonempty, never by `max_row`.

### Step 2 — extend the compiler beyond `set_value`
Add `clone_table_rows` (insert rows under a header, cloning a row template's styling), `replace_region_rows`, and `protect.py` (compiler refuses any write intersecting a protected range — pre-flight, before touching bytes). Row insertion means shifting `r=` attributes on subsequent rows and updating `mergeCell` refs — the fiddliest remaining piece of the project.

### Step 3 — docx + pptx compilers
`app/compiler/docx_compiler.py` (python-docx, run-level edits — the plan measured that docx round-trips losslessly, so this is lower-risk) and `pptx_compiler.py` (python-pptx, shape-level).
⚠️ There is **no pptx in the sample corpus** — one has to be built (plan §1.5 suggests a Workshop Readout deck derived from the MOM, ~45 min).
⚠️ For docx structural QA, count `<w:drawing>` elements in the XML, **not** `doc.inline_shapes` — the BRD has 6 drawings but `inline_shapes` returns 1, so a fingerprint built on it would report "1/1 preserved" while 4 images vanished.

### Step 4 — wire ingestion into the API
Fingerprint on upload, run the region detector, persist the result. Needs new tables (`document_schemas`, `document_regions` — see plan §8) and a new Alembic migration. Ingestion is 15–40s, so it should be async (`BackgroundTasks` + a `jobs` table with SSE progress) — the frontend needs a job-status endpoint to poll.

### Step 5 — only now: LLM + search
LLM region classifier → metadata writer (purpose / when_to_use / tags) → embed **the generated metadata, not document chunks** → pgvector on `templates` → hybrid BM25 + vector + RRF search. Rationale for embedding metadata over body text is in plan §9 and is itself a scoring point — be ready to defend it.

---

## 4. Environment gotchas (these cost real time to rediscover)

- **`uv` is not on `PATH` in bash.** It lives at `/c/Users/VE00YN080/AppData/Roaming/Python/Python314/Scripts/uv.exe`. Prefix commands with:
  `export PATH="/c/Users/VE00YN080/AppData/Roaming/Python/Python314/Scripts:$PATH"`
- **Run the server:** `uv run uvicorn app.main:app --reload` from `TemplateHub-Backend/`.
- **RDS is on port 5432**, which Claude Code's default sandbox blocks (it allows 443 only). Any DB-touching command needs `dangerouslyDisableSandbox: true`. A timeout on 5432 is *not* automatically an RDS problem — test `google.com:5432` to tell sandbox-blocking apart from a real security-group issue.
- **Corporate Zscaler TLS interception** breaks boto3, because botocore ships its own static CA bundle instead of using the OS trust store. Fixed in `app/storage/s3.py::_ca_bundle_path()` by merging the Windows root store (`ssl.enum_certificates`) into certifi's bundle and passing it as `verify=`. **Do not** replace this with the `truststore` package — it was tried and caused `maximum recursion depth exceeded` with botocore.
- **Circular FK between `templates` and `template_versions`:** Postgres checks non-deferred FKs at statement time, so inserts must go: insert Template → `flush()` → insert TemplateVersion → `flush()` → set `template.current_version_id` → `commit()`. See `app/api/v1/templates.py`.
- **Secrets:** `.env` holds the real RDS password and AWS keys. It is `.gitignore`d and has never been staged in any commit — keep it that way. `.env.example` documents the required variable names.
- `scratch/` is gitignored — it's where compiled test output goes.

---

## 5. Repo facts

- Remote: `https://github.com/Jayant135/TemplateHub-Backend`
- `TemplateHub-Backend/` is its own git repo; the parent `Code/` folder is **not** a repo.
- Sample documents live in `../Files/` (outside the repo): `MOM Sample.xlsx`, `BFL Sample.xlsx`, `POC List sample.xlsx`, `BRD Sample.docx`, plus a hackathon intro pptx (not a template sample).
- Frontend (React + TS) is a teammate's workstream, in a separate repo.
