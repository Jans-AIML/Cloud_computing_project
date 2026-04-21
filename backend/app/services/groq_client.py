"""
Groq client — llama-3.1-8b-instant chat completions.

API key is read from AWS Secrets Manager (GROQ_SECRET_ARN env var) in production,
or directly from the GROQ_API_KEY env var in local development.
"""

import json
import time
from typing import Generator

import boto3
from groq import Groq

from app.core.config import get_settings
from app.core.logging import logger

_groq_client: Groq | None = None
_groq_api_key: str | None = None


def _fetch_groq_api_key() -> str:
    global _groq_api_key
    if _groq_api_key:
        return _groq_api_key

    settings = get_settings()
    if settings.groq_secret_arn:
        sm = boto3.client("secretsmanager", region_name=settings.aws_region_name)
        secret = sm.get_secret_value(SecretId=settings.groq_secret_arn)
        _groq_api_key = json.loads(secret["SecretString"])["api_key"]
    else:
        # Local dev: key passed directly via GROQ_API_KEY env var
        _groq_api_key = settings.groq_api_key

    return _groq_api_key


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=_fetch_groq_api_key())
    return _groq_client


def invoke_groq(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> dict:
    """
    Non-streaming Groq chat completion.
    Returns {'text': str, 'input_tokens': int, 'output_tokens': int, 'latency_ms': int}.
    """
    settings = get_settings()
    if max_tokens > settings.max_tokens_per_request:
        max_tokens = settings.max_tokens_per_request

    client = _get_groq_client()
    t0 = time.monotonic()

    response = client.chat.completions.create(
        model=settings.groq_chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    text = response.choices[0].message.content or ""
    usage = response.usage

    logger.info(
        "groq_invocation",
        model=settings.groq_chat_model,
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
        latency_ms=latency_ms,
    )
    return {
        "text": text,
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "latency_ms": latency_ms,
    }


def stream_groq(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """Streaming Groq chat completion. Yields text chunks."""
    settings = get_settings()
    client = _get_groq_client()

    stream = client.chat.completions.create(
        model=settings.groq_chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
