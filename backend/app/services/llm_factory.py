"""
LLM Factory — single import point for all LLM/embedding calls.

Checks LLM_PROVIDER at startup and delegates to the correct backend:
  LLM_PROVIDER=local   → Ollama  (no AWS, free, runs on your machine)
  LLM_PROVIDER=bedrock → AWS Bedrock Claude 3 + Titan Embeddings

Usage — replace all direct bedrock_client imports with:
    from app.services.llm_factory import embed_text, invoke_llm, stream_llm

This is the ONLY file that knows which provider is active.
Everything else (rag.py, briefs.py, routers) stays provider-agnostic.
"""

from typing import Generator
from app.core.config import get_settings


def embed_text(text: str) -> list[float]:
    """Embed a string. Returns a float vector of length settings.embed_dim."""
    provider = get_settings().llm_provider
    if provider == "bedrock":
        from app.services.bedrock_client import embed_text as _embed
    elif provider == "groq":
        from app.services.fastembed_client import embed_text as _embed  # type: ignore[no-redef]
    else:
        from app.services.ollama_client import embed_text as _embed  # type: ignore[no-redef]
    return _embed(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    provider = get_settings().llm_provider
    if provider == "bedrock":
        from app.services.bedrock_client import embed_batch as _eb
    elif provider == "groq":
        from app.services.fastembed_client import embed_batch as _eb  # type: ignore[no-redef]
    else:
        from app.services.ollama_client import embed_batch as _eb  # type: ignore[no-redef]
    return _eb(texts)


def invoke_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> dict:
    """
    Non-streaming completion.
    Returns {'text': str, 'input_tokens': int, 'output_tokens': int, 'latency_ms': int}.
    """
    provider = get_settings().llm_provider
    if provider == "bedrock":
        from app.services.bedrock_client import invoke_claude
        return invoke_claude(system_prompt, user_message, max_tokens, temperature)
    elif provider == "groq":
        from app.services.groq_client import invoke_groq
        return invoke_groq(system_prompt, user_message, max_tokens, temperature)
    else:
        from app.services.ollama_client import invoke_llm as _invoke
        return _invoke(system_prompt, user_message, max_tokens, temperature)


def stream_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """Streaming completion. Yields text chunks."""
    provider = get_settings().llm_provider
    if provider == "bedrock":
        from app.services.bedrock_client import stream_claude
        yield from stream_claude(system_prompt, user_message, max_tokens)
    elif provider == "groq":
        from app.services.groq_client import stream_groq
        yield from stream_groq(system_prompt, user_message, max_tokens)
    else:
        from app.services.ollama_client import stream_llm as _stream
        yield from _stream(system_prompt, user_message, max_tokens)
