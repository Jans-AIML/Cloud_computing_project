"""
Database connection management.

- Uses psycopg2 with pgvector registered.
- Reads DB password from AWS Secrets Manager (once per Lambda cold-start).
- Exposes get_db() as a FastAPI dependency that yields a connection.
"""

import json
import os
from contextlib import contextmanager
from typing import Generator

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.config import get_settings
from app.core.logging import logger

_db_password: str | None = None


def _fetch_db_password() -> str:
    """Fetch DB password from Secrets Manager (cached after first call)."""
    global _db_password
    if _db_password:
        return _db_password

    settings = get_settings()
    if settings.db_secret_arn:
        client = boto3.client("secretsmanager", region_name=settings.aws_region_name)
        secret = client.get_secret_value(SecretId=settings.db_secret_arn)
        creds = json.loads(secret["SecretString"])
        _db_password = creds["password"]
    else:
        # Local dev: fall back to env var
        _db_password = settings.db_password

    return _db_password


def get_connection() -> psycopg2.extensions.connection:
    """Return a new psycopg2 connection with pgvector registered."""
    settings = get_settings()
    password = _fetch_db_password()

    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=password,
        sslmode="require" if settings.environment == "production" else "prefer",
        cursor_factory=RealDictCursor,
    )

    # Register pgvector types so embeddings come back as Python lists
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()

    return conn


@contextmanager
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context manager / FastAPI dependency yielding a DB connection."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
