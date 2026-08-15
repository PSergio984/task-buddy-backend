"""Embedding access — provider-switchable lazy singleton.

``local``  (sentence-transformers, zero per-query cost, offline-capable)
``openai`` (text-embedding-3-small via the API; used in production because the
            ~470MB local model OOMs Render's 512MB tier on first use).

The local path imports sentence_transformers lazily inside get_embedder() so
app boot stays fast and import-safe; tests stub get_embedder() directly.
"""

import asyncio
from typing import Optional

import numpy as np

from app.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
)

_EMBEDDER: Optional[object] = None


def _openai_client():
    """Lazily-built OpenAI client for embeddings (mirrors assistant.py)."""
    from openai import OpenAI

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY)


def _embed_openai(texts: list[str]) -> np.ndarray:
    """Embed via text-embedding-3-small; returns L2-normalized vectors."""
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    client = _openai_client()
    response = client.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=texts)
    vectors = np.asarray([item.embedding for item in response.data], dtype=np.float32)
    if vectors.size == 0:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.where(norms > 0, vectors / norms, vectors)


def get_embedder() -> object:
    """Return the process-global SentenceTransformer, loading it on first use."""
    global _EMBEDDER
    if _EMBEDDER is None:
        try:
            from sentence_transformers import SentenceTransformer

            _EMBEDDER = SentenceTransformer(EMBEDDING_MODEL)
        except Exception as exc:  # pragma: no cover - model-load failure path
            raise RuntimeError("embedder failed to load") from exc
    return _EMBEDDER


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts with normalized vectors (cosine == dot product)."""
    if EMBEDDING_PROVIDER == "openai":
        return _embed_openai(texts)
    embedder = get_embedder()
    embeddings = embedder.encode(texts, normalize_embeddings=True)  # type: ignore[attr-defined]
    return np.asarray(embeddings, dtype=np.float32)


async def aembed_texts(texts: list[str]) -> np.ndarray:
    """Embed asynchronously — both providers are called in a worker thread."""
    return await asyncio.to_thread(embed_texts, texts)
