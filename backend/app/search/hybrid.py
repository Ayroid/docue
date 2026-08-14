"""Hybrid retrieval: BM25 + vector, fused with RRF (plan §9, RAG-1).

**Why both halves are mandatory here, not a nice-to-have.** This corpus is full
of internal acronyms -- `MOM`, `BFL`, `POC`, `BRD`, `YMSLI-F-MOM` -- which
embeddings handle badly: they are near-meaningless tokens with no distributional
signal. BM25 nails them. Meanwhile "record what we agreed and who's doing what"
has zero lexical overlap with "Minutes of Meeting", so BM25 scores it at nothing
and the vector search nails it. Either half alone fails one of the two demo
queries.

**Fusion is Reciprocal Rank Fusion, and it is deliberately hand-rolled.** RRF is
`1/(k + rank)` summed across rankings -- about ten lines. Running it here rather
than inside a retriever abstraction is what makes the per-signal ranks
survivable: the UI shows *why* a template matched, with the rank it held in each
signal, and that is a scoring point rather than a debugging aid. A fused score
that arrives without its inputs cannot be explained.

**Ranks, not scores, are what get fused.** BM25 returns `ts_rank_cd` values
around 0.05-0.3 and cosine similarity returns 0.3-0.9; adding or averaging those
directly would let the vector half dominate every query by virtue of its range.
RRF only reads position, which is exactly why it needs no score normalisation
and no per-corpus tuning.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.bedrock import BedrockError, embed

logger = logging.getLogger(__name__)

__all__ = ["SearchHit", "SearchOutcome", "search"]

# The standard RRF constant. Large enough that the gap between rank 1 and rank 2
# does not swamp agreement between the two signals -- a template ranked 3rd by
# both beats one ranked 1st by a single signal and absent from the other, which
# is the behaviour that makes fusion worth doing.
RRF_K = 60

# Kept identical to migration 0003's index expression. If these drift, Postgres
# silently stops using the index and the query falls back to a sequential scan
# that still returns correct results -- slow and green, the worst failure shape.
_TSVECTOR = """
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(form_id, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(purpose, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(when_to_use, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(category, '')), 'C')
"""

# Unapproved templates are invisible to search, exactly as they are to
# `GET /templates`. Written as a correlated EXISTS rather than a join so it can
# be dropped into both halves unchanged, and so neither query grows a row per
# version. An approval gate that only covered the library listing would be no
# gate at all: the search box is how anyone actually finds a template.
_APPROVED = """
  AND EXISTS (
        SELECT 1 FROM template_versions v
        WHERE v.id = templates.current_version_id
          AND v.approval_status = 'approved'
  )
"""

_LEXICAL_SQL = f"""
SELECT id::text AS id,
       ts_rank_cd({_TSVECTOR}, plainto_tsquery('english', :q)) AS score,
       ts_headline('english',
                   coalesce(purpose, '') || ' ' || coalesce(when_to_use, ''),
                   plainto_tsquery('english', :q),
                   'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=18, MinWords=6'
       ) AS headline
FROM templates
WHERE status = 'active'
  AND ({_TSVECTOR}) @@ plainto_tsquery('english', :q)
  {_APPROVED}
ORDER BY score DESC
LIMIT :n
"""

# `<=>` is cosine distance, so 1 - distance is similarity. Ordering by the
# operator (not by the expression) is what lets the HNSW index serve the query.
_VECTOR_SQL = f"""
SELECT id::text AS id, 1 - (embedding <=> CAST(:qv AS vector)) AS score
FROM templates
WHERE status = 'active' AND embedding IS NOT NULL
  {_APPROVED}
ORDER BY embedding <=> CAST(:qv AS vector)
LIMIT :n
"""

_HYDRATE_SQL = """
SELECT id::text AS id, title, format, purpose, when_to_use, audience, category,
       tags, form_id, house_pattern, current_version_id::text AS current_version_id
FROM templates
WHERE id = ANY(CAST(:ids AS uuid[]))
"""


@dataclass
class SearchHit:
    template_id: str
    title: str
    format: str
    purpose: str | None
    when_to_use: str | None
    audience: str | None
    tags: list[str]
    form_id: str | None
    current_version_id: str | None
    score: float
    bm25_rank: int | None
    vector_rank: int | None
    bm25_score: float | None
    vector_score: float | None
    highlights: list[str] = field(default_factory=list)

    @property
    def match_explanation(self) -> str:
        """Plain English, derived from the ranks -- never written by a model.

        An LLM-written explanation can describe a match that did not actually
        drive the ranking. This says only what the retrieval did.
        """
        if self.bm25_rank and self.vector_rank:
            return (
                f"Matched on both meaning (#{self.vector_rank}) and keywords "
                f"(#{self.bm25_rank})."
            )
        if self.vector_rank:
            return f"Matched on meaning (#{self.vector_rank}); no keyword overlap."
        return f"Matched on keywords (#{self.bm25_rank}); little semantic overlap."


@dataclass
class SearchOutcome:
    hits: list[SearchHit]
    latency_ms: int
    lexical_candidates: int
    vector_candidates: int
    degraded: str | None = None


def _rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def search(db: Session, query: str, *, top_k: int = 5, candidates: int = 25) -> SearchOutcome:
    """Run both signals, fuse, and hydrate the winners.

    Degrades rather than failing: if embedding the query errors -- Bedrock down,
    throttled, unconfigured -- the lexical half still answers, and `degraded`
    says so. Plan §14's rule is that an outage costs capability, not the
    product; on this corpus BM25 alone still finds every template by its
    acronym.
    """
    import time

    started = time.perf_counter()
    query = (query or "").strip()
    if not query:
        return SearchOutcome(hits=[], latency_ms=0, lexical_candidates=0, vector_candidates=0)

    lexical = db.execute(text(_LEXICAL_SQL), {"q": query, "n": candidates}).mappings().all()

    degraded = None
    vector_rows: list[Any] = []
    try:
        vector = embed([query], purpose="search_query", input_type="search_query")[0]
        literal = "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
        vector_rows = db.execute(text(_VECTOR_SQL), {"qv": literal, "n": candidates}).mappings().all()
    except BedrockError as exc:
        logger.warning("vector half unavailable, serving lexical only: %s", exc)
        degraded = "semantic search unavailable; keyword results only"

    lexical_ids = [row["id"] for row in lexical]
    vector_ids = [row["id"] for row in vector_rows]
    fused = _rrf([lexical_ids, vector_ids])
    if not fused:
        return SearchOutcome(
            hits=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            lexical_candidates=len(lexical_ids),
            vector_candidates=len(vector_ids),
            degraded=degraded,
        )

    ordered = sorted(fused, key=lambda doc_id: fused[doc_id], reverse=True)[:top_k]
    rows = {
        row["id"]: row
        for row in db.execute(text(_HYDRATE_SQL), {"ids": "{" + ",".join(ordered) + "}"})
        .mappings()
        .all()
    }
    lexical_by_id = {row["id"]: row for row in lexical}
    vector_by_id = {row["id"]: row for row in vector_rows}

    hits: list[SearchHit] = []
    for doc_id in ordered:
        row = rows.get(doc_id)
        if row is None:  # pragma: no cover - deleted between the two queries
            continue
        headline = (lexical_by_id.get(doc_id) or {}).get("headline")
        hits.append(
            SearchHit(
                template_id=doc_id,
                title=row["title"],
                format=row["format"],
                purpose=row["purpose"],
                when_to_use=row["when_to_use"],
                audience=row["audience"],
                tags=list(row["tags"] or []),
                form_id=row["form_id"],
                current_version_id=row["current_version_id"],
                score=round(fused[doc_id], 6),
                bm25_rank=lexical_ids.index(doc_id) + 1 if doc_id in lexical_ids else None,
                vector_rank=vector_ids.index(doc_id) + 1 if doc_id in vector_ids else None,
                bm25_score=(lexical_by_id.get(doc_id) or {}).get("score"),
                vector_score=(vector_by_id.get(doc_id) or {}).get("score"),
                highlights=[headline] if headline else [],
            )
        )

    return SearchOutcome(
        hits=hits,
        latency_ms=int((time.perf_counter() - started) * 1000),
        lexical_candidates=len(lexical_ids),
        vector_candidates=len(vector_ids),
        degraded=degraded,
    )
