"""
Local filesystem storage adapter.
Replaces S3 when USE_LOCAL_STORAGE=true (local development).

Files are stored under settings.local_storage_path:
  local_data/
    raw/        ← uploaded files (equivalent to S3 private/public buckets)
    clean/      ← PII-redacted text (equivalent to S3 public-docs/clean/)
"""

import os
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import logger


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_save_path(s3_key: str) -> Path:
    """Convert an S3-style key (raw/{id}/file.pdf) to a local path."""
    settings = get_settings()
    local_path = Path(settings.local_storage_path) / s3_key
    _ensure(local_path.parent)
    return local_path


def save_file(s3_key: str, content: bytes) -> None:
    """Write bytes to the local filesystem at the given S3-equivalent key."""
    path = local_save_path(s3_key)
    path.write_bytes(content)
    logger.info("local_storage_write", path=str(path), size=len(content))


def read_file(s3_key: str) -> bytes:
    """Read bytes from the local filesystem."""
    path = local_save_path(s3_key)
    if not path.exists():
        raise FileNotFoundError(f"Local file not found: {path}")
    return path.read_bytes()


def delete_file(s3_key: str) -> None:
    """Delete a local file (mirrors S3 delete_object)."""
    path = local_save_path(s3_key)
    if path.exists():
        path.unlink()
        logger.info("local_storage_delete", path=str(path))


def generate_local_upload_url(document_id: str, fastapi_base_url: str = "http://localhost:8001") -> str:
    """
    Return a URL that the frontend can PUT the file to.
    Points to the /documents/local-upload/{document_id} endpoint on the FastAPI server.
    (In production this would be an S3 pre-signed URL instead.)
    """
    return f"{fastapi_base_url}/documents/local-upload/{document_id}"
