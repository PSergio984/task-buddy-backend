"""Retrieval core: BM25 + semantic + RRF fusion, per-user scoped."""

import asyncio
import hashlib

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embeddings import aembed_texts
from app.knowledge.retrieval.bm25 import BM25_B, BM25_K1, InvertedIndex
from app.knowledge.retrieval.hybrid import RRF_K, rrf_search
from app.knowledge.retrieval.semantic import (
    ChunkedSemanticSearch,
    format_embedding,
    parse_embedding,
    semantic_chunk,
)
from app.knowledge.retrieval.tokenize import tokenize_text
from app.models.knowledge import KnowledgeChunk

__all__ = [
    "BM25_B",
    "BM25_K1",
    "RRF_K",
    "InvertedIndex",
    "ChunkedSemanticSearch",
    "rrf_search",
    "semantic_chunk",
    "tokenize_text",
    "format_embedding",
    "parse_embedding",
    "chunk_hash",
    "UserKnowledgeIndex",
]

# Retrieval pool expansion per result: each system fetches limit * 500
# candidates so RRF can fuse deep ranks (port of rag-search-engine).
RRF_POOL_MULTIPLIER = 500


def chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class UserKnowledgeIndex:
    """Per-user in-process retrieval index over tbl_knowledge_chunks.

    Each user gets a private BM25 + semantic index, rebuilt when the stored
    chunk content hashes change. Chunk inserts/deletes are scoped by
    knowledge_id + user_id (T-7-02/T-7-05). The shared cache is process-wide;
    rebuilds build-then-swap so a search never sees a half-built index.
    """

    _cache: dict[int, dict] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Drop all in-memory indexes (test isolation / cache eviction)."""
        cls._cache.clear()

    def _entry(self, user_id: int) -> dict:
        return self._cache.setdefault(
            user_id,
            {
                "content_hash": None,
                "bm25": InvertedIndex(user_id=user_id),
                "semantic": ChunkedSemanticSearch(),
            },
        )

    async def ensure_index(self, db: AsyncSession, user_id: int) -> None:
        """Build/rebuild the user's index when the stored chunk set changed."""
        result = await db.execute(
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.content,
                KnowledgeChunk.embedding,
                KnowledgeChunk.content_hash,
            )
            .where(KnowledgeChunk.user_id == user_id)
            .order_by(KnowledgeChunk.id)
        )
        rows = result.all()

        corpus_hash = chunk_hash("|".join(f"{r.id}:{r.content_hash}" for r in rows))
        entry = self._entry(user_id)
        if entry["content_hash"] == corpus_hash:
            return

        # Build fresh objects, then swap — stale chunks never survive an edit.
        bm25 = InvertedIndex(user_id=user_id)
        semantic = ChunkedSemanticSearch()
        for chunk_id, content, embedding, _content_hash in rows:
            bm25.add_document(chunk_id, content, metadata={"content": content})
            semantic.add_chunk(chunk_id, content, parse_embedding(embedding))
        self._cache[user_id] = {
            "content_hash": corpus_hash,
            "bm25": bm25,
            "semantic": semantic,
        }

    async def ingest_chunks(
        self,
        db: AsyncSession,
        user_id: int,
        task_id: int,
        knowledge_id: int,
        text_chunks: list[str],
        embeddings: np.ndarray,
    ) -> list[int]:
        """Persist chunk rows (flush-not-commit) and return their ids.

        Embeddings are bound dialect-natively: a float list for pgvector's
        Vector(EMBEDDING_DIM) (its adapter rejects string literals), the format_embedding
        string for the SQLite Text variant.
        """
        is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
        chunk_ids: list[int] = []
        for i, (chunk_text, embedding) in enumerate(zip(text_chunks, embeddings)):
            emb = np.asarray(embedding, dtype=np.float32)
            db_value: str | list[float] = emb.tolist() if is_postgres else format_embedding(emb)
            row = KnowledgeChunk(
                user_id=user_id,
                task_id=task_id,
                knowledge_id=knowledge_id,
                chunk_index=i,
                content=chunk_text,
                embedding=db_value,
                content_hash=chunk_hash(chunk_text),
            )
            db.add(row)
            await db.flush()
            chunk_ids.append(row.id)
        return chunk_ids

    async def remove_knowledge_chunks(
        self, db: AsyncSession, user_id: int, knowledge_id: int
    ) -> None:
        """Delete a knowledge row's chunks (scoped by user)."""
        await db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_id == knowledge_id,
                KnowledgeChunk.user_id == user_id,
            )
        )

    def _sync_search(
        self,
        entry: dict,
        query: str,
        query_embedding: np.ndarray,
        limit: int,
    ) -> list[dict]:
        bm25_results = entry["bm25"].bm25_search(query, limit * RRF_POOL_MULTIPLIER)
        semantic_results = entry["semantic"].search_chunks(
            query_embedding, limit * RRF_POOL_MULTIPLIER
        )
        return rrf_search(bm25_results, semantic_results, limit=limit)

    async def search(
        self, db: AsyncSession, user_id: int, query: str, limit: int = 5
    ) -> list[dict]:
        """Hybrid search: BM25 + semantic fused by RRF, per-user only."""
        await self.ensure_index(db, user_id)
        entry = self._entry(user_id)

        query_embedding = (await aembed_texts([query]))[0]
        # Sync BM25/semantic work off the event loop (T-7-06).
        return await asyncio.to_thread(self._sync_search, entry, query, query_embedding, limit)
