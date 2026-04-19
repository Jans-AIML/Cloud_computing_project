"""
CEEP Backend — Configuration (pydantic-settings).

All values come from environment variables injected by Lambda.
Local development uses a .env file (never committed — see .gitignore).
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ───────────────────────────────────────────────────────────
    environment: str = "development"

    # ── Database ──────────────────────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ceep"
    db_user: str = "ceep_admin"
    db_password: str = ""            # populated from Secrets Manager at runtime
    db_secret_arn: str = ""          # Lambda reads this at cold-start

    # ── S3 ────────────────────────────────────────────────────────────────────
    public_bucket: str = "ceep-public-docs-local"
    private_bucket: str = "ceep-private-uploads-local"

    # ── AWS ───────────────────────────────────────────────────────────────────
    aws_region_name: str = "us-east-1"

    # ── Bedrock ───────────────────────────────────────────────────────────────
    bedrock_claude_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"

    # ── SQS ───────────────────────────────────────────────────────────────────
    ingest_queue_url: str = ""

    # ── LLM provider ─────────────────────────────────────────────────────────
    # "local"  → Ollama (no AWS needed, free, runs on your machine)
    # "bedrock" → AWS Bedrock (production)
    llm_provider: str = "local"

    # ── Ollama (used when llm_provider=local) ─────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"      # pull with: ollama pull llama3.2
    ollama_embed_model: str = "nomic-embed-text"  # pull with: ollama pull nomic-embed-text

    # ── Local storage (used when llm_provider=local) ──────────────────────────
    # When True, files are saved to local_storage_path instead of S3.
    use_local_storage: bool = True
    local_storage_path: str = "./local_data"

    # ── Embedding dimension ───────────────────────────────────────────────────
    # Must match the model: nomic-embed-text=768, Titan Embeddings v2=1536
    # Set automatically based on provider but can be overridden.
    embed_dim: int = 768  # 768 for local Ollama; switch to 1536 for Bedrock

    # ── Rate limits ───────────────────────────────────────────────────────────
    max_requests_per_minute: int = 20
    max_tokens_per_request: int = 4096
    max_rag_results: int = 8

    # ── Chunk sizes ───────────────────────────────────────────────────────────
    chunk_size: int = 400
    chunk_overlap: int = 50


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Lambda cold-start resolves once."""
    return Settings()
