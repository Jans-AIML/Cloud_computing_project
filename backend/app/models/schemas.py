"""Pydantic schemas for documents, evidence cards, and RAG."""

from __future__ import annotations

from datetime import datetime, date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ── Source / Upload ───────────────────────────────────────────────────────────

class UploadRequest(BaseModel):
    filename: str = Field(..., description="Original filename (PDF or .eml/.txt)")
    content_type: str = Field(..., description="MIME type")
    source_type: str = Field("pdf", description="'pdf' | 'url' | 'email'")
    source_url: str | None = None
    consent_given: bool = Field(
        False,
        description="Must be True for email submissions — contributor consent to PII redaction",
    )

    def validate_email_consent(self) -> None:
        if self.source_type == "email" and not self.consent_given:
            raise ValueError(
                "Consent is required to submit an email. "
                "The contributor must agree to PII redaction before upload."
            )


class UploadResponse(BaseModel):
    document_id: UUID
    upload_url: str = Field(..., description="Pre-signed S3 PUT URL (expires in 15 min)")
    expires_in_seconds: int = 900


# ── Evidence Cards ────────────────────────────────────────────────────────────

class EvidenceCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    excerpt: str
    topic_tags: list[str] = []
    date_mentioned: date | None = None
    citation_url: str | None = None
    citation_label: str | None = None
    created_at: datetime


class DocumentSummary(BaseModel):
    id: UUID
    source_type: str
    title: str | None
    source_url: str | None
    text_snippet: str | None
    word_count: int | None
    ingested_at: datetime
    evidence_card_count: int = 0


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    top_k: int = Field(8, ge=1, le=20)
    topic_filter: list[str] = []
    date_from: date | None = None
    date_to: date | None = None


class SearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_text: str
    score: float = Field(..., description="Cosine similarity (0–1)")
    citation_label: str | None
    citation_url: str | None
    topic_tags: list[str] = []
    source_type: str | None = None


# ── RAG ───────────────────────────────────────────────────────────────────────

class RagRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=800)
    top_k: int = Field(6, ge=1, le=10)
    topic_filter: list[str] = []


class Citation(BaseModel):
    label: str
    url: str | None
    excerpt: str
    source_type: str | None = None


class RagResponse(BaseModel):
    answer: str
    citations: list[Citation]
    input_tokens: int
    output_tokens: int
    latency_ms: int


# ── Briefs ────────────────────────────────────────────────────────────────────

class BriefRequest(BaseModel):
    template_id: str = Field(
        ...,
        description="'ocdsb_submission' | 'councillor_letter' | 'mpp_letter' | 'op_ed'",
    )
    goal: str = Field(
        ...,
        max_length=300,
        description="e.g. 'Request restoration of full JK programming at Lady Evelyn'",
    )
    audience: str = Field(
        ...,
        max_length=200,
        description="e.g. 'OCDSB Supervisor of Education'",
    )
    tone: str = Field("formal", description="'formal' | 'community'")
    extra_context: str = Field("", max_length=500)


class BriefResponse(BaseModel):
    draft: str
    footnotes: list[Citation]
    template_id: str
    input_tokens: int
    output_tokens: int


class BriefTemplate(BaseModel):
    id: str
    name: str
    description: str
    typical_length: str
