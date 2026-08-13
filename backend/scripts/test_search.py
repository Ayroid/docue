"""Hybrid search over the real corpus, proven inside a rolled-back transaction.

    uv run python scripts/test_search.py                  # RRF checks only
    TEMPLATEHUB_LIVE_LLM=1 uv run python scripts/test_search.py   # full path

The live half seeds the five corpus documents through the real enrichment
pass -- classify, metadata, embed -- inserts them, runs the two demo queries
from plan §13, and **rolls the whole thing back**. Nothing is written to the
shared database, including the `0003` columns, which the script creates inside
the same transaction when they are not there yet. That means this proves the
search path before the migration is applied anywhere.

The two queries are the demo, and they are chosen to fail without one half each:

  * "record what we agreed and who's doing what" shares no word with "Minutes
    of Meeting" -- BM25 scores it at nothing, the vector half has to find it.
  * "BFL" is an internal acronym with no distributional meaning -- embeddings
    handle it badly, BM25 has to find it.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.ingestion.enrich import enrich  # noqa: E402
from app.search.hybrid import _rrf, search  # noqa: E402

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"

CORPUS = [
    ("MOM Sample.xlsx", "xlsx"),
    ("BFL Sample.xlsx", "xlsx"),
    ("POC List sample.xlsx", "xlsx"),
    ("BRD Sample.docx", "docx"),
    ("Workshop Readout Template.pptx", "pptx"),
]

DEMO_QUERIES = [
    ("record what we agreed and who's doing what", "MOM Sample.xlsx", "semantic"),
    ("BFL", "BFL Sample.xlsx", "lexical"),
]

_DDL = """
ALTER TABLE templates
    ADD COLUMN IF NOT EXISTS purpose TEXT,
    ADD COLUMN IF NOT EXISTS when_to_use TEXT,
    ADD COLUMN IF NOT EXISTS audience TEXT,
    ADD COLUMN IF NOT EXISTS category VARCHAR(100),
    ADD COLUMN IF NOT EXISTS tags TEXT[],
    ADD COLUMN IF NOT EXISTS embedding vector(1024),
    ADD COLUMN IF NOT EXISTS metadata_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS metadata_prompt_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ
"""


def check_rrf() -> list[str]:
    """Fusion behaviour, with no database and no model."""
    failures: list[str] = []

    # Agreement beats a single strong signal: `b` is 2nd and 2nd, `a` is 1st in
    # one ranking and absent from the other. That preference is the entire
    # reason to fuse rather than to pick a winner per query.
    scores = _rrf([["a", "b", "c"], ["d", "b", "c"]])
    if not scores["b"] > scores["a"]:
        failures.append("RRF ranked a single-signal hit above one both signals agreed on")
    if not scores["b"] > scores["c"]:
        failures.append("RRF ignored rank order within a signal")

    # Ranks, not scores. A lexical score of 0.29 and a cosine of 0.91 must not
    # let the vector half dominate by virtue of its range.
    if _rrf([["x"]])["x"] != _rrf([["y"]])["y"]:
        failures.append("RRF is sensitive to something other than position")

    # An empty ranking is a degraded half, not an error.
    if _rrf([["a"], []])["a"] <= 0:
        failures.append("RRF broke when one signal returned nothing")
    return failures


def _seed(db: Session, name: str, fmt: str) -> tuple[uuid.UUID, str]:
    data = (FILES_DIR / name).read_bytes()
    result = enrich(data, fmt, filename=name)
    template_id = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO templates (id, title, original_filename, format, status,
                                   form_id, purpose, when_to_use, audience, category,
                                   tags, embedding, created_at, updated_at)
            VALUES (:id, :title, :fn, :fmt, 'active', :form_id, :purpose, :when, :aud,
                    :cat, :tags, CAST(:emb AS vector), now(), now())
            """
        ),
        {
            "id": str(template_id),
            "title": result.metadata.title,
            "fn": name,
            "fmt": fmt,
            "form_id": None,
            "purpose": result.metadata.purpose,
            "when": result.metadata.when_to_use,
            "aud": result.metadata.audience,
            "cat": result.metadata.category,
            "tags": "{" + ",".join(f'"{t}"' for t in result.metadata.tags) + "}",
            "emb": "[" + ",".join(f"{v:.6f}" for v in (result.embedding or [])) + "]"
            if result.embedding
            else None,
        },
    )
    print(
        f"  seeded {name:<34} {result.regions_labelled:>3} labelled, "
        f"embedded={result.embedding is not None}, {result.elapsed_ms}ms"
    )
    return template_id, result.metadata.title


def run_live() -> list[str]:
    failures: list[str] = []
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection)
    try:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        connection.exec_driver_sql(_DDL)
        print("  columns ensured inside the transaction (rolled back at the end)\n")

        titles: dict[str, str] = {}
        for name, fmt in CORPUS:
            if not (FILES_DIR / name).exists():
                print(f"  {name:<34} SKIP (not on this machine)")
                continue
            template_id, title = _seed(db, name, fmt)
            titles[name] = title
        db.flush()

        print()
        for query, expected_file, why in DEMO_QUERIES:
            outcome = search(db, query, top_k=3)
            print(f'  "{query}"  ({why} half should carry it)')
            if outcome.degraded:
                print(f"    degraded: {outcome.degraded}")
            for position, hit in enumerate(outcome.hits, start=1):
                marker = "->" if position == 1 else "  "
                print(
                    f"    {marker} {hit.title[:46]:<46} rrf={hit.score:.5f} "
                    f"bm25=#{hit.bm25_rank} vec=#{hit.vector_rank}"
                )
                print(f"       {hit.match_explanation}")
                for highlight in hit.highlights:
                    print(f"       {highlight[:150]}")
            if not outcome.hits:
                failures.append(f"{query!r} returned nothing")
                continue
            expected_title = titles.get(expected_file)
            if expected_title and outcome.hits[0].title != expected_title:
                failures.append(
                    f"{query!r} ranked {outcome.hits[0].title!r} first, expected {expected_title!r}"
                )
            print(f"    latency {outcome.latency_ms}ms, "
                  f"{outcome.lexical_candidates} lexical / {outcome.vector_candidates} vector candidates\n")
    finally:
        db.close()
        transaction.rollback()
        connection.close()

    with engine.connect() as check:
        leaked = check.exec_driver_sql(
            "select 1 from information_schema.columns "
            "where table_name='templates' and column_name='embedding'"
        ).fetchone()
        print(f"  rolled back -- embedding column persisted? {bool(leaked)}")
        if leaked:
            failures.append("the transaction leaked schema into the shared database")
    return failures


def main() -> int:
    print("fusion behaviour (no database, no model)")
    failures = check_rrf()
    print(f"  {'PASS' if not failures else 'FAIL'} -- agreement wins, position-only, degrades to one half")

    if not os.environ.get("TEMPLATEHUB_LIVE_LLM"):
        print("\nlive search: SKIPPED (set TEMPLATEHUB_LIVE_LLM=1 to run it)")
        print("  Seeds the corpus through the real enrichment pass; roughly $0.30.")
    else:
        print("\nlive search over the corpus, inside a transaction that rolls back")
        failures += run_live()

    print()
    if failures:
        print(f"search: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("search: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
