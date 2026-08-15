# Docue

A document template hub, built for the YMSLI hackathon.

Someone uploads a `.docx`, `.pptx`, or `.xlsx` they already use — a report, a
proposal, a workshop readout. Docue works out which parts of it are the
skeleton and which are filled in fresh each time. Anyone else can then find
that template by describing what they need rather than remembering its
filename, answer a short interview about their case, and get back a finished
document with the original's formatting untouched.

The formatting part is the hard part. Docue edits the document's XML in place
rather than regenerating it, so styles, headers, numbering, and theme survive
intact.

```
backend/    FastAPI + PostgreSQL/pgvector + S3  →  backend/README.md
frontend/   React + TypeScript + Vite           →  frontend/README.md
```

## How it fits together

```
upload  →  ingest  →  search  →  converse  →  plan  →  compile
           │          │          │            │        │
           detect     embed &    ask only     answers  edit the XML
           editable   index by   what can't   → change in place, keep
           regions    meaning    be inferred  spec     the formatting
```

Ingestion, conversation, planning, and compilation all live in the backend.
The frontend owns discovery, the interview UI, and document preview — which it
renders **in the browser** (`docx-preview`, `pptx-preview`, `exceljs`) so a file
can be previewed before it is ever uploaded.

## Running it

You need Docker, [uv](https://docs.astral.sh/uv/), Node, and an
OpenAI-compatible LLM endpoint.

```bash
cp backend/.env.example backend/.env   # fill in LLM_API_KEY and JWT_SECRET
./dev.sh
```

That is the whole thing. `dev.sh` starts Postgres and MinIO, waits for both to
report healthy, syncs dependencies, applies migrations, seeds the first
administrator if the database is empty, and runs the API and the interface
together with their logs interleaved. Ctrl-C stops both. It is safe to re-run.

| Command | Does |
|---|---|
| `./dev.sh` | Everything — services, API, interface |
| `./dev.sh backend` | Services and API only |
| `./dev.sh frontend` | Interface only, against an API you started elsewhere |
| `./dev.sh stop` | Stop the containers, keep the data |
| `./dev.sh reset` | Destroy the database and rebuild it, after confirming |

<details>
<summary>Running the steps by hand instead</summary>

```bash
# 1. Services and API
cd backend
docker compose up -d          # Postgres (pgvector) + MinIO
uv sync
uv run alembic upgrade head
uv run python scripts/seed_admin.py
uv run uvicorn app.main:app --reload

# 2. Interface, in a second terminal
cd frontend
npm install
npm run dev
```
</details>

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API + `/docs` | http://localhost:8000 |
| MinIO console | http://localhost:9001 |

Vite proxies `/api/v1` to port 8000, so keep the frontend's API base URL
relative — an absolute one makes every call cross-origin, and the backend
allows only a small fixed set of origins.

Each side's README covers its own configuration, layout, and verification
scripts in full.

## A note on history

This repository was assembled from two that were developed separately. Both
histories were rewritten so their files sit under `backend/` and `frontend/`
throughout the past — `git log backend/app/main.py` answers correctly for
commits made long before the merge.

One exception: the frontend's files moved up a level shortly before the merge,
so tracing a frontend file past that point needs `--follow`.

```bash
git log --follow -- frontend/src/App.tsx
```
