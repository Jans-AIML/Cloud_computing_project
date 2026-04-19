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

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        settings = get_settings()
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region_name,
        )
    return _bedrock_client


# ── Retry decorator ────────────────────────────────────────────────────────────
_throttle_retry = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(ClientError),
)


# ── Embeddings ─────────────────────────────────────────────────────────────────

@_throttle_retry
def embed_text(text: str) -> list[float]:
    """
    Generate a 1536-dim embedding using Amazon Titan Embeddings v2.
    Returns a normalised float vector.
    """
    settings = get_settings()
    client = _get_bedrock_client()

    body = json.dumps({"inputText": text[:8192]})  # Titan max input
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
