"""
AWS Glue Job: chunker_embedder.py
Step 2 of the CEEP ETL pipeline.

Reads the clean (PII-redacted) text from public-docs S3 bucket,
splits it into overlapping chunks (~400 tokens each),
generates vector embeddings using AWS Bedrock Titan Embeddings v2,
and loads the chunks + embeddings into the RDS PostgreSQL chunks table.

Also creates an evidence card for each document (a human-readable excerpt).

Arguments:
  --PUBLIC_BUCKET           S3 bucket with clean text files
  --DB_SECRET_ARN           Secrets Manager ARN for DB credentials
  --DB_HOST                 RDS endpoint
  --DB_NAME                 Database name
  --AWS_REGION              AWS region
  --BEDROCK_EMBED_MODEL_ID  e.g. amazon.titan-embed-text-v2:0
  --CHUNK_SIZE              Target tokens per chunk (default: 400)
  --CHUNK_OVERLAP           Overlap tokens between consecutive chunks (default: 50)
  --document_id             UUID of the document to process
"""

import json
import sys
import re
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from awsglue.utils import getResolvedOptions

# ── Parse job arguments ────────────────────────────────────────────────────────
args = getResolvedOptions(sys.argv, [
    "PUBLIC_BUCKET",
    "DB_SECRET_ARN",
    "DB_HOST",
    "DB_NAME",
    "AWS_REGION",
    "BEDROCK_EMBED_MODEL_ID",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "document_id",
])

PUBLIC_BUCKET = args["PUBLIC_BUCKET"]
DB_SECRET_ARN = args["DB_SECRET_ARN"]
DB_HOST = args["DB_HOST"]
DB_NAME = args["DB_NAME"]
REGION = args["AWS_REGION"]
EMBED_MODEL_ID = args["BEDROCK_EMBED_MODEL_ID"]
CHUNK_SIZE = int(args["CHUNK_SIZE"])
CHUNK_OVERLAP = int(args["CHUNK_OVERLAP"])
DOCUMENT_ID = args["document_id"]

# ── AWS clients ────────────────────────────────────────────────────────────────
s3 = boto3.client("s3", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


def get_db_conn():
    secret = json.loads(
        secrets.get_secret_value(SecretId=DB_SECRET_ARN)["SecretString"]
    )
    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=secret["username"],
        password=secret["password"],
        sslmode="require",
        cursor_factory=RealDictCursor,
    )


# ── Tokenizer (word-count approximation) ──────────────────────────────────────
# Real token counts need tiktoken, but Glue doesn't include it by default.
# We approximate: ~1.3 words per token (English average).

def word_count_to_tokens(words: int) -> int:
    return int(words / 1.3)

def tokens_to_words(tokens: int) -> int:
    return int(tokens * 1.3)


# ── Text chunking ──────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size_tokens: int, overlap_tokens: int) -> list[str]:
    """
    Split text into overlapping chunks.
    chunk_size_tokens and overlap_tokens are approximate (word-count based).
    """
    words = text.split()
    chunk_words = tokens_to_words(chunk_size_tokens)
    overlap_words = tokens_to_words(overlap_tokens)

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_words
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_words - overlap_words   # slide forward, keeping overlap
        if start >= len(words):
            break

    return chunks


# ── Embedding ──────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Call Bedrock Titan Embeddings v2 to get a 1536-dim vector."""
    body = json.dumps({"inputText": text[:8192]})
    response = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


# ── Source metadata lookup ─────────────────────────────────────────────────────

def get_source_metadata(conn, document_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.source_type, s.source_url, s.title, s.published_at,
                   d.clean_s3_key
            FROM documents d
            JOIN sources s ON s.id = d.source_id
            WHERE d.id = %s
            """,
            (document_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else {}


# ── Write chunks + embeddings to DB ───────────────────────────────────────────

def insert_chunks(conn, document_id: str, chunks_with_embeddings: list[tuple]) -> None:
    """
    Bulk-insert chunks and their pgvector embeddings.
    chunks_with_embeddings: [(chunk_index, chunk_text, token_count, embedding_list)]
    """
    sql = """
    INSERT INTO chunks (document_id, chunk_index, chunk_text, token_count, embedding)
    VALUES %s
    ON CONFLICT (document_id, chunk_index) DO UPDATE
        SET chunk_text  = EXCLUDED.chunk_text,
            token_count = EXCLUDED.token_count,
            embedding   = EXCLUDED.embedding
    """
    values = [
        (document_id, idx, text, token_count, f"[{','.join(str(x) for x in emb)}]")
        for idx, text, token_count, emb in chunks_with_embeddings
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()


def upsert_evidence_card(conn, document_id: str, excerpt: str, source_url: str | None, citation_label: str) -> None:
    """Create or update the evidence card for this document."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_cards (document_id, excerpt, citation_url, citation_label)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (document_id) DO UPDATE
                SET excerpt        = EXCLUDED.excerpt,
                    citation_url   = EXCLUDED.citation_url,
                    citation_label = EXCLUDED.citation_label
            """,
            (document_id, excerpt[:1000], source_url, citation_label),
        )
    conn.commit()


# ── Main ETL step ──────────────────────────────────────────────────────────────

def run():
    print(f"[chunker_embedder] Starting for document_id={DOCUMENT_ID}")

    conn = get_db_conn()
    meta = get_source_metadata(conn, DOCUMENT_ID)

    if not meta or not meta.get("clean_s3_key"):
        print(f"[chunker_embedder] No clean text found for {DOCUMENT_ID}; skipping")
        conn.close()
        return

    # 1. Read clean text from S3
    obj = s3.get_object(Bucket=PUBLIC_BUCKET, Key=meta["clean_s3_key"])
    text = obj["Body"].read().decode("utf-8")
    print(f"[chunker_embedder] Read {len(text)} chars of clean text")

    # 2. Chunk the text
    text_chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    print(f"[chunker_embedder] Split into {len(text_chunks)} chunks")

    # 3. Embed each chunk
    chunks_with_embeddings = []
    for i, chunk in enumerate(text_chunks):
        embedding = embed_text(chunk)
        token_count = word_count_to_tokens(len(chunk.split()))
        chunks_with_embeddings.append((i, chunk, token_count, embedding))
        if i % 10 == 0:
            print(f"[chunker_embedder] Embedded {i+1}/{len(text_chunks)} chunks")

    # 4. Insert into DB
    insert_chunks(conn, DOCUMENT_ID, chunks_with_embeddings)
    print(f"[chunker_embedder] Inserted {len(chunks_with_embeddings)} chunks into DB")

    # 5. Create evidence card
    excerpt = text[:500].strip()
    source_url = meta.get("source_url")
    published = meta.get("published_at")
    title = meta.get("title") or source_url or "Community document"
    citation_label = f"{title} ({published.year if published else 'n.d.'})"
    upsert_evidence_card(conn, DOCUMENT_ID, excerpt, source_url, citation_label)
    print(f"[chunker_embedder] Evidence card created for {DOCUMENT_ID}")

    conn.close()
    print(f"[chunker_embedder] Done. document_id={DOCUMENT_ID}")


run()
