"""Sentence chunking + in-memory semantic index — port of rag-search-engine."""

import re

import numpy as np

DEFAULT_SEMANTIC_CHUNK_SIZE = 4
DEFAULT_CHUNK_OVERLAP = 0


def semantic_chunk(
    text: str,
    max_chunk_size: int = DEFAULT_SEMANTIC_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into sentence groups of up to max_chunk_size sentences."""
    text = text.strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) == 1 and not re.search(r"[.!?]$", sentences[0]):
        sentences = [text]
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    i = 0
    n = len(sentences)
    while i < n:
        chunk_sentences = sentences[i : i + max_chunk_size]
        if chunks and len(chunk_sentences) <= overlap:
            break
        chunks.append(" ".join(chunk_sentences))
        i += max_chunk_size - overlap
    return chunks


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Cosine similarity between two vectors (normalized vectors: dot product)."""
    dot_product = float(np.dot(vec1, vec2))
    norm1 = float(np.linalg.norm(vec1))
    norm2 = float(np.linalg.norm(vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def format_embedding(emb: np.ndarray) -> str:
    """Embedding serialization contract (M6): str(list) literal for pgvector/SQLite."""
    return "[" + ",".join(map(str, emb)) + "]"


def parse_embedding(value: str | list) -> np.ndarray:
    """Inverse of format_embedding. Handles the str(list) literal (SQLite Text
    variant) and the plain float list pgvector returns on Postgres."""
    if isinstance(value, list):
        return np.asarray(value, dtype=np.float32)
    stripped = value.strip()
    if stripped.startswith("["):
        stripped = stripped[1:]
    if stripped.endswith("]"):
        stripped = stripped[:-1]
    return np.array([float(x) for x in stripped.split(",") if x.strip()], dtype=np.float32)


class ChunkedSemanticSearch:
    """In-memory per-user semantic index over knowledge chunks."""

    def __init__(self, model_dim: int = 384) -> None:
        self.model_dim = model_dim
        self._embeddings: dict[int, np.ndarray] = {}
        self._texts: dict[int, str] = {}

    def add_chunk(self, chunk_id: int, text: str, embedding: np.ndarray) -> None:
        """Add (or replace) a chunk's embedding."""
        self._embeddings[chunk_id] = np.asarray(embedding, dtype=np.float32)
        self._texts[chunk_id] = text

    def remove_chunk(self, chunk_id: int) -> None:
        """Remove a chunk from the index."""
        self._embeddings.pop(chunk_id, None)
        self._texts.pop(chunk_id, None)

    def search_chunks(
        self, query_embedding: np.ndarray, limit: int = 10
    ) -> list[dict]:
        """Rank chunks by cosine similarity to the query embedding."""
        scores: list[dict] = []
        for chunk_id, emb in self._embeddings.items():
            score = cosine_similarity(query_embedding, emb)
            scores.append(
                {
                    "chunk_id": chunk_id,
                    "score": score,
                    "text": self._texts[chunk_id],
                }
            )
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:limit]
