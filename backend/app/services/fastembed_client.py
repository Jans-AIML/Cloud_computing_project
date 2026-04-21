"""
Local embedding client using fastembed (ONNX — no API key, no network calls after first load).

Model: BAAI/bge-small-en-v1.5
  - 384-dim vectors
  - ~22 MB ONNX model file, pre-baked into the Lambda container image at build time.

Cold-start behaviour:
  - Pre-built model lives at /var/task/fastembed_cache (read-only, inside the container image).
  - On cold start, it is copied to /tmp/fastembed_cache (writable) — a fast local copy.
  - Subsequent warm invocations reuse the in-memory model instantly.

Key design:
  - _model is a module-level singleton (survives across warm invocations).
  - _embed_cache deduplicates identical queries to avoid redundant CPU inference.
"""

import hashlib
import os

from fastembed import TextEmbedding

from app.core.logging import logger

_model: TextEmbedding | None = None

# In-memory dedup cache: sha256(text) → vector
_embed_cache: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 500

FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
# /var/task/fastembed_cache is read-only (baked into image); copy to /tmp on cold start.
_BAKED_CACHE = "/var/task/fastembed_cache"
_RUNTIME_CACHE = "/tmp/fastembed_cache"


def _ensure_cache() -> str:
    """
    Return a cache directory containing the pre-built model.

    Preference order:
    1. /tmp/fastembed_cache  — if it already exists from a previous warm invocation
    2. /var/task/fastembed_cache — baked into the container image (read-only but loadable)
    3. /tmp/fastembed_cache  — copy from (2) when (2) write-fails; download if neither exists

    fastembed only needs WRITE access when downloading a model for the first time.
    On warm paths the model is already on disk, so read-only is fine.
    """
    if os.path.exists(_RUNTIME_CACHE):
        return _RUNTIME_CACHE  # already set up from a previous invocation

    if os.path.exists(_BAKED_CACHE):
        # Prefer the baked path directly — avoids a slow copy.
        # fastembed only writes during download, which doesn't happen here.
        return _BAKED_CACHE

    # Local dev / no baked image: model will be downloaded to /tmp on first use
    logger.info("fastembed_cache_download", dst=_RUNTIME_CACHE)
    return _RUNTIME_CACHE


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        cache_dir = _ensure_cache()
        logger.info("fastembed_model_loading", model=FASTEMBED_MODEL)
        _model = TextEmbedding(model_name=FASTEMBED_MODEL, cache_dir=cache_dir)
        logger.info("fastembed_model_ready", model=FASTEMBED_MODEL)
    return _model


def embed_text(text: str) -> list[float]:
    """Embed a single string. Returns a 384-dim float vector."""
    cache_key = hashlib.sha256(text.encode()).hexdigest()
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]

    model = _get_model()
    # fastembed.embed() returns a generator of numpy arrays
    vector: list[float] = next(model.embed([text])).tolist()

    if len(_embed_cache) >= _EMBED_CACHE_MAX:
        # Evict the 50 oldest entries
        for k in list(_embed_cache.keys())[:50]:
            del _embed_cache[k]
    _embed_cache[cache_key] = vector
    return vector


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple strings. Uses fastembed's batched ONNX inference."""
    model = _get_model()
    return [vec.tolist() for vec in model.embed(texts)]

