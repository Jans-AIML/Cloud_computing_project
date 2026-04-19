"""
Local ETL — runs the ingest pipeline in-process (no Glue, no SQS).

In production, Glue jobs handle this asynchronously.
Locally, we call the same logic as Python functions, triggered
immediately after the file is received at /documents/local-upload/{id}.

Steps: extract text → (light PII scrub) → chunk → embed → insert DB
"""

import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.logging import logger
from app.services.llm_factory import embed_text
from app.services.local_storage import read_file, save_file

# ── Local PII scrub (regex-based, no Comprehend needed) ───────────────────────
# This is a best-effort local substitute. AWS Comprehend is used in production
# for higher accuracy. For local testing with dummy/public data this is fine.

_PII_PATTERNS = [
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"), "[REDACTED-NAME]"),              # simple name pattern
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b"), "[REDACTED-EMAIL]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "[REDACTED-PHONE]"),
    (re.compile(r"\b\d{1,5}\s+\w[\w\s]+(?:Street|St|Ave|Avenue|Road|Rd|Drive|Dr|Blvd|Court|Ct)\b", re.I), "[REDACTED-ADDRESS]"),
]


def _local_pii_scrub(text: str) -> tuple[str, int]:
    """
    Regex-based PII removal.
    Returns (scrubbed_text, redaction_count).
    NOTE: Less accurate than AWS Comprehend. For local testing only.
    """
    count = 0
    for pattern, replacement in _PII_PATTERNS:
        matches = pattern.findall(text)
        count += len(matches)
        text = pattern.sub(replacement, text)
    return text, count


# ── URL fetching ─────────────────────────────────────────────────────────────

def _fetch_url_text(url: str) -> str:
    """Fetch a web page and return its visible text."""
    headers = {"User-Agent": "Mozilla/5.0 (CEEP research bot; educational use)"}
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from uploaded bytes."""
    if filename.lower().endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text
            import io
            return extract_text(io.BytesIO(file_bytes))
        except ImportError:
            logger.warning("pdfminer_not_installed_falling_back_to_decode")
            return file_bytes.decode("latin-1", errors="replace")
    # Plain text / email
    for enc in ("utf-8", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


# ── Main entry point ──────────────────────────────────────────────────────────

def run_local_etl(
    document_id: str,
    s3_key: str,
    source_type: str,
    consent_flag: bool,
    conn,
    source_url: str | None = None,
) -> None:
    """
    Run the full ETL pipeline in-process.
    Called synchronously after a local file upload or URL submission.
    """
    settings = get_settings()

    logger.info("local_etl_start", document_id=document_id, source_type=source_type)

    # 1. Skip emails without consent (same rule as production)
    if source_type == "email" and not consent_flag:
        logger.warning("local_etl_skip_no_consent", document_id=document_id)
        return

    # 2. Get text — fetch from URL or read from local storage
    if source_type == "url" and source_url:
        logger.info("local_etl_fetching_url", document_id=document_id, url=source_url)
        text = _fetch_url_text(source_url)
    else:
        raw_bytes = read_file(s3_key)
        filename = Path(s3_key).name
        text = _extract_text(raw_bytes, filename)
    logger.info("local_etl_extracted", document_id=document_id, chars=len(text))

    # 3. PII scrub
    clean_text, redaction_count = _local_pii_scrub(text)
    logger.info("local_etl_pii_scrub", document_id=document_id, redactions=redaction_count)

    # 4. Save clean text to local storage
    clean_key = f"clean/{document_id}/text.txt"
    save_file(clean_key, clean_text.encode("utf-8"))

    # 5. Chunk
    chunks = _chunk_text(clean_text, settings.chunk_size, settings.chunk_overlap)
    logger.info("local_etl_chunked", document_id=document_id, chunks=len(chunks))

    # 6. Embed and insert into DB
    with conn.cursor() as cur:
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            embedding = embed_text(chunk)
            token_count = len(chunk.split())
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            cur.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, chunk_text, token_count, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                ON CONFLICT (document_id, chunk_index) DO UPDATE
                    SET chunk_text  = EXCLUDED.chunk_text,
                        token_count = EXCLUDED.token_count,
                        embedding   = EXCLUDED.embedding
                """,
                (document_id, i, chunk, token_count, embedding_str),
            )

        # 7. Update document record
        snippet = clean_text[:500]
        word_count = len(clean_text.split())
        cur.execute(
            """
            UPDATE documents
            SET clean_s3_key = %s, text_snippet = %s, word_count = %s, ingested_at = now()
            WHERE id = %s
            """,
            (clean_key, snippet, word_count, document_id),
        )

        # 8. Create/update evidence card
        cur.execute(
            """
            INSERT INTO evidence_cards (document_id, excerpt)
            VALUES (%s, %s)
            ON CONFLICT (document_id) DO UPDATE SET excerpt = EXCLUDED.excerpt
            """,
            (document_id, snippet),
        )

    conn.commit()
    logger.info("local_etl_done", document_id=document_id, chunks=len(chunks), words=word_count)
