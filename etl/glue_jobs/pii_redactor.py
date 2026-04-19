"""
AWS Glue Job: pii_redactor.py
Step 1 of the CEEP ETL pipeline.

Reads a raw document (PDF or email) from the private S3 bucket,
uses AWS Comprehend to detect PII entities, redacts them, and writes the
clean text to the public-docs S3 bucket.

Why Glue instead of Lambda?
- Glue supports PySpark for large document sets.
- Glue job bookmarking prevents re-processing already-ingested files.
- Glue has no 15-minute timeout (unlike Lambda).
- AWS Glue is purpose-built for ETL and data cataloguing.

Arguments (passed as Glue job parameters):
  --PRIVATE_BUCKET      S3 bucket with raw uploads
  --PUBLIC_BUCKET       S3 bucket for clean output
  --DB_SECRET_ARN       Secrets Manager ARN for DB credentials
  --DB_HOST             RDS endpoint
  --DB_NAME             Database name
  --AWS_REGION          AWS region
  --document_id         UUID of the document to process (set per-job invocation)
  --s3_key              S3 key of the raw file
  --source_type         'email' | 'pdf' | 'url'
  --consent_flag        'true' | 'false'
"""

import json
import sys
import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor
from awsglue.utils import getResolvedOptions

# ── Parse job arguments ────────────────────────────────────────────────────────
args = getResolvedOptions(sys.argv, [
    "PRIVATE_BUCKET",
    "PUBLIC_BUCKET",
    "DB_SECRET_ARN",
    "DB_HOST",
    "DB_NAME",
    "AWS_REGION",
    "document_id",
    "s3_key",
    "source_type",
    "consent_flag",
])

PRIVATE_BUCKET = args["PRIVATE_BUCKET"]
PUBLIC_BUCKET = args["PUBLIC_BUCKET"]
DB_SECRET_ARN = args["DB_SECRET_ARN"]
DB_HOST = args["DB_HOST"]
DB_NAME = args["DB_NAME"]
REGION = args["AWS_REGION"]
DOCUMENT_ID = args["document_id"]
S3_KEY = args["s3_key"]
SOURCE_TYPE = args["source_type"]
CONSENT_FLAG = args["consent_flag"].lower() == "true"

