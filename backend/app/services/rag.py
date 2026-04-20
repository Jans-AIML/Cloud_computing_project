"""
RAG service — hybrid retrieval (dense pgvector + keyword tsvector) + Bedrock completion.

Pipeline:
  1. Embed the user question with Titan Embeddings v2.
  2. Run parallel dense (ANN) and keyword (FTS) search against chunks table.
  3. Re-rank by combined score.
  4. Build a citation-aware prompt.
  5. Call Claude 3 with a strict "cite only from context" system prompt.
  6. Parse the JSON-structured answer + citations.
"""

import json
import time
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import logger
from app.models.schemas import Citation, RagResponse, SearchResult
from app.services.llm_factory import embed_text, invoke_llm, stream_llm

# System prompt enforces citation-first, no hallucination policy
_RAG_SYSTEM_PROMPT = """You are CEEP, the Community Evidence & Engagement Platform assistant.
Your role is to help community members understand facts about Lady Evelyn and other Ottawa
community schools using ONLY the evidence excerpts provided below.

Rules you must follow:
1. Answer ONLY from the provided context. If the context does not contain the answer, say:
   "I don't have evidence for this in the current corpus. You may want to add more documents."
2. Every factual claim in your answer must be followed by a citation marker [N] corresponding
   to the source in the context.
3. Never invent URLs, dates, names, or statistics.
4. Never target or identify specific private individuals.
5. Keep answers concise (2–4 paragraphs maximum).
6. Return your response as valid JSON with this exact structure:
   {"answer": "...", "citations": [{"label": "...", "url": "...", "excerpt": "..."}]}
"""


def _build_context_block(chunks: list[dict]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, 1):
        label = chunk.get("citation_label") or "Unknown source"
        url = chunk.get("citation_url") or ""
        lines.append(f"[{i}] Source: {label} — {url}\n{chunk['chunk_text']}\n")
    return "\n---\n".join(lines)


def hybrid_search(
    conn,
    query_embedding: list[float],
    query_text: str,
    top_k: int = 8,
    topic_filter: list[str] | None = None,
) -> list[dict]:
    """
    Hybrid search: dense cosine similarity + BM25-style keyword search.
    Returns list of chunk dicts sorted by combined score.
    """
    settings = get_settings()
    top_k = min(top_k, settings.max_rag_results)

    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    topic_clause = ""
    params: list = [embedding_str, query_text, top_k * 2]

    if topic_filter:
        topic_clause = "AND ec.topic_tags && %s::text[]"
        params.insert(2, topic_filter)

    sql = f"""
    WITH vector_search AS (
        SELECT
            c.id                    AS chunk_id,
            c.document_id,
            c.chunk_text,
            1 - (c.embedding <=> %s::vector) AS vector_score,
            0.0                     AS keyword_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    ),
    keyword_search AS (
        SELECT
            c.id                    AS chunk_id,
            c.document_id,
            c.chunk_text,
            0.0                     AS vector_score,
            ts_rank(
                to_tsvector('english', c.chunk_text),
                plainto_tsquery('english', %s)
            )                       AS keyword_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL
          AND to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', %s)
        LIMIT %s
    ),
    combined AS (
        SELECT chunk_id, document_id, chunk_text,
               MAX(vector_score) AS vector_score,
               MAX(keyword_score) AS keyword_score
        FROM (SELECT * FROM vector_search UNION ALL SELECT * FROM keyword_search) u
        GROUP BY chunk_id, document_id, chunk_text
    )
    SELECT
        combined.chunk_id,
        combined.document_id,
        combined.chunk_text,
        (0.7 * combined.vector_score + 0.3 * combined.keyword_score) AS score,
        ec.citation_label,
        ec.citation_url,
        ec.topic_tags
    FROM combined
    LEFT JOIN evidence_cards ec ON ec.document_id = combined.document_id
    {topic_clause}
    ORDER BY score DESC
    LIMIT %s;
    """

    # Build full params list
    full_params = [
        embedding_str,   # vector_search embedding
        embedding_str,   # vector_search ORDER BY
        top_k * 2,       # vector_search LIMIT
        query_text,      # keyword_search ts_rank
        query_text,      # keyword_search WHERE
        top_k * 2,       # keyword_search LIMIT
    ]
    if topic_filter:
        full_params.append(topic_filter)
    full_params.append(top_k)

    with conn.cursor() as cur:
        cur.execute(sql, full_params)
        rows = cur.fetchall()

    return [dict(row) for row in rows]


def rag_query(conn, question: str, top_k: int = 6, topic_filter: list[str] | None = None) -> RagResponse:
    """Full RAG pipeline: embed → retrieve → complete → parse citations."""
    t0 = time.monotonic()

    # 1. Embed question
    query_embedding = embed_text(question)

    # 2. Retrieve relevant chunks
    chunks = hybrid_search(conn, query_embedding, question, top_k=top_k, topic_filter=topic_filter)

    if not chunks:
        return RagResponse(
            answer="I don't have any evidence in the corpus matching your question. "
                   "Try adding relevant documents first.",
            citations=[],
            input_tokens=0,
            output_tokens=0,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    # 3. Build context block
    context = _build_context_block(chunks)
    user_message = f"Context:\n{context}\n\nQuestion: {question}"

    # 4. Call LLM (Ollama locally, Bedrock in production)
    result = invoke_llm(_RAG_SYSTEM_PROMPT, user_message, max_tokens=1024)

    # 5. Parse structured JSON response
    # The LLM sometimes wraps JSON in markdown fences or extra prose — extract robustly.
    import re as _re
    raw_text = result["text"]
    parsed = None
    # Try direct parse, then extract the first {...} block
    for candidate in [raw_text, *(_re.findall(r'\{[\s\S]*\}', raw_text))]:
        try:
            parsed = json.loads(candidate)
            break
        except (json.JSONDecodeError, ValueError):
            continue

    if parsed and isinstance(parsed, dict) and "answer" in parsed:
        answer = parsed["answer"]
        citations = [
            Citation(
                label=c.get("label", ""),
                url=c.get("url"),
                excerpt=c.get("excerpt", ""),
            )
            for c in parsed.get("citations", [])
        ]
    else:
        # Graceful fallback: return raw text, build citations from retrieved chunks
        answer = raw_text
        citations = [
            Citation(
                label=c.get("citation_label") or "Source",
                url=c.get("citation_url"),
                excerpt=c["chunk_text"][:200],
            )
            for c in chunks[:3]
        ]

    # 6. Audit log query
    _log_rag_query(
        conn,
        question=question,
        answer=answer,
        chunk_ids=[c["chunk_id"] for c in chunks],
        model_id=get_settings().bedrock_claude_model_id,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        latency_ms=result["latency_ms"],
    )

    return RagResponse(
        answer=answer,
        citations=citations,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        latency_ms=result["latency_ms"],
    )


def _log_rag_query(conn, **kwargs) -> None:
    chunk_ids = kwargs.pop("chunk_ids", [])
    sql = """
    INSERT INTO rag_queries
        (question, answer, chunk_ids, model_id, input_tokens, output_tokens, latency_ms)
    VALUES (%s, %s, %s::uuid[], %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                kwargs["question"],
                kwargs["answer"],
                chunk_ids,
                kwargs["model_id"],
                kwargs["input_tokens"],
                kwargs["output_tokens"],
                kwargs["latency_ms"],
            ),
        )
