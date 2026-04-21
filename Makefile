.PHONY: start setup dev frontend stop clean test bootstrap deploy-infra deploy-frontend deploy-all destroy-infra fix-redactions

# ── Local development commands ─────────────────────────────────────────────────

start:
	@echo "Starting PostgreSQL (Docker)..."
	docker compose up -d
	@echo "Waiting for Postgres to be ready..."
	@until docker exec ceep-db pg_isready -U ceep_admin -d ceep; do sleep 1; done
	@echo "Starting Ollama (native)..."
	@ollama serve &>/tmp/ollama.log & echo "Ollama started (logs: /tmp/ollama.log)"
	@echo "Services ready."

setup: start
	@echo "Pulling Ollama models (this may take a few minutes the first time)..."
	ollama pull llama3.2
	ollama pull nomic-embed-text
	@echo "Initialising database schema..."
	cd backend && ../.venv/bin/python -m app.core.schema
	@echo ""
	@echo "Setup complete. Run 'make dev' to start the backend."

dev:
	@echo "Starting FastAPI backend on http://localhost:8001"
	@echo "  API docs: http://localhost:8001/docs"
	cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

frontend:
	@echo "Starting React frontend on http://localhost:5173"
	cd frontend && npm run dev

install:
	cd backend && ../.venv/bin/pip install -r requirements.txt
	cd frontend && npm install

stop:
	docker compose down
	@pkill ollama 2>/dev/null || true

clean:
	@echo "WARNING: This will delete the database volume and all local data."
	@read -p "Are you sure? [y/N] " ans && [ "$$ans" = "y" ]
	docker compose down -v
	rm -rf backend/local_data

fix-redactions:
	@echo "Removing false-positive [REDACTED-NAME] tags from public document chunks..."
	sudo docker exec ceep-db psql -U ceep_admin -d ceep -c \
		"UPDATE chunks SET chunk_text = regexp_replace(chunk_text, '\[REDACTED-NAME\]\s*', '', 'g') WHERE document_id IN (SELECT d.id FROM documents d JOIN sources s ON s.id = d.source_id WHERE s.source_type IN ('url','pdf')); \
		 UPDATE evidence_cards SET excerpt = regexp_replace(excerpt, '\[REDACTED-NAME\]\s*', '', 'g') WHERE document_id IN (SELECT d.id FROM documents d JOIN sources s ON s.id = d.source_id WHERE s.source_type IN ('url','pdf'));"
	@echo "Done. Restart 'make dev' for changes to take effect."

test:
	cd backend && ../.venv/bin/python -m pytest tests/ -v

seed:
	@echo "Seeding corpus with public sources..."
	CEEP_API_URL=http://localhost:8001 .venv/bin/python scripts/seed_corpus.py

# ── AWS deployment commands ────────────────────────────────────────────────────

bootstrap:
	@echo "Bootstrapping CDK in us-east-1 (one-time setup)..."
	cd infrastructure && cdk bootstrap aws://563142504525/us-east-1

deploy-infra:
	@echo "Deploying StorageStack + ComputeStack + EtlStack + FrontendStack..."
	cd infrastructure && cdk deploy --all --require-approval never --outputs-file ../cdk-outputs.json

deploy-frontend:
	@echo "Building and uploading React frontend to S3..."
	cd frontend && npm run build
	aws s3 sync frontend/dist/assets s3://ceep-frontend-563142504525/assets/ \
		--delete --cache-control "public, max-age=31536000, immutable" --quiet
	aws s3 cp frontend/dist/index.html s3://ceep-frontend-563142504525/index.html \
		--cache-control "no-cache, no-store, must-revalidate"
	@echo "Frontend deployed."

deploy-all:
	bash scripts/deploy.sh

destroy-infra:
	@echo "WARNING: This will destroy all AWS resources and may lose data."
	@read -p "Type 'destroy' to confirm: " ans && [ "$$ans" = "destroy" ]
	cd infrastructure && cdk destroy --all
