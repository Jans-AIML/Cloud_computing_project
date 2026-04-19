"""
Database schema initialisation.

Run this once after RDS is created:
    python -m app.core.schema

Or call init_schema() from a Lambda admin endpoint (requires admin credentials).
"""

SCHEMA_SQL = """
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Sources ──────────────────────────────────────────────────────────────────
-- Tracks the origin of each document: URL, upload, email, etc.
CREATE TABLE IF NOT EXISTS sources (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('url', 'pdf', 'email', 'email_redacted')),
    source_url      TEXT,
    title           TEXT,
    author          TEXT,         -- for public docs only; NULL for emails
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    consent_flag    BOOLEAN DEFAULT FALSE,  -- TRUE = contributor consented (emails)
    contributor_id  TEXT,                   -- opaque ID (no PII) of the person who uploaded
    metadata        JSONB DEFAULT '{}'
);

-- ── Documents ─────────────────────────────────────────────────────────────────
-- Parsed, (redacted) full text of each source.
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    raw_s3_key      TEXT,           -- key in PRIVATE bucket (raw email); NULL for public
    clean_s3_key    TEXT,           -- key in PUBLIC bucket (redacted/parsed text)
    text_snippet    TEXT,           -- first 500 chars for preview
    word_count      INT,
    language        TEXT DEFAULT 'en',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    deleted_at      TIMESTAMPTZ,    -- soft-delete support
    UNIQUE (source_id)
);

-- ── Evidence Cards ────────────────────────────────────────────────────────────
-- A human-readable excerpt from a document, searchable and citable.
CREATE TABLE IF NOT EXISTS evidence_cards (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    excerpt         TEXT NOT NULL,      -- redacted excerpt (≤ 500 words)
    topic_tags      TEXT[] DEFAULT '{}',
    date_mentioned  DATE,               -- date referenced in the excerpt (if any)
    citation_url    TEXT,               -- canonical URL
    citation_label  TEXT,               -- "CBC News, Mar 10 2026"
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ── Chunks (for RAG retrieval) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    chunk_text      TEXT NOT NULL,
    token_count     INT,
    embedding       vector(1536),       -- Titan Embeddings v2 dimension
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

-- pgvector HNSW index for fast ANN search
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Full-text search index (hybrid retrieval)
CREATE INDEX IF NOT EXISTS chunks_fts_idx
    ON chunks USING gin (to_tsvector('english', chunk_text));

-- ── PII Audit ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pii_audit (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_type     TEXT NOT NULL,
    score           REAL NOT NULL,
    char_start      INT,
    char_end        INT,
    redacted_at     TIMESTAMPTZ DEFAULT now()
);

-- ── RAG Queries (audit trail) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_queries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question        TEXT NOT NULL,
    answer          TEXT,
    chunk_ids       UUID[],             -- which chunks were retrieved
    model_id        TEXT,
    input_tokens    INT,
    output_tokens   INT,
    latency_ms      INT,
    asked_at        TIMESTAMPTZ DEFAULT now()
);
"""


def init_schema(conn) -> None:
    """Create all tables if they do not exist."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


if __name__ == "__main__":
    from app.core.database import get_connection

    conn = get_connection()
    init_schema(conn)
    conn.close()
    print("Schema initialised successfully.")
