# Docue — Backend

FastAPI service behind Docue, a document template hub built for the YMSLI
hackathon. It ingests office documents, works out which parts of them are
variable, interviews a user to fill those parts in, and compiles a new document
that keeps the original's formatting intact.

The React interface it serves lives alongside it in [`frontend/`](../frontend). Run
both: see the [root README](../README.md).

---

## What it does

A template starts as an ordinary `.docx`, `.pptx`, or `.xlsx` that someone
uploads. From there:

1. **Ingestion** fingerprints the file, detects its editable regions, classifies
   them, and enriches them with metadata (`app/ingestion`).
2. **Search** indexes the result so it can be found by meaning rather than
   filename, using pgvector embeddings alongside a keyword index
   (`app/search/hybrid.py`).
3. **Conversation** turns the detected regions into an interview — what to ask,
   in what order, how to phrase it, and what can be inferred from what the user
   already wrote instead of being asked again (`app/conversation`).
4. **Planning** converts the collected answers into a change spec: a precise
   list of edits to apply (`app/planning/change_planner.py`).
5. **Compilation** applies that spec surgically, editing the document's XML in
   place rather than regenerating it, so styles, headers, and numbering survive
   (`app/compiler`).

Access control, approvals, versioning, and email notifications sit around that
core in `app/access`, `app/models`, and `app/notifications`.

## Stack

| Piece | Choice |
|---|---|
| API | FastAPI, Python 3.14, `uv` for dependency management |
| Database | PostgreSQL 16 with pgvector, via SQLAlchemy + Alembic |
| Object storage | S3-compatible — MinIO locally, real S3 in a deployment |
| Language model | Any OpenAI-compatible endpoint (`app/ai/bedrock.py`) |

The LLM client is named `bedrock.py` for historical reasons — it originally
called AWS Bedrock, and the module keeps its exported names so the eight call
sites did not have to change. It now speaks the OpenAI API to a local proxy.

## Layout

```
app/
├── api/v1/       route handlers — auth, templates, search, sessions, admin, …
├── models/       SQLAlchemy tables
├── schemas/      Pydantic request/response models
├── ingestion/    upload → fingerprint → region detection → classification
├── conversation/ question planning, phrasing, extraction, derived answers
├── planning/     answers → change spec
├── compiler/     change spec → rewritten docx/pptx/xlsx
├── search/       hybrid vector + keyword search
├── access/       who may see or edit a template
├── ai/           LLM client and prompts
├── storage/      S3/MinIO
└── core/         settings
alembic/          migrations (squashed to a single baseline)
scripts/          setup and manual verification scripts
```

## Running it

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), and an
OpenAI-compatible LLM endpoint reachable from your machine.

```bash
cp .env.example .env      # then fill in the values described below
docker compose up -d      # Postgres (pgvector) + MinIO
uv sync
uv run alembic upgrade head
uv run python scripts/seed_admin.py
uv run uvicorn app.main:app --reload
```

The API comes up on `http://localhost:8000`; interactive docs at `/docs`, and a
liveness probe at `/health`. Compose also exposes the MinIO console on
`http://localhost:9001`. The bucket is created automatically at startup, so
there is no manual bucket step.

### Configuration

Every setting is read from `.env`; see `.env.example` for the annotated list.
The ones you must set:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string; matches the compose credentials |
| `S3_BUCKET_NAME`, `AWS_REGION` | Object storage target |
| `S3_ENDPOINT_URL` | Point at MinIO locally; leave unset for real AWS |
| `LLM_API_KEY`, `LLM_BASE_URL` | The OpenAI-compatible endpoint |
| `JWT_SECRET` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

Two defaults are deliberate rather than arbitrary:

- `LLM_EMBEDDING_MODEL` is **pinned**, not `auto`. The `templates.embedding`
  column is `VECTOR(1024)`, so a 3072-dimension model will not fit it. If you
  change the model, change the column and re-embed.
- `JWT_SECRET` has a development default that the app **refuses to start on**
  unless `APP_ENV` is `local`. That is intentional: a shared deployment running
  on a secret committed to the repository would let anyone mint an admin token.

Leave `SMTP_HOST` blank and every OTP and notification is written to the server
log in full instead of being sent — enough to exercise the whole auth flow
without a mailbox.

## Verifying a setup

`scripts/` holds standalone checks that hit the real services rather than
mocks. Useful after a fresh install:

```bash
uv run python scripts/check_db.py          # connection, extension, tables
uv run python scripts/check_s3.py          # upload and read back
uv run python scripts/check_auth_flow.py   # register → OTP → login
uv run python scripts/check_full_flow.py   # upload → ingest → generate
```

## Migrations

The eight original migrations were squashed into a single baseline,
`alembic/versions/0001_initial_schema.py`. If you are carrying a database
created before that squash, recreate it rather than trying to upgrade across
the gap.

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "what changed"
```
