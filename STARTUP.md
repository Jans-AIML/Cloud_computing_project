# CEEP — Sequential Startup Guide

## Prerequisites

Before anything else, confirm these are installed:

| Tool | Min Version | Check |
|---|---|---|
| Python | 3.10+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Docker Desktop | any | `docker --version` |
| Git | any | `git --version` |

---

## Part 1 — One-Time Setup (run once per machine)

### Step 1 — Clone the repository

```bash
git clone https://github.com/Jans-AIML/Cloud_computing_project
cd Cloud_computing_project
```

### Step 2 — Create the Python virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (Git Bash / WSL)
source .venv/Scripts/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

> Keep this virtual environment active for all subsequent Python steps.

### Step 3 — Install backend Python dependencies

```bash
pip install -r backend/requirements.txt
```

This installs FastAPI, psycopg2, pgvector, groq, fastembed, pdfminer, httpx, and all other backend packages.

### Step 4 — Install frontend Node dependencies

```bash
cd frontend
npm install
cd ..
```

### Step 5 — Copy and configure environment variables

```bash
cp .env.example backend/.env
```

Open `backend/.env` and fill in the required values:

```dotenv
# Required: choose your LLM provider
LLM_PROVIDER=groq          # Recommended for local dev

# Required if LLM_PROVIDER=groq
# Get a free key at https://console.groq.com
GROQ_API_KEY=gsk_your_actual_key_here

# Leave these as-is for local dev (Groq + fastembed)
GROQ_CHAT_MODEL=llama-3.1-8b-instant
EMBED_DIM=384

# Database — matches docker-compose.yml, no changes needed
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ceep
DB_USER=ceep_admin
DB_PASSWORD=changeme_local

# Storage — filesystem for local dev, no S3 needed
USE_LOCAL_STORAGE=true
LOCAL_STORAGE_PATH=./local_data
```

> If you prefer a fully-offline setup, set `LLM_PROVIDER=local` and install Ollama
> (`https://ollama.com`), then run `ollama pull llama3.2 && ollama pull nomic-embed-text`.
> Also set `EMBED_DIM=768` for Ollama's embedding model.

---

## Part 2 — Starting the Stack (run every session)

Run each step **in order**. Steps 1–2 are terminal-independent; Steps 3 and 4 each need their own terminal.

### Step 1 — Start PostgreSQL (Docker)

```bash
docker compose up -d
```

Wait for the database to become ready:

```bash
# macOS / Linux
until docker exec ceep-db pg_isready -U ceep_admin -d ceep; do sleep 1; done

# Or just wait ~10 seconds, then continue
```

> This starts `pgvector/pgvector:pg15` on `localhost:5432`. Data persists in a Docker volume between restarts.

### Step 2 — Initialise the database schema (first start only, or after `make clean`)

```bash
cd backend
python -m app.core.schema
cd ..
```

This runs `CREATE TABLE IF NOT EXISTS` for all tables (`sources`, `documents`, `chunks`, `evidence_cards`, `pii_audit`, `rag_queries`) and creates the HNSW vector index and GIN full-text index. Safe to re-run — it is idempotent.

### Step 3 — Start the FastAPI backend (Terminal 1)

```bash
make dev
```

Or equivalently:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Confirm it is running:
- API root: http://localhost:8001
- Swagger UI: http://localhost:8001/docs

> On the very first request that triggers embedding (e.g., uploading a document), fastembed will
> download the `BAAI/bge-small-en-v1.5` ONNX model (~22 MB) into `backend/local_data/fastembed_cache/`.
> This happens once; subsequent starts are instant.

### Step 4 — Start the React frontend (Terminal 2)

```bash
make frontend
```

Or equivalently:

```bash
cd frontend
npm run dev
```

Frontend is available at: http://localhost:5173

Vite automatically proxies all `/api/*` requests to `localhost:8001`, so no CORS configuration is needed in local dev.

---

## Part 3 — Verify Everything Works

Open http://localhost:5173 and run through this checklist:

- [ ] **Upload tab** — drag in a PDF or paste a public URL; it should appear in the document list
- [ ] **Search tab** — search for a word from the uploaded document; results should show with source badges and match scores
- [ ] **Ask tab** — ask a question about uploaded content; the answer should include inline `[1]`, `[2]` citation markers
- [ ] **Write tab** — pick a template (e.g. "Local Op-Ed"), fill in the fields, generate a brief; citations should appear in the Sources panel

---

## Part 4 — Stopping the Stack

```bash
# Stop Docker (Postgres)
docker compose down

# Stop Ollama if running (Linux/macOS only)
pkill ollama 2>/dev/null || true
```

Or use the Makefile shortcut:

```bash
make stop
```

Data in the Postgres volume is preserved. To wipe everything (destructive):

```bash
make clean   # prompts for confirmation; deletes DB volume + local_data/
```

---

## Part 5 — Optional: Seed the Corpus

To populate the database with a set of pre-defined public sources for testing:

```bash
CEEP_API_URL=http://localhost:8001 .venv/bin/python scripts/seed_corpus.py
```

Run this after the backend is already started (Step 3 above).

---

## Part 6 — AWS Deployment (production only)

> Skip this section for local development. The deployed app is already live at
> https://d3voaboc02j1x3.cloudfront.net.

### One-time CDK bootstrap

```bash
# Requires AWS credentials configured (aws configure or env vars)
make bootstrap
```

### Full deploy (infrastructure + frontend)

```bash
make deploy-all          # runs scripts/deploy.sh end-to-end
```

This does, in order:
1. Builds the React frontend (with placeholder API URL)
2. Deploys CDK stacks: `StorageStack` → `ComputeStack` → `EtlStack` → `FrontendStack`
3. Reads the real API Gateway URL from `cdk-outputs.json`
4. Rebuilds the frontend with the real URL
5. Syncs the build to S3 (`ceep-frontend-563142504525`)
6. Invalidates the CloudFront cache (`E2V5EZNC31X6NU`)

### Deploy only the frontend (after UI-only changes)

```bash
make deploy-frontend
```

### Deploy only backend code changes (no infra changes)

```bash
REPO="563142504525.dkr.ecr.us-east-1.amazonaws.com/cdk-hnb659fds-container-assets-563142504525-us-east-1"
docker build --platform linux/amd64 -t ${REPO}:latest backend/
docker push ${REPO}:latest
aws lambda update-function-code \
  --function-name "CeepComputeStack-CeepApiLambdaE91D0423-Y8QlvXhUWuQg" \
  --image-uri "${REPO}:latest"
```

---

## Quick-Reference Summary

```
# Terminal 0 (once per session)
docker compose up -d
cd backend && python -m app.core.schema && cd ..   # first run only

# Terminal 1
make dev           # FastAPI → http://localhost:8001/docs

# Terminal 2
make frontend      # React  → http://localhost:5173
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `connection refused` on port 5432 | Docker not running | `docker compose up -d` |
| `relation "chunks" does not exist` | Schema not initialised | `cd backend && python -m app.core.schema` |
| `GROQ_API_KEY not set` | Missing `.env` | `cp .env.example backend/.env` then add key |
| Embedding download hangs | First-run fastembed fetch | Wait — 22 MB download; check `backend/local_data/fastembed_cache/` |
| `ModuleNotFoundError` on backend start | Wrong venv or deps not installed | `source .venv/bin/activate && pip install -r backend/requirements.txt` |
| Frontend can't reach API | Backend not started | Start `make dev` first, then `make frontend` |
| Ollama connection refused | `LLM_PROVIDER=local` but Ollama not running | Run `ollama serve` in a separate terminal, or switch to `LLM_PROVIDER=groq` |
