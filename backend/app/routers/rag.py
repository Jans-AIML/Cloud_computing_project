"""
/rag — RAG Q&A with verifiable citations (non-streaming and streaming).
All requests routed through API Gateway → Lambda.
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.logging import logger
from app.models.schemas import RagRequest, RagResponse
from app.services.bedrock_client import embed_text, stream_claude
from app.services.rag import hybrid_search, rag_query, _build_context_block, _RAG_SYSTEM_PROMPT

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query", response_model=RagResponse)
def query(payload: RagRequest) -> RagResponse:
    """
    Non-streaming RAG Q&A.
    Returns a structured answer with inline citations and token usage.
    """
    logger.info("rag_query", question=payload.question[:80])
    with get_db() as conn:
        return rag_query(
            conn,
            question=payload.question,
            top_k=payload.top_k,
            topic_filter=payload.topic_filter if payload.topic_filter else None,
        )


@router.post("/stream")
def stream(payload: RagRequest) -> StreamingResponse:
    """
    Streaming RAG Q&A using AWS Bedrock response streaming.
    Returns a text/event-stream response; each SSE event is a text chunk.
    Streaming reduces perceived latency — users see the first tokens immediately.
    """
    logger.info("rag_stream", question=payload.question[:80])

    query_embedding = embed_text(payload.question)

    with get_db() as conn:
        chunks = hybrid_search(
            conn,
            query_embedding=query_embedding,
            query_text=payload.question,
            top_k=payload.top_k,
            topic_filter=payload.topic_filter if payload.topic_filter else None,
        )

    context = _build_context_block(chunks) if chunks else "No relevant evidence found."
    user_message = f"Context:\n{context}\n\nQuestion: {payload.question}"

    def event_generator():
        for text_chunk in stream_claude(_RAG_SYSTEM_PROMPT, user_message):
            # Server-Sent Events format
            yield f"data: {text_chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
