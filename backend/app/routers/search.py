"""
/search — keyword + vector hybrid search over evidence chunks.
All search requests go through API Gateway → this Lambda handler.
"""

from fastapi import APIRouter, Query, HTTPException, status

from app.core.database import get_db
from app.core.logging import logger
from app.models.schemas import SearchResult
from app.services.llm_factory import embed_text
from app.services.rag import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=3, max_length=500, description="Search query"),
    top_k: int = Query(8, ge=1, le=20),
    topic: list[str] = Query([], description="Filter by topic tags"),
) -> list[SearchResult]:
    """
    Hybrid vector + keyword search over the evidence corpus.
    Returns ranked chunks with citation metadata.
    """
    logger.info("search_request", query=q, top_k=top_k, topics=topic)

    query_embedding = embed_text(q)

    with get_db() as conn:
        chunks = hybrid_search(
            conn,
            query_embedding=query_embedding,
            query_text=q,
            top_k=top_k,
            topic_filter=topic if topic else None,
        )

    return [
        SearchResult(
            chunk_id=c["chunk_id"],
            document_id=c["document_id"],
            chunk_text=c["chunk_text"],
            score=float(c["score"]),
            citation_label=c.get("citation_label"),
            citation_url=c.get("citation_url"),
            topic_tags=c.get("topic_tags") or [],
            source_type=c.get("source_type"),
        )
        for c in chunks
    ]
