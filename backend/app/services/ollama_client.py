"""
Ollama client — local substitute for AWS Bedrock.

Ollama runs on your machine (or in Docker) and exposes an HTTP API
that mirrors the OpenAI format, so the interface matches bedrock_client.py.

Models to pull once Ollama is running:
    docker exec ceep-ollama ollama pull llama3.2
    docker exec ceep-ollama ollama pull nomic-embed-text

Why these models?
- llama3.2 (3B): fast on CPU, good instruction-following, fits on 8 GB RAM
- nomic-embed-text: 768-dim embeddings, fast, no GPU required
"""

import json
import time
from typing import Generator

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.core.config import get_settings
from app.core.logging import logger


def _base_url() -> str:
    return get_settings().ollama_base_url


# Retry on connection errors (Ollama loading a model can take a few seconds)
_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
)


# ── Embeddings ─────────────────────────────────────────────────────────────────

@_retry
def embed_text(text: str) -> list[float]:
    """
    Generate embeddings using Ollama's nomic-embed-text model.
    Returns a 768-dim float vector.
    """
    settings = get_settings()
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{_base_url()}/api/embeddings",
            json={"model": settings.ollama_embed_model, "prompt": text[:4096]},
        )
        response.raise_for_status()
    return response.json()["embedding"]


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [embed_text(t) for t in texts]


# ── Chat completions ───────────────────────────────────────────────────────────

@_retry
def invoke_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> dict:
    """
    Non-streaming Ollama chat completion.
    Returns {'text': str, 'input_tokens': int, 'output_tokens': int, 'latency_ms': int}.
    Interface is identical to bedrock_client.invoke_claude so rag.py needs no changes.
    """
    settings = get_settings()
    t0 = time.monotonic()

    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{_base_url()}/api/chat",
            json={
                "model": settings.ollama_chat_model,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": min(max_tokens, settings.max_tokens_per_request),
                },
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
        )
        response.raise_for_status()

    latency_ms = int((time.monotonic() - t0) * 1000)
    data = response.json()
    text = data["message"]["content"]

    # Ollama reports token counts in eval_count / prompt_eval_count
    input_tokens = data.get("prompt_eval_count", 0)
    output_tokens = data.get("eval_count", 0)

    logger.info(
        "ollama_invocation",
        model=settings.ollama_chat_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }


@_retry
def stream_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """
    Streaming Ollama chat completion.
    Yields text chunks as they arrive — identical interface to bedrock_client.stream_claude.
    """
    settings = get_settings()

    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            f"{_base_url()}/api/chat",
            json={
                "model": settings.ollama_chat_model,
                "stream": True,
                "options": {
                    "temperature": 0.3,
                    "num_predict": min(max_tokens, settings.max_tokens_per_request),
                },
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if chunk.get("done"):
                        break
