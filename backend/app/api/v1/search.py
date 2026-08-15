"""Template discovery (plan §6, RAG-1)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import optional_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResult, SignalScores
from app.search.hybrid import search as run_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search_templates(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
) -> SearchResponse:
    """Natural-language template search, hybrid BM25 + vector fused with RRF.

    POST rather than GET: queries are prose and can carry anything a user types,
    and the plan's §6 contract already names it POST.

    **The caller is resolved here even though the result set does not yet depend
    on it.** `optional_user` rather than `current_user`, to match `GET
    /templates`, which has always served the approved library to signed-out
    visitors; requiring a token here would be a product change rather than the
    hardening this is. What the caller buys today is that the filter is built by
    `app.access.templates.search_predicate` instead of a constant inlined in the
    SQL -- so restricting a template to named users later changes one function,
    not the search stack.
    """
    outcome = run_search(db, payload.query, top_k=payload.top_k, viewer=user)
    return SearchResponse(
        query=payload.query,
        latency_ms=outcome.latency_ms,
        lexical_candidates=outcome.lexical_candidates,
        vector_candidates=outcome.vector_candidates,
        degraded=outcome.degraded,
        results=[
            SearchResult(
                template_id=hit.template_id,
                title=hit.title,
                format=hit.format,
                purpose=hit.purpose,
                when_to_use=hit.when_to_use,
                audience=hit.audience,
                tags=hit.tags,
                form_id=hit.form_id,
                current_version_id=hit.current_version_id,
                score=hit.score,
                match_explanation=hit.match_explanation,
                highlights=hit.highlights,
                scores=SignalScores(
                    bm25_rank=hit.bm25_rank,
                    vector_rank=hit.vector_rank,
                    bm25=hit.bm25_score,
                    vector=hit.vector_score,
                    rrf=hit.score,
                ),
            )
            for hit in outcome.hits
        ],
    )
