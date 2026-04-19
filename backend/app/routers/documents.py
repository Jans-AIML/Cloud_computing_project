"""
/documents — upload and manage evidence documents.

All routes go through API Gateway → this Lambda handler.
Files never go directly from the browser to S3; instead Lambda generates
a pre-signed PUT URL and returns it to the client.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.database import get_db
from app.core.logging import logger
from app.models.schemas import DocumentSummary, UploadRequest, UploadResponse
from app.services.storage import (
    delete_document_from_s3,
    enqueue_etl_job,
    generate_upload_url,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def request_upload(payload: UploadRequest) -> UploadResponse:
    """
    Step 1 of the upload flow:
    - Validates consent for email submissions.
    - Creates a source record in the DB.
    - Returns a pre-signed S3 PUT URL (valid 15 min).
    Client then PUTs the file directly to S3, then calls POST /documents/confirm.
    """
    # Enforce consent gate for emails
    try:
        payload.validate_email_consent()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    document_id = str(uuid.uuid4())
    s3_key = f"raw/{document_id}/{payload.filename}"

    upload_url = generate_upload_url(
        document_id=document_id,
        filename=payload.filename,
        content_type=payload.content_type,
        source_type=payload.source_type,
    )

    # Persist source record so we can track it (even before ETL completes)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sources (id, source_type, source_url, consent_flag)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    document_id,
                    payload.source_type,
                    payload.source_url,
                    payload.consent_given,
                ),
            )
            cur.execute(
                """
                INSERT INTO documents (id, source_id, raw_s3_key)
                VALUES (%s, %s, %s)
                """,
                (document_id, document_id, s3_key),
            )

    # Enqueue ETL job (Glue picks this up in production)
    enqueue_etl_job(
        document_id=document_id,
        s3_key=s3_key,
        source_type=payload.source_type,
        consent_flag=payload.consent_given,
    )

    # In local mode, run ETL in-process immediately for URL sources
    # (PDF sources go through PUT /documents/local-upload/{id} instead)
    from app.core.config import get_settings as _get_settings
    _settings = _get_settings()
    if _settings.use_local_storage and payload.source_type == "url" and payload.source_url:
        from app.services.local_etl import run_local_etl
        with get_db() as conn:
            run_local_etl(
                document_id=document_id,
                s3_key=s3_key,
                source_type=payload.source_type,
                consent_flag=payload.consent_given,
                conn=conn,
                source_url=str(payload.source_url),
            )

    logger.info("upload_requested", document_id=document_id, source_type=payload.source_type)
    return UploadResponse(
        document_id=uuid.UUID(document_id),
        upload_url=upload_url,
        expires_in_seconds=900,
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(limit: int = 20, offset: int = 0) -> list[DocumentSummary]:
    """Return paginated list of ingested (non-deleted) evidence documents."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id,
                    s.source_type,
                    s.title,
                    s.source_url,
                    d.text_snippet,
                    d.word_count,
                    d.ingested_at,
                    COUNT(ec.id) AS evidence_card_count
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                LEFT JOIN evidence_cards ec ON ec.document_id = d.id
                WHERE d.deleted_at IS NULL
                GROUP BY d.id, s.source_type, s.title, s.source_url,
                         d.text_snippet, d.word_count, d.ingested_at
                ORDER BY d.ingested_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

    return [DocumentSummary(**dict(row)) for row in rows]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    """
    Right-to-deletion: soft-delete the document and hard-delete S3 object.
    Embeddings are removed from pgvector via CASCADE on the chunks table.
    """
    from app.core.config import get_settings

    settings = get_settings()

    with get_db() as conn:
        with conn.cursor() as cur:
            # Fetch s3 key and source type before deletion
            cur.execute(
                "SELECT d.raw_s3_key, s.source_type FROM documents d "
                "JOIN sources s ON s.id = d.source_id "
                "WHERE d.id = %s AND d.deleted_at IS NULL",
                (document_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found or already deleted",
                )

            raw_s3_key = row["raw_s3_key"]
            source_type = row["source_type"]

            # Soft-delete the document row (cascades to chunks → removes embeddings)
            cur.execute(
                "UPDATE documents SET deleted_at = now() WHERE id = %s",
                (document_id,),
            )

    # Hard-delete the raw file from S3
    if raw_s3_key:
        bucket = (
            settings.private_bucket if source_type == "email" else settings.public_bucket
        )
        delete_document_from_s3(bucket=bucket, s3_key=raw_s3_key)

    logger.info("document_deleted", document_id=document_id)


# ── Local-upload endpoint (development only) ──────────────────────────────────

@router.put("/local-upload/{document_id}", status_code=status.HTTP_200_OK)
async def local_upload_receive(document_id: str, request: Request) -> dict:
    """
    Receives the raw file body via PUT (mirrors the S3 pre-signed URL flow).
    Only active when USE_LOCAL_STORAGE=true (local development).

    Flow:
      1. Frontend calls POST /documents/upload → gets URL pointing here
      2. Frontend PUTs file bytes to this endpoint
      3. This endpoint saves the file and runs the ETL pipeline in-process
    """
    from app.core.config import get_settings
    from app.services.local_storage import save_file

    settings = get_settings()
    if not settings.use_local_storage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local upload endpoint is only available in local development mode.",
        )

    # Read the raw file bytes from the request body
    file_bytes = await request.body()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file body")

    # Look up the document record to get the s3_key and source metadata
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.raw_s3_key, s.source_type, s.consent_flag
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                WHERE d.id = %s
                """,
                (document_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    s3_key = row["raw_s3_key"]
    source_type = row["source_type"]
    consent_flag = row["consent_flag"]

    # Save to local filesystem
    save_file(s3_key, file_bytes)
    logger.info("local_upload_received", document_id=document_id, bytes=len(file_bytes))

    # Run ETL in-process (no Glue, no SQS — everything happens synchronously here)
    with get_db() as conn:
        from app.services.local_etl import run_local_etl
        run_local_etl(
            document_id=document_id,
            s3_key=s3_key,
            source_type=source_type,
            consent_flag=consent_flag,
            conn=conn,
        )

    return {"status": "processed", "document_id": document_id}