# ── AWS Clients ────────────────────────────────────────────────────────────────
s3 = boto3.client("s3", region_name=REGION)
comprehend = boto3.client("comprehend", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# ── PII entity types to redact ─────────────────────────────────────────────────
REDACT_ENTITY_TYPES = {
    "NAME", "EMAIL", "PHONE", "ADDRESS",
    "SSN", "CREDIT_DEBIT_NUMBER", "BANK_ACCOUNT_NUMBER",
}
MIN_CONFIDENCE = 0.90   # only redact high-confidence detections

# ── DB connection ──────────────────────────────────────────────────────────────

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


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_s3(bucket: str, key: str) -> str:
    """
    Download the raw file and extract plain text.
    Supports: .txt, .eml (email), .pdf (basic; for production use Textract).
    """
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw_bytes = obj["Body"].read()

    if key.endswith(".pdf"):
        # For MVP: use pdfminer.six if available; otherwise decode as latin-1
        try:
            from pdfminer.high_level import extract_text_to_fp
            from pdfminer.layout import LAParams
            import io
            output = io.StringIO()
            extract_text_to_fp(io.BytesIO(raw_bytes), output, laparams=LAParams())
            return output.getvalue()
        except ImportError:
            return raw_bytes.decode("latin-1", errors="replace")

    # Email / plain text
    return raw_bytes.decode("utf-8", errors="replace")


# ── PII Redaction ──────────────────────────────────────────────────────────────

def redact_pii(text: str, document_id: str, conn) -> tuple[str, list[dict]]:
    """
    Detect PII entities using AWS Comprehend and replace them with
    [REDACTED-<TYPE>] markers.

    Returns (redacted_text, list_of_redaction_audit_records).
    """
    # Comprehend has a 5000-byte limit per call; split large documents
    MAX_BYTES = 4800
    chunks = []
    current = []
    current_bytes = 0
    for word in text.split():
        word_bytes = len(word.encode("utf-8")) + 1
        if current_bytes + word_bytes > MAX_BYTES:
            chunks.append(" ".join(current))
            current = [word]
            current_bytes = word_bytes
        else:
            current.append(word)
            current_bytes += word_bytes
    if current:
        chunks.append(" ".join(current))

    redacted_parts = []
    audit_records = []

    for chunk in chunks:
        response = comprehend.detect_pii_entities(Text=chunk, LanguageCode="en")
        entities = response.get("Entities", [])

        # Sort by begin offset descending so we can replace without shifting indices
        entities_to_redact = [
            e for e in entities
            if e["Type"] in REDACT_ENTITY_TYPES and e["Score"] >= MIN_CONFIDENCE
        ]
        entities_to_redact.sort(key=lambda e: e["BeginOffset"], reverse=True)

        redacted = chunk
        for entity in entities_to_redact:
            label = f"[REDACTED-{entity['Type']}]"
            redacted = redacted[: entity["BeginOffset"]] + label + redacted[entity["EndOffset"]:]
            audit_records.append({
                "document_id": document_id,
                "entity_type": entity["Type"],
                "score": entity["Score"],
                "char_start": entity["BeginOffset"],
                "char_end": entity["EndOffset"],
            })

        redacted_parts.append(redacted)

    return " ".join(redacted_parts), audit_records


# ── Write audit records to DB ──────────────────────────────────────────────────

def write_audit_records(conn, records: list[dict]) -> None:
    if not records:
        return
    sql = """
    INSERT INTO pii_audit (document_id, entity_type, score, char_start, char_end)
    VALUES (%s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        for rec in records:
            cur.execute(sql, (
                rec["document_id"],
                rec["entity_type"],
                rec["score"],
                rec["char_start"],
                rec["char_end"],
            ))
    conn.commit()


# ── Update document record in DB ──────────────────────────────────────────────

def update_document(conn, document_id: str, clean_s3_key: str, snippet: str, word_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET clean_s3_key = %s,
                text_snippet  = %s,
                word_count    = %s,
                ingested_at   = now()
            WHERE id = %s
            """,
            (clean_s3_key, snippet[:500], word_count, document_id),
        )
    conn.commit()


# ── Main ETL step ──────────────────────────────────────────────────────────────

def run():
    print(f"[pii_redactor] Starting for document_id={DOCUMENT_ID}, source_type={SOURCE_TYPE}")

    # Emails without consent are silently skipped (never processed)
    if SOURCE_TYPE == "email" and not CONSENT_FLAG:
        print(f"[pii_redactor] SKIPPING {DOCUMENT_ID}: email with no consent")
        return

    # 1. Extract text from S3
    bucket = PRIVATE_BUCKET if SOURCE_TYPE == "email" else PUBLIC_BUCKET
    text = extract_text_from_s3(bucket, S3_KEY)
    print(f"[pii_redactor] Extracted {len(text)} chars from {bucket}/{S3_KEY}")

    # 2. Redact PII (always, even for public docs — in case they contain personal info)
    conn = get_db_conn()
    redacted_text, audit_records = redact_pii(text, DOCUMENT_ID, conn)
    print(f"[pii_redactor] Redacted {len(audit_records)} PII entities")

    # 3. Write clean text to public-docs bucket
    clean_key = f"clean/{DOCUMENT_ID}/text.txt"
    s3.put_object(
        Bucket=PUBLIC_BUCKET,
        Key=clean_key,
        Body=redacted_text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    print(f"[pii_redactor] Wrote clean text to {PUBLIC_BUCKET}/{clean_key}")

    # 4. Write audit records
    write_audit_records(conn, audit_records)

    # 5. Update document record
    word_count = len(redacted_text.split())
    snippet = redacted_text[:500]
    update_document(conn, DOCUMENT_ID, clean_key, snippet, word_count)

    conn.close()
    print(f"[pii_redactor] Done. document_id={DOCUMENT_ID}, words={word_count}")


run()
