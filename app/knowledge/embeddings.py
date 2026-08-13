"""Local embedding model access — lazy process-global singleton.

Zero per-query embedding cost: the model runs locally (sentence-transformers),
never an API. Imports must never require torch — sentence_transformers is
imported lazily inside get_embedder() so app boot stays fast and import-safe.
"""

import asyncio
from typing import Optional

import numpy as np

from app.config import EMBEDDING_MODEL

_EMBEDDER: Optional[object] = None


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
    embedder = get_embedder()
    embeddings = embedder.encode(texts, normalize_embeddings=True)  # type: ignore[attr-defined]
    return np.asarray(embeddings, dtype=np.float32)


async def aembed_texts(texts: list[str]) -> np.ndarray:
    """Embed asynchronously — the model is not async-safe, so run in a thread."""
    return await asyncio.to_thread(embed_texts, texts)
