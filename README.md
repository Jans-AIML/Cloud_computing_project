# CEEP — Community Evidence & Engagement Platform

**2026W-AML-3503-OTT01 Cloud Computing for Big Data — Final Project**  
Group 1: Jans Alzate-Morales (c0936855) · Yash Suthar (c0957228) · Nafis Ahmed (c0959671)

---

## What is CEEP?

A cloud-native, LLM-assisted web application to ingest, analyse, and mobilise community
evidence for keeping Lady Evelyn and other Ottawa community schools open.  
It ingests PDFs, emails (with PII redaction), and public web pages; turns them into citable
*evidence cards*; and drives a RAG-backed Q&A and brief-generation interface.

---

## Revised Architecture (incorporating course feedback)

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1 — Frontend                                          │
│  CloudFront CDN  ←→  React + Vite SPA                      │
│  (S3 is the *deployment target* for static assets,          │
│   not a frontend component — it belongs to Tier 3)         │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS  (all traffic)
┌──────────────────────────▼──────────────────────────────────┐
│  Tier 2 — Backend  (API Gateway is the SOLE entry point)    │
│                                                             │
│  API Gateway (HTTP API)                                     │
│       ├── /documents/*   → Lambda (FastAPI/Mangum)          │
│       ├── /search/*      → Lambda (FastAPI/Mangum)          │
│       ├── /rag/*         → Lambda (FastAPI/Mangum)          │
│       └── /briefs/*      → Lambda (FastAPI/Mangum)          │
│                                                             │
│  Upload flow:                                               │
│   API GW → Lambda → pre-signed S3 URL (client uploads      │
│   directly) → S3 event → SQS → AWS Glue Job (ETL)         │
│                                                             │
│  ETL Pipeline (AWS Glue):                                   │
│   Extract → PII Redact (Comprehend) → Parse/OCR            │
│   → Chunk → Embed (Bedrock Titan) → Load (RDS pgvector)    │
│                                                             │
│  LLM:  AWS Bedrock (Claude 3 Haiku / Sonnet)               │
│        — same AWS account, no external vendor              │
└──────────────────────────┬──────────────────────────────────┘
                           │ SQL + vector queries
┌──────────────────────────▼──────────────────────────────────┐
│  Tier 3 — Data / Storage                                    │
│  S3 (raw docs, parsed JSON, static frontend build)         │
│  RDS PostgreSQL + pgvector (embeddings, evidence cards)    │
│  CloudWatch (logs, metrics, alarms)                        │
│  Secrets Manager (DB credentials, API keys)                │
│  KMS (encryption keys for S3 SSE-KMS, RDS)                │
└─────────────────────────────────────────────────────────────┘
```

### Why AWS Bedrock instead of GPT or Groq?
- Keeps all data **inside AWS** — no PII leaves the account boundary.
- Bedrock supports the same RAG/streaming/citation patterns Claude requires.
- Single billing account & IAM policy surface (easier governance).
- Claude 3 Haiku is comparable in quality to GPT-4o-mini at the same price range.
- No feature in the proposal requires something only GPT supports.

### Why AWS Glue for ETL?
- Managed Spark environment handles large document sets without Lambda's 15-min timeout.
- Glue Crawlers auto-discover new S3 objects and trigger processing jobs.
- Built-in retry, logging, and job bookmarking - exactly what a deterministic ingestion pipeline needs.
- Glue Data Catalog keeps schema/lineage metadata for audit purposes.

---

## Core MVP Features (non-stretch — delivered for final exam)

| Feature | Description |
|---|---|
| Corpus Ingestion | Drag-and-drop PDF/email upload; URL bookmarking; S3 → Glue ETL |
| PII Redaction | AWS Comprehend strips names/emails/phones before evidence cards are created |
| RAG Q&A | Hybrid dense (pgvector) + keyword search → Claude 3 answer with inline citations |
| Brief Generator | Templates for OCDSB submissions, councillor letters, op-eds |
| Governance | Per-user rate limits, token budget caps, streaming responses, audit trail |

## Stretch Features (if time allows)

| Feature | Description |
|---|---|
| Petition & Sentiment Pulse | Track petition milestones and local media sentiment |
| Planning Context Panel | Curate nearby development signals (340 Parkdale, ward updates) |
| CI/CD | GitHub Actions → AWS CDK deploy |

---

## Sensitive Data Policy

### Community Emails
- Raw emails land in `s3://ceep-private-uploads/` — **private bucket, SSE-KMS encrypted**.
- **Consent gate**: a contributor must check an explicit opt-in before any email content is processed.
- AWS Comprehend `DetectPiiEntities` runs as the **first step** in the Glue job; any text segment
  tagged as PERSON, EMAIL, PHONE, ADDRESS is replaced with `[REDACTED-<type>]`.
- Only the **redacted excerpt** becomes an evidence card; the raw file is retained for audit
  but never queried or displayed.
- Email authors may request deletion at any time (DELETE /documents/{id} triggers S3 + DB purge).

### Public & Semi-Public Documents
- News articles, OCDSB pages, community sites: indexed as **summaries + canonical URL**, not full copies.
- Copyright compliance: we store ≤ 500-word excerpts per source, always with attribution.
- OCDSB official PDFs: treated as public-domain government documents; full text indexed.

### Documentation Shared with the Community
Because CEEP is itself a public-good tool, we will publish:
1. **`docs/community_guide.md`** — plain-language explanation of what data is stored,
   how to submit evidence, how to request deletion, and how evidence cards are generated.
2. **`docs/sensitive_data_guide.md`** — technical PII policy for contributors and maintainers.
3. A CEEP-hosted **Privacy Notice** page reachable from the UI footer.

---

## Repository Structure

```
.
├── infrastructure/          # AWS CDK (Python) — all cloud resources
│   ├── app.py
│   ├── requirements.txt
│   └── stacks/
│       ├── storage_stack.py   # S3 buckets, RDS, KMS
│       ├── compute_stack.py   # Lambda, API Gateway
│       ├── etl_stack.py       # Glue jobs, SQS, Comprehend permissions
│       └── frontend_stack.py  # CloudFront distribution
├── backend/                 # FastAPI application (runs inside Lambda via Mangum)
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/           # documents, search, rag, briefs
│   │   ├── services/          # bedrock_client, embeddings, rag, pii, storage
│   │   ├── models/            # Pydantic schemas
│   │   └── core/              # config, security, rate_limit
│   ├── requirements.txt
│   └── Dockerfile             # local dev / ECS fallback
├── etl/
│   ├── glue_jobs/             # PySpark Glue scripts
│   │   ├── ingest_documents.py
│   │   ├── pii_redactor.py
│   │   ├── chunker_embedder.py
│   │   └── index_loader.py
│   └── crawlers/
│       └── web_crawler.py     # Scheduled Lambda for URL bookmarks
├── frontend/                # React + Vite SPA
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/          # API client (all calls via API Gateway)
│   │   └── hooks/
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── architecture.md
│   ├── sensitive_data_guide.md
│   └── community_guide.md
├── scripts/
│   ├── deploy.sh
│   └── seed_corpus.py
└── tests/
```

---

## Quick-start (local development)

```bash
# 1. Clone & enter repo
git clone <repo> && cd Cloud_computing_project

# 2. Python environment (backend + infra)
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r infrastructure/requirements.txt

# 3. Local backend (no AWS needed for basic tests)
cd backend && uvicorn app.main:app --reload

# 4. Frontend
cd frontend && npm install && npm run dev

# 5. Deploy to AWS (needs configured AWS CLI + CDK bootstrapped)
cd infrastructure && cdk deploy --all
```

---

## Technology Stack Summary

| Layer | Technology | Reason |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript | Fast SPA, small bundle |
| CDN | CloudFront | Free 1 TB/mo, HTTPS, edge caching |
| API | API Gateway HTTP API | Sole entry point; 1M calls/mo free |
| Compute | AWS Lambda + FastAPI + Mangum | Serverless, 1M invocations/mo free |
| ETL | AWS Glue (PySpark) | Managed Spark, Glue Crawlers, job bookmarking |
| PII | AWS Comprehend | Managed NLP, no model to maintain |
| LLM | AWS Bedrock (Claude 3) | In-account, no data leaves AWS |
| Embeddings | Bedrock Titan Embeddings v2 | Same account, 1536-dim vectors |
| Vector DB | RDS PostgreSQL + pgvector | Free tier 750 hrs, zero extra cost |
| Object Store | S3 | Raw docs + parsed JSON + frontend build |
| Secrets | Secrets Manager + KMS | Encrypted credentials |
| Observability | CloudWatch Logs + Metrics | Free 5 GB logs, 10 metrics |
| IaC | AWS CDK (Python) | Type-safe, same language as backend |
