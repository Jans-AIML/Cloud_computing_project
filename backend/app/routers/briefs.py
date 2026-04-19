"""
/briefs — generate letters and advocacy briefs grounded in evidence cards.
"""

import json
from fastapi import APIRouter, HTTPException, status

from app.core.database import get_db
from app.core.logging import logger
from app.models.schemas import BriefRequest, BriefResponse, BriefTemplate, Citation
from app.services.bedrock_client import embed_text, invoke_claude
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
1. Use ONLY the evidence provided — no invented facts, dates, or statistics.
2. Every factual claim must be supported by a citation [N] linked to the context.
3. Do NOT include personal names of private individuals.
4. Tone: {tone}.
5. Audience: {audience}.
6. Goal: {goal}.
7. Do NOT make partisan political statements. Focus on facts, evidence, and community impact.
8. End with a clear, respectful call to action.
9. Return valid JSON: {{"draft": "...", "footnotes": [{{"label":"...", "url":"...", "excerpt":"..."}}]}}"""


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
        chunks = hybrid_search(conn, query_embedding, payload.goal, top_k=8)

    context = _build_context_block(chunks) if chunks else "No relevant evidence found in corpus."

    system_prompt = _BRIEF_SYSTEM_PROMPT.format(
        template_name=template.name,
        tone=payload.tone,
        audience=payload.audience,
        goal=payload.goal,
    )
    user_message = (
        f"Evidence context:\n{context}\n\n"
        f"Additional context from user: {payload.extra_context}\n\n"
        f"Now write the {template.name}."
    )

    result = invoke_claude(system_prompt, user_message, max_tokens=1500, temperature=0.4)

    try:
        parsed = json.loads(result["text"])
        draft = parsed.get("draft", result["text"])
        footnotes = [
            Citation(
                label=f.get("label", ""),
                url=f.get("url"),
                excerpt=f.get("excerpt", ""),
            )
            for f in parsed.get("footnotes", [])
        ]
    except (json.JSONDecodeError, KeyError):
        draft = result["text"]
        footnotes = [
            Citation(
                label=c.get("citation_label") or "Source",
                url=c.get("citation_url"),
                excerpt=c["chunk_text"][:200],
            )
            for c in chunks[:5]
        ]

    return BriefResponse(
        draft=draft,
        footnotes=footnotes,
        template_id=payload.template_id,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
    )
