# Developer Guide — CEEP

> **For Nafis and Yash** — everything you need to test the live system, run it locally,
> make changes, and deploy them.

---

## 1. Live System (no setup needed)

| Endpoint | URL |
|---|---|
| Web UI | <https://d3voaboc02j1x3.cloudfront.net> |
| API (Swagger docs) | <https://rrzjd3hm7l.execute-api.us-east-1.amazonaws.com/docs> |

### Quick API smoke-tests

```bash
# List all documents in the corpus
curl -s "https://rrzjd3hm7l.execute-api.us-east-1.amazonaws.com/documents" | python3 -m json.tool | head -40

# Hybrid search
curl -s "https://rrzjd3hm7l.execute-api.us-east-1.amazonaws.com/search?q=JK+registration"

# RAG Q&A
curl -s -X POST "https://rrzjd3hm7l.execute-api.us-east-1.amazonaws.com/rag" \
  -H "Content-Type: application/json" \
  -d '{"question": "What did the OCDSB decide on March 9 2026?", "top_k": 6}'

# Generate a brief (op-ed template)
curl -s -X POST "https://rrzjd3hm7l.execute-api.us-east-1.amazonaws.com/briefs/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "op_ed",
    "goal": "urge OCDSB to restore JK enrolment at Lady Evelyn",
    "audience": "Ottawa general public",
    "tone": "community",
    "extra_context": ""
  }'
```

---

## 2. Local Development

### Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10+ | Backend |
| Node.js | 18+ | Frontend |
| Docker + Docker Compose | any recent | Local PostgreSQL |
| Groq API key | free | Chat LLM (get at console.groq.com) |

### Setup

```bash
# Clone
git clone https://github.com/Jans-AIML/Cloud_computing_project.git
cd Cloud_computing_project

# Python virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt

# Node modules
cd frontend && npm install && cd ..

# Local PostgreSQL with pgvector
docker compose up -d

# Configure environment
cp .env.example backend/.env
# Open backend/.env and set:
#   GROQ_API_KEY=gsk_your_key_here   ← required
# Everything else can stay as the defaults for local dev.

# Initialise DB schema
cd backend && python -m app.core.schema && cd ..
```

### Running locally

```bash
# Terminal 1 — backend (http://localhost:8001, Swagger at /docs)
make dev

# Terminal 2 — frontend (http://localhost:5173)
make frontend
```

> **Note:** `LLM_PROVIDER=groq` (set in `.env`) downloads the fastembed model
> (`BAAI/bge-small-en-v1.5`) on first run to `./local_data/fastembed_cache`.
> This is ~130 MB and takes ~30 s on first startup only.

### Other Makefile commands

```bash
make stop        # stop Docker containers
make clean       # ⚠ deletes DB volume and all local_data
make install     # reinstall backend pip + frontend npm packages
```

---

## 3. Project Structure

```
backend/app/
├── main.py                 # FastAPI app + Mangum Lambda handler
├── routers/
│   ├── documents.py        # POST /upload, POST /{id}/process, GET, DELETE
│   ├── search.py           # GET /search?q=...
│   ├── rag.py              # POST /rag
│   └── briefs.py           # GET /briefs/templates, POST /briefs/generate
├── services/
│   ├── local_etl.py        # ★ Core ETL: extract → PII scrub → chunk → embed → load
│   ├── rag.py              # hybrid_search() SQL + pgvector
│   ├── llm_factory.py      # provider-agnostic invoke_llm / embed_text
│   ├── groq_client.py      # Groq API (chat + streaming)
│   ├── fastembed_client.py # fastembed ONNX embeddings (local, no API)
│   ├── storage.py          # S3 presigned URLs, download, delete
│   └── bedrock_client.py   # legacy Bedrock client (not active)
├── models/
│   └── schemas.py          # Pydantic types: SearchResult, Citation, BriefResponse, …
└── core/
    ├── config.py           # Settings (reads .env / Lambda env vars)
    ├── database.py         # psycopg2 connection pool + get_db() context manager
    └── logging.py          # structlog JSON logger

frontend/src/
├── pages/
│   ├── SearchPage.tsx      # Hybrid search with source-type badges
│   ├── AskPage.tsx         # RAG Q&A with citations
│   ├── WritePage.tsx       # Brief/letter generator
│   └── UploadPage.tsx      # Upload PDF / URL / email
└── services/api.ts         # Typed API client (all fetch calls)
```

---

## 4. Deploying Changes

### 4a. Backend (Lambda)

Any change to `backend/` requires rebuilding the Docker image:

```bash
# From repo root
REPO="563142504525.dkr.ecr.us-east-1.amazonaws.com/cdk-hnb659fds-container-assets-563142504525-us-east-1"
NEWTAG="my-change-$(date +%s)"

# Build (must be linux/amd64 for Lambda)
sg docker -c "docker build --platform linux/amd64 -t ${REPO}:${NEWTAG} backend 2>&1 | tail -5"

# Push to ECR (Docker must be logged in to ECR)
# aws ecr get-login-password | docker login --username AWS --password-stdin ${REPO%%/*}
sg docker -c "docker push ${REPO}:${NEWTAG} 2>&1 | tail -3"

# Update Lambda
aws lambda update-function-code \
  --function-name "CeepComputeStack-CeepApiLambdaE91D0423-Y8QlvXhUWuQg" \
  --image-uri "${REPO}:${NEWTAG}"

# Wait until ready
aws lambda wait function-updated \
  --function-name "CeepComputeStack-CeepApiLambdaE91D0423-Y8QlvXhUWuQg"

echo "Lambda updated ✓"
```

