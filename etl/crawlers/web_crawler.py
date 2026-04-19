"""
Web crawler / URL bookmarker — runs as a scheduled Lambda function.
Fetches public URLs and submits them to the CEEP ingestion pipeline.

This is separate from the Glue ETL; it is a lightweight Lambda that
periodically crawls bookmarked URLs and pushes new content to S3 → SQS → Glue.

Scheduled via EventBridge (e.g., every 6 hours).
"""

import hashlib
import json
import os
from datetime import datetime
from urllib.parse import urlparse

import boto3
import httpx
from bs4 import BeautifulSoup

REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")
PUBLIC_BUCKET = os.environ["PUBLIC_BUCKET"]
INGEST_QUEUE_URL = os.environ["INGEST_QUEUE_URL"]

s3 = boto3.client("s3", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

# ── Seeded URLs (corpus bootstrap) ────────────────────────────────────────────
SEED_URLS = [
    # Save Lady Evelyn community sites
    "https://sites.google.com/view/saveladyevelynschool/home",
    "https://sites.google.com/view/saveladyevelynschool/taking-action",
    "https://sites.google.com/view/saveladyevelynschool/parents-proposal",
    # News
    "https://www.cbc.ca/news/canada/ottawa/ocdsb-delays-closing-kindergarten-registration-alternative-schools-1.7147389",
    # Mainstreeter
    "https://www.themainstreeter.com/saving-lady-evelyn-school/",
    # Kitchissippi Ward
    "https://kitchissippi.ca/",
]

HEADERS = {
    "User-Agent": "CEEP-Community-Evidence-Bot/1.0 (+https://github.com/ceep-project)",
}


def url_to_s3_key(url: str) -> str:
    """Deterministic S3 key from a URL (hash-based, collision-resistant)."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    domain = urlparse(url).netloc.replace(".", "-")
    return f"raw/crawled/{domain}/{url_hash}.txt"


def fetch_page_text(url: str) -> str | None:
    """Fetch a URL and extract main body text (no PII — public pages only)."""
    try:
        response = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"[crawler] Failed to fetch {url}: {exc}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove nav, footer, scripts, styles
    for tag in soup(["nav", "footer", "script", "style", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse blank lines
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def already_crawled(s3_key: str) -> bool:
    """Check if this URL has already been ingested (S3 object exists)."""
    try:
        s3.head_object(Bucket=PUBLIC_BUCKET, Key=s3_key)
        return True
    except s3.exceptions.ClientError:
        return False


def crawl_and_ingest(url: str) -> None:
    """Fetch a URL, store raw text in S3, enqueue for Glue ETL."""
    s3_key = url_to_s3_key(url)

    if already_crawled(s3_key):
        print(f"[crawler] Already ingested: {url}")
        return

    text = fetch_page_text(url)
    if not text:
        return

    # Write to S3
    import uuid
    document_id = str(uuid.uuid4())
    s3.put_object(
        Bucket=PUBLIC_BUCKET,
        Key=s3_key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
        Metadata={
            "source_url": url,
            "crawled_at": datetime.utcnow().isoformat(),
            "document_id": document_id,
        },
    )
    print(f"[crawler] Stored {len(text)} chars → s3://{PUBLIC_BUCKET}/{s3_key}")

    # Enqueue ETL job
    message = {
        "document_id": document_id,
        "s3_key": s3_key,
        "source_type": "url",
        "source_url": url,
        "consent_flag": True,   # public pages don't require consent
    }
    sqs.send_message(
        QueueUrl=INGEST_QUEUE_URL,
        MessageBody=json.dumps(message),
    )
    print(f"[crawler] Enqueued ETL job for document_id={document_id}")


def lambda_handler(event, context):
    """Lambda entry point — called by EventBridge on a schedule."""
    urls = event.get("urls", SEED_URLS)
    for url in urls:
        crawl_and_ingest(url)
    return {"status": "ok", "crawled": len(urls)}
