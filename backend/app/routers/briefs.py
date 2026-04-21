"""
/briefs — generate letters and advocacy briefs grounded in evidence cards.
"""

import json
from fastapi import APIRouter, HTTPException, status

from app.core.database import get_db
from app.core.logging import logger
from app.models.schemas import BriefRequest, BriefResponse, BriefTemplate, Citation
from app.services.llm_factory import embed_text, invoke_llm
from app.services.rag import hybrid_search, _build_context_block

router = APIRouter(prefix="/briefs", tags=["briefs"])

# ── Templates ──────────────────────────────────────────────────────────────────
TEMPLATES: dict[str, BriefTemplate] = {
    "ocdsb_submission": BriefTemplate(
        id="ocdsb_submission",
        name="OCDSB Supervisor Submission",
        description="Formal submission to the OCDSB Superintendent / Supervisor of Education",
        typical_length="400–600 words",
    ),
    "councillor_letter": BriefTemplate(
        id="councillor_letter",
        name="Letter to City Councillor",
        description="Letter to the ward councillor requesting support or action",
        typical_length="300–400 words",
    ),
    "mpp_letter": BriefTemplate(
        id="mpp_letter",
        name="Letter to MPP / MP",
        description="Letter to the member of provincial or federal parliament",
        typical_length="300–400 words",
    ),
    "op_ed": BriefTemplate(
        id="op_ed",
        name="Local Op-Ed",
        description="Opinion piece for the Mainstreeter, Ottawa Citizen, or CBC community section",
        typical_length="500–700 words",
    ),
}

# ── System prompt for brief generation ────────────────────────────────────────
_BRIEF_SYSTEM_PROMPT = """You are a community advocacy writing assistant for CEEP.
Write a well-structured {template_name} on behalf of concerned community members.

Rules:
1. Use ONLY the evidence provided in the numbered context below — no invented facts, dates, or statistics.
2. Every factual claim must be followed by an inline citation marker [N] where N is the source number.
3. Do NOT include personal names of private individuals.
4. Tone: {tone}.
5. Audience: {audience}.
6. Goal: {goal}.
7. Do NOT make partisan political statements. Focus on facts, evidence, and community impact.
8. End with a clear, respectful call to action.
9. Return valid JSON with ONLY a "draft" key: {{"draft": "..."}}
   - The draft field must contain only the letter/article text with inline [N] markers.
   - Do NOT add a Footnotes, References, Works Cited, or Sources section inside the draft text.
   - The footnotes will be rendered separately by the application."""


@router.get("/templates", response_model=list[BriefTemplate])
def list_templates() -> list[BriefTemplate]:
    return list(TEMPLATES.values())


@router.post("/generate", response_model=BriefResponse)
def generate_brief(payload: BriefRequest) -> BriefResponse:
    """
    Generate an advocacy brief using evidence from the corpus.
    The brief includes footnotes tied to real evidence cards.
    """
    if payload.template_id not in TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template '{payload.template_id}'. "
                   f"Valid options: {list(TEMPLATES.keys())}",
        )

    template = TEMPLATES[payload.template_id]
    logger.info("brief_generate", template_id=payload.template_id, goal=payload.goal[:60])

    # Retrieve relevant evidence using the goal as the query
    query_embedding = embed_text(payload.goal)

    with get_db() as conn:
        chunks = hybrid_search(conn, query_embedding, payload.goal, top_k=12)

    # Deduplicate chunks by document so each source appears exactly once in
    # the context block. Multiple high-scoring chunks from the same document
    # are merged with " [...] " so the LLM still sees more of that document.
    seen_doc_ids: dict[str, int] = {}  # document_id → index in unique_chunks
    unique_chunks: list[dict] = []
    for chunk in chunks:
        doc_id = str(chunk.get("document_id") or "")
        if doc_id and doc_id in seen_doc_ids:
            idx = seen_doc_ids[doc_id]
            unique_chunks[idx]["chunk_text"] += " [...] " + chunk["chunk_text"]
        else:
            new_chunk = dict(chunk)
            unique_chunks.append(new_chunk)
            if doc_id:
                seen_doc_ids[doc_id] = len(unique_chunks) - 1

    context = _build_context_block(unique_chunks) if unique_chunks else "No relevant evidence found in corpus."

    system_prompt = _BRIEF_SYSTEM_PROMPT.format(
        template_name=template.name,
        tone=payload.tone,
        audience=payload.audience,
        goal=payload.goal,
    )
    user_message = (
        f"Evidence context:\n{context}\n\n"
        f"Additional context from user: {payload.extra_context}\n\n"
        f"Now write the {template.name}. Remember: return only {{\"draft\": \"...\"}} — "
        f"no footnotes section inside the draft text."
    )

    result = invoke_llm(system_prompt, user_message, max_tokens=1500, temperature=0.4)

    # Parse draft from LLM response
    try:
        parsed = json.loads(result["text"])
        draft = parsed.get("draft", result["text"])
    except (json.JSONDecodeError, KeyError):
        draft = result["text"]

    # Safety net: strip any "Footnotes:" / "References:" trailing section the
    # model may have added despite the instructions.
    import re as _re
    draft = _re.sub(
        r"\n{0,2}(?:Footnotes|References|Sources|Works Cited)\s*:?\s*\n.*",
        "",
        draft,
        flags=_re.IGNORECASE | _re.DOTALL,
    ).rstrip()

    # Build footnotes from the REAL retrieved chunks (deduplicated above).
    # This guarantees accurate source names, real excerpts, and correct URLs.
    footnotes = [
        Citation(
            label=c.get("citation_label") or "Source",
            url=c.get("citation_url"),
            excerpt=c["chunk_text"][:250],
            source_type=c.get("source_type"),
        )
        for c in unique_chunks
    ]

    return BriefResponse(
        draft=draft,
        footnotes=footnotes,
        template_id=payload.template_id,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
    )
