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


class UrlFetchError(Exception):
    """Raised when a URL cannot be fetched (non-200, timeout, DNS failure, etc.)."""

from app.core.config import get_settings
from app.core.logging import logger
from app.services.llm_factory import embed_text
from app.services.local_storage import read_file, save_file

# ── Local PII scrub (regex-based, no Comprehend needed) ───────────────────────
# This is a best-effort local substitute. AWS Comprehend is used in production
# for higher accuracy. For local testing with dummy/public data this is fine.

# PII patterns applied to PRIVATE content (emails) only.
_PII_PATTERNS_PUBLIC = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b"), "[REDACTED-EMAIL]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "[REDACTED-PHONE]"),
    (re.compile(r"\b\d{1,5}\s+\w[\w\s]+(?:Street|St|Ave|Avenue|Road|Rd|Drive|Dr|Blvd|Court|Ct)\b", re.I), "[REDACTED-ADDRESS]"),
]

# Targeted name patterns for emails — only catch names in clearly-personal contexts,
# avoiding the broad two-word title-case match that falsely redacts school/program names.
# IMPORTANT: the combined Name+email pattern must run BEFORE _PII_PATTERNS_PUBLIC so the
# email address hasn't been redacted yet when we try to match "Name <email>".
_PII_PATTERNS_PRIVATE = [
    # "Jane Doe <jane@example.com>" — combined replacement before standalone email scrub
    (re.compile(r'\b[A-Z][a-z]+(?: [A-Z][a-z]+)?\b\s*<[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}>'), '[REDACTED-NAME] <[REDACTED-EMAIL]>'),
    # Email thread timestamp attribution: "Jane Smith, Jan 20, 2026 at 10:27"
    (re.compile(r'\b[A-Z][a-z]+ [A-Z][a-z]+(?=,\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s,.])'), '[REDACTED-NAME]'),
] + _PII_PATTERNS_PUBLIC

# Known school, program, and place names that must never be redacted from emails.
# These are protected before PII scrubbing and restored afterwards.
_EMAIL_SAFELIST: list[str] = [
    "Lady Evelyn",
    "Junior Kindergarten",
    "Senior Kindergarten",
    "Early French Immersion",
    "French Immersion",
    "Extended French",
    "Old Ottawa East",
    "Old Ottawa",
    "Ottawa East",
    "Ottawa Carleton",
    "Ottawa-Carleton",
    "Ottawa Catholic",
    "Ottawa River",
    "Elgin Street",
    "Churchill Avenue",
    "Henry Munro",
    "Heritage Public",
    "Hopewell Avenue",
    "Hilson Avenue",
    "Huntley Centennial",
    "Larsen Elementary",
    "District School",
    "Public School",
    "School Board",
]


def _local_pii_scrub(text: str, source_type: str = "url") -> tuple[str, int]:
    """
    Regex-based PII removal.
    Returns (scrubbed_text, redaction_count).
    Uses stricter patterns for private sources (emails) than public ones (url/pdf).
    NOTE: Less accurate than AWS Comprehend. For local testing only.
    """
    patterns = _PII_PATTERNS_PRIVATE if source_type == "email" else _PII_PATTERNS_PUBLIC

    # For emails: protect known school/program/place names so they survive PII scrubbing.
    # Each occurrence is stored in order and replaced with a unique token.
    saved: list[str] = []
    if source_type == "email":
        for term in _EMAIL_SAFELIST:
            pat = re.compile(re.escape(term), re.IGNORECASE)

            def _repl(m: re.Match, _saved: list = saved) -> str:  # noqa: B023
                idx = len(_saved)
                _saved.append(m.group(0))  # preserve original casing
                return f"__SAFE{idx}__"

            text = pat.sub(_repl, text)

    count = 0
    for pattern, replacement in patterns:
        matches = pattern.findall(text)
        count += len(matches)
        text = pattern.sub(replacement, text)

    # Restore protected terms in the order they were saved
    for i, original in enumerate(saved):
        text = text.replace(f"__SAFE{i}__", original)

    return text, count


# ── URL fetching ─────────────────────────────────────────────────────────────