> **Tip:** The Docker build is cached — changing a single Python file typically takes
> 15–30 seconds, not a full rebuild.

### 4b. Frontend

```bash
cd frontend
npm run build
aws s3 sync dist/ s3://ceep-frontend-563142504525/ --delete --quiet
aws cloudfront create-invalidation --distribution-id E2V5EZNC31X6NU --paths "/*"
cd ..
```

Changes appear at <https://d3voaboc02j1x3.cloudfront.net> within ~30–60 seconds.

### 4c. CDK infrastructure changes

Only needed if you change AWS resources (new routes, IAM permissions, etc.):

```bash
source .venv/bin/activate
cd infrastructure
sg docker -c "bash -c 'source ../.venv/bin/activate && cdk deploy CeepComputeStack --require-approval never'"
```

---

## 5. Key Environment Variables (Lambda)

These are set directly on the Lambda function (not in `.env`):

| Variable | Value | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Activates Groq + fastembed |
| `EMBED_DIM` | `384` | fastembed BAAI/bge-small-en-v1.5 |
| `GROQ_SECRET_ARN` | `arn:aws:secretsmanager:…` | Groq API key from Secrets Manager |
| `DB_SECRET_ARN` | `arn:aws:secretsmanager:…` | DB credentials |
| `PUBLIC_BUCKET` | `ceep-public-docs-563142504525` | |
| `PRIVATE_BUCKET` | `ceep-private-uploads-563142504525` | |
| `ENVIRONMENT` | `production` | |
| `USE_LOCAL_STORAGE` | `false` | Use S3, not local filesystem |

---

## 6. Database Schema (pgvector)

```sql
-- Primary tables (simplified)
sources    (id uuid PK, source_type, source_url, title, consent_flag, created_at)
documents  (id uuid PK, source_id FK, raw_s3_key, clean_s3_key, text_snippet,
            word_count, ingested_at, deleted_at)
chunks     (id uuid PK, document_id FK, chunk_index, chunk_text, token_count,
            embedding vector(384))  -- pgvector column
evidence_cards (id uuid PK, document_id FK, excerpt, citation_label, citation_url,
                topic_tags text[], date_mentioned date)
```

Hybrid search uses:
- **Dense**: `c.embedding <=> query_vector` (cosine distance via pgvector)
- **Keyword**: `to_tsvector('english', chunk_text) @@ plainto_tsquery('english', query)`
- **Combined score**: `0.7 × vector_score + 0.3 × keyword_score`

---

## 7. Adding a New Document Source Type

1. Add the MIME type / file extension to `_extract_text()` in `local_etl.py`.
2. Decide if it's public (→ public S3 bucket) or private (→ private bucket + consent gate).
3. Update `generate_upload_url()` in `storage.py` if routing logic changes.
4. Add the new `source_type` value to the TypeScript `SearchResult` badge map in
   `SearchPage.tsx` and `WritePage.tsx`.

---

## 8. Adding a New Brief Template

Edit `TEMPLATES` in `backend/app/routers/briefs.py`:

```python
"my_template": BriefTemplate(
    id="my_template",
    name="Human-Readable Name",
    description="What this template produces",
    typical_length="300–500 words",
),
```

No frontend changes needed — the template list is fetched dynamically.

---

## 9. Testing Checklist (for Nafis / Yash)

### Upload flows
- [ ] Upload a PDF → confirm it appears in **My Evidence** list with a word count
- [ ] Upload a URL → confirm it fetches, shows title, appears searchable
- [ ] Upload a `.eml` file with consent checkbox → confirm it processes and Subject becomes the title
- [ ] Upload a URL that doesn't exist → confirm you get a clear error, no orphan record

### Search
- [ ] Search `"Lady Evelyn"` → top results should include URL + PDF sources
- [ ] Search `"kindergarten registration"` → results should include email source with purple badge
- [ ] Check that source-type badges (orange PDF / green Web / purple Email) appear correctly
- [ ] Check that "N% match" score is shown

### Ask (RAG)
- [ ] Ask "What did OCDSB decide on March 9, 2026?" → answer should cite the Yahoo Canada article
- [ ] Ask something not in the corpus → CEEP should say "I don't have evidence for this"

### Write
- [ ] Generate a "Local Op-Ed" → draft should contain inline `[1]`…`[N]` markers
- [ ] Draft should NOT have a "Footnotes:" section appended at the bottom
- [ ] "Sources consulted" panel should show coloured badges + real excerpts
- [ ] Click "Copy draft" and paste — should be clean text

### Deletion
- [ ] Delete a test document → confirm it disappears from search results

---

## 10. Known Limitations

| Issue | Status |
|---|---|
| PII scrubbing is regex-based, not ML-powered | By design for cost; AWS Comprehend could replace it |
| Email name redaction only catches `Name <email>` and `Name, Month YYYY` patterns | Conservative to avoid false positives on school names |
| fastembed model downloads on cold start if cache is not warm | Only affects first Lambda invocation after a cold start |
| No authentication / user accounts | MVP scope; community advocacy context |
| Brief generator [N] markers may not always align perfectly with the Sources list | The LLM chooses which sources to cite; sources are ordered by relevance |
