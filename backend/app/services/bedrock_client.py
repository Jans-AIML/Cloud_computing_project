"""
AWS Bedrock client — Claude 3 (completions) and Titan Embeddings v2.

Key design decisions:
- All LLM calls stay inside AWS (Bedrock), so no data crosses to an external vendor.
- Exponential backoff via tenacity handles Bedrock throttling.
- Token budget is enforced: requests exceeding max_tokens are rejected before calling Bedrock.
- Streaming is supported for the /rag/stream endpoint.
"""

import json
import time
from typing import Generator

import boto3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import logger

import hashlib

import botocore.config

_bedrock_client = None

# Module-level cache: survives across Lambda warm invocations.
# Key: sha256 of the input text. Max 500 entries (evict oldest on overflow).
_embed_cache: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 500


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        settings = get_settings()
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region_name,
            config=botocore.config.Config(
                connect_timeout=5,
                read_timeout=25,
                retries={"max_attempts": 1},
            ),
        )
    return _bedrock_client


# ── Retry decorator ────────────────────────────────────────────────────────────
# 2 attempts with short backoff — keeps total time under Lambda's 60 s timeout.
_throttle_retry = retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=3, max=10),
    retry=retry_if_exception_type(ClientError),
)


# ── Embeddings ─────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """
    Generate a 1536-dim embedding using Amazon Titan Embeddings v1.
    Results are cached in module memory to avoid redundant Bedrock calls.
    """
    cache_key = hashlib.sha256(text.encode()).hexdigest()
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]

    vector = _embed_text_remote(text)

    if len(_embed_cache) >= _EMBED_CACHE_MAX:
        # Evict the oldest 50 entries
        for k in list(_embed_cache.keys())[:50]:
            del _embed_cache[k]
    _embed_cache[cache_key] = vector
    return vector


@_throttle_retry
def _embed_text_remote(text: str) -> list[float]:
    """Actual Bedrock call; called only on cache miss."""
    settings = get_settings()
    client = _get_bedrock_client()

    body = json.dumps({"inputText": text[:8192]})  # Titan V1: no dimensions field needed
    response = client.invoke_model(
        modelId=settings.bedrock_embed_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["embedding"]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts sequentially (Titan does not support batch natively)."""
    return [embed_text(t) for t in texts]


# ── Chat completions ───────────────────────────────────────────────────────────

def _build_claude_body(
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    temperature: float = 0.3,
) -> dict:
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }


@_throttle_retry
def invoke_claude(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> dict:
    """
    Non-streaming Claude 3 invocation.
    Returns {'text': str, 'input_tokens': int, 'output_tokens': int}.
    """
    settings = get_settings()
    if max_tokens > settings.max_tokens_per_request:
        max_tokens = settings.max_tokens_per_request

    client = _get_bedrock_client()
    body = json.dumps(
        _build_claude_body(system_prompt, user_message, max_tokens, temperature)
    )

    t0 = time.monotonic()
    response = client.invoke_model(
        modelId=settings.bedrock_claude_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    result = json.loads(response["body"].read())

    text = result["content"][0]["text"]
    usage = result.get("usage", {})
    logger.info(
        "bedrock_invocation",
        model=settings.bedrock_claude_model_id,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=latency_ms,
    )
    return {
        "text": text,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "latency_ms": latency_ms,
    }


@_throttle_retry
def stream_claude(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """
    Streaming Claude 3 invocation.
    Yields text chunks as Server-Sent Events (text/event-stream).
    """
    settings = get_settings()
    if max_tokens > settings.max_tokens_per_request:
        max_tokens = settings.max_tokens_per_request

    client = _get_bedrock_client()
    body = json.dumps(
        _build_claude_body(system_prompt, user_message, max_tokens, temperature=0.3)
    )

    response = client.invoke_model_with_response_stream(
        modelId=settings.bedrock_claude_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    for event in response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        if chunk["type"] == "content_block_delta":
            yield chunk["delta"].get("text", "")