def _fetch_url_text(url: str) -> tuple[str, str]:
    """Fetch a web page and return (visible_text, page_title)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.5",
    }
    try:
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise UrlFetchError(
            f"URL returned {exc.response.status_code}: {url}"
        ) from exc
    except httpx.TimeoutException:
        raise UrlFetchError(f"URL timed out after 30 s: {url}")
    except httpx.RequestError as exc:
        raise UrlFetchError(f"Could not reach URL ({type(exc).__name__}): {url}") from exc
    soup = BeautifulSoup(resp.text, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or url
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    if len(text.split()) < 20:
        raise UrlFetchError(
            f"URL returned too little extractable text (possible JavaScript-only page or bot block): {url}"
        )
    return text, title


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_email_text(file_bytes: bytes) -> tuple[str, str]:
    """
    Parse a MIME .eml file and return (body_text, subject).
    Handles quoted-printable and base64 transfer encodings automatically
    via the ``email.policy.default`` policy (Python 3.6+).
    Strips all routing headers, MIME boundaries, and metadata.
    Only Subject, Date, and the message body are included in body_text.
    """
    import email as _email_lib
    from email import policy as _email_policy

    msg = _email_lib.message_from_bytes(file_bytes, policy=_email_policy.default)

    parts: list[str] = []

    subject = msg.get("Subject", "")
    if subject:
        parts.append(f"Subject: {subject}")

    date_val = msg.get("Date", "")
    if date_val:
        parts.append(f"Date: {date_val}")

    body = ""

    def _get_text_from_part(part) -> str:  # type: ignore[no-untyped-def]
        try:
            return part.get_content() or ""
        except Exception:
            # Fallback: decode payload manually
            raw = part.get_payload(decode=True)
            if not raw:
                return ""
            charset = part.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")

    if msg.is_multipart():
        # Prefer text/plain; fall back to text/html
        html_fallback = ""
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            if ct == "text/plain":
                candidate = _get_text_from_part(part).strip()
                if candidate:
                    body = candidate
                    break
            elif ct == "text/html" and not html_fallback:
                html_fallback = BeautifulSoup(
                    _get_text_from_part(part), "html.parser"
                ).get_text(separator=" ", strip=True)
        if not body and html_fallback:
            body = html_fallback
    else:
        ct = msg.get_content_type()
        if ct == "text/plain":
            body = _get_text_from_part(msg).strip()
        elif ct == "text/html":
            body = BeautifulSoup(
                _get_text_from_part(msg), "html.parser"
            ).get_text(separator=" ", strip=True)

    if body:
        parts.append(body)

    result = "\n\n".join(parts).strip()
    if not result:
        # Last resort: raw decode
        return file_bytes.decode("utf-8", errors="replace"), subject
    return result, subject


def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from uploaded bytes (discards email subject metadata)."""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text
            import io
            return extract_text(io.BytesIO(file_bytes))
        except ImportError:
            logger.warning("pdfminer_not_installed_falling_back_to_decode")
            return file_bytes.decode("latin-1", errors="replace")
    if name_lower.endswith(".eml"):
        body, _subject = _extract_email_text(file_bytes)
        return body
    # Plain text
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
    file_bytes: bytes | None = None,
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
    page_title: str | None = None
    if source_type == "url" and source_url:
        logger.info("local_etl_fetching_url", document_id=document_id, url=source_url)
        text, page_title = _fetch_url_text(source_url)
    else:
        raw_bytes = file_bytes if file_bytes is not None else read_file(s3_key)
        filename = Path(s3_key).name
        if filename.lower().endswith(".eml"):
            # Use the email Subject as the human-readable title
            text, email_subject = _extract_email_text(raw_bytes)
            page_title = email_subject.strip() or filename
        else:
            text = _extract_text(raw_bytes, filename)
            page_title = filename
    logger.info("local_etl_extracted", document_id=document_id, chars=len(text))

    # 3. PII scrub (stricter for emails, lighter for public web/PDF content)
    clean_text, redaction_count = _local_pii_scrub(text, source_type=source_type)
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

        # 7. Update document record and source title
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
        if page_title:
            cur.execute(
                "UPDATE sources SET title = %s WHERE id = %s",
                (page_title, document_id),
            )

        # 8. Create/update evidence card with citation metadata
        citation_label = page_title or source_url or "CEEP Document"
        citation_url = source_url if source_type == "url" else None
        cur.execute(
            """
            INSERT INTO evidence_cards (document_id, excerpt, citation_label, citation_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (document_id) DO UPDATE
                SET excerpt        = EXCLUDED.excerpt,
                    citation_label = EXCLUDED.citation_label,
                    citation_url   = EXCLUDED.citation_url
            """,
            (document_id, snippet, citation_label, citation_url),
        )

    conn.commit()
    logger.info("local_etl_done", document_id=document_id, chunks=len(chunks), words=word_count)
