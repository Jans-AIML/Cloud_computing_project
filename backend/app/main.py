"""
CEEP FastAPI application — entry point for AWS Lambda via Mangum.

All client requests arrive via API Gateway → Mangum → this app.
Mangum translates the API Gateway event format into a standard ASGI request.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.core.config import get_settings
from app.core.logging import logger
from app.routers import documents, search, rag, briefs

settings = get_settings()

app = FastAPI(
    title="CEEP API",
    description="Community Evidence & Engagement Platform — RAG-backed Q&A and brief generation",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# In production, replace "*" with the actual CloudFront domain after first deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-Id"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(rag.router)
app.include_router(briefs.router)


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "environment": settings.environment}


# ── Admin: DB schema init (called once after first deploy) ────────────────────
@app.post("/admin/init-schema", tags=["ops"])
def init_schema_endpoint():
    """Initialise pgvector schema. Safe to call multiple times (CREATE IF NOT EXISTS)."""
    if settings.environment == "production":
        from app.core.schema import init_schema as _init
        from app.core.database import get_connection
        conn = get_connection()
        try:
            _init(conn)
        finally:
            conn.close()
        return {"status": "schema initialised"}
    return {"status": "skipped (not production)"}


@app.post("/admin/reset-schema", tags=["ops"])
def reset_schema_endpoint():
    """Drop and recreate all tables. Use after changing embed_dim. Data will be lost."""
    if settings.environment == "production":
        from app.core.schema import init_schema as _init
        from app.core.database import get_connection
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    DROP TABLE IF EXISTS rag_queries CASCADE;
                    DROP TABLE IF EXISTS pii_audit CASCADE;
                    DROP TABLE IF EXISTS chunks CASCADE;
                    DROP TABLE IF EXISTS evidence_cards CASCADE;
                    DROP TABLE IF EXISTS documents CASCADE;
                    DROP TABLE IF EXISTS sources CASCADE;
                """)
            conn.commit()
            _init(conn)
        finally:
            conn.close()
        return {"status": "schema reset and reinitialised"}
    return {"status": "skipped (not production)"}


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again."},
    )


# ── Lambda handler ────────────────────────────────────────────────────────────
# Mangum wraps the ASGI app so it can be invoked by API Gateway / Lambda.
handler = Mangum(app, lifespan="off")
