"""Request and response models for `POST /search` (plan §6).

Field names follow the plan's stated contract so Track C can build against it
without a translation layer: `match_explanation` plus a per-signal `scores`
breakdown, because making the ranking visible is the feature, not the debugging.
"""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=25)


class SignalScores(BaseModel):
    bm25_rank: int | None = None
    vector_rank: int | None = None
    bm25: float | None = None
    vector: float | None = None
    rrf: float


class SearchResult(BaseModel):
    template_id: str
    title: str
    format: str
    purpose: str | None = None
    when_to_use: str | None = None
    audience: str | None = None
    tags: list[str] = []
    form_id: str | None = None
    current_version_id: str | None = None
    score: float
    match_explanation: str
    highlights: list[str] = []
    scores: SignalScores


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    latency_ms: int
    lexical_candidates: int
    vector_candidates: int
    degraded: str | None = None
