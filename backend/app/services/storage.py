"""
Storage service — S3 pre-signed URL generation and SQS job dispatch.

All uploads go through API Gateway → Lambda → pre-signed S3 URL.
The client PUTs directly to S3 using the pre-signed URL.
After the upload, Lambda enqueues an SQS message to trigger Glue ETL.
"""

import json
import uuid

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import logger


def _s3_client():
    return boto3.client("s3", region_name=get_settings().aws_region_name)


def _sqs_client():
    return boto3.client("sqs", region_name=get_settings().aws_region_name)


def generate_upload_url(
    document_id: str,
    filename: str,
    content_type: str,
    source_type: str,
    expires_in: int = 900,
) -> str:
    """
    Generate an upload URL.
    LOCAL:      Returns a URL pointing to FastAPI's /documents/local-upload/{id}
    PRODUCTION: Returns a pre-signed S3 PUT URL (expires in `expires_in` seconds).
    """
    settings = get_settings()

    if settings.use_local_storage:
        from app.services.local_storage import generate_local_upload_url
        return generate_local_upload_url(document_id)

    # ── Production: S3 pre-signed URL ─────────────────────────────────────────
    bucket = (
        settings.private_bucket
        if source_type == "email"
        else settings.public_bucket
    )

    # Deterministic S3 key: raw/{document_id}/{filename}
    s3_key = f"raw/{document_id}/{filename}"

    client = _s3_client()
    try:
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": s3_key,
                "ContentType": content_type,
                # Server-side encryption parameters
                "ServerSideEncryption": "aws:kms" if source_type == "email" else "AES256",
            },
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        logger.error("presigned_url_error", error=str(exc), document_id=document_id)
        raise

    logger.info(
        "generated_upload_url",
        document_id=document_id,
        bucket=bucket,
        s3_key=s3_key,
        source_type=source_type,
    )
    return url


def enqueue_etl_job(document_id: str, s3_key: str, source_type: str, consent_flag: bool) -> None:
    """
    Send an SQS message to trigger the Glue ETL workflow for this document.
    The Glue job trigger polls this queue.
    """
    settings = get_settings()
    if not settings.ingest_queue_url:
        logger.warning("ingest_queue_url_not_set_skipping_sqs")
        return

    message = {
        "document_id": document_id,
        "s3_key": s3_key,
        "source_type": source_type,
        "consent_flag": consent_flag,
    }

    client = _sqs_client()
    client.send_message(
        QueueUrl=settings.ingest_queue_url,
        MessageBody=json.dumps(message),
        MessageGroupId="ceep-ingest",  # for FIFO queue; ignored for standard
    )
    logger.info("etl_job_enqueued", document_id=document_id)


def delete_document_from_s3(bucket: str, s3_key: str) -> None:
    """Hard-delete a document from S3 (called on right-to-deletion requests)."""
    client = _s3_client()
    try:
        client.delete_object(Bucket=bucket, Key=s3_key)
        logger.info("s3_object_deleted", bucket=bucket, key=s3_key)
    except ClientError as exc:
        logger.error("s3_delete_error", bucket=bucket, key=s3_key, error=str(exc))
        raise
