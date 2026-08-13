"""Tests for the retrieval core (tokenizer, BM25, semantic, hybrid RRF)."""

import hashlib

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.retrieval import (
    InvertedIndex,
    UserKnowledgeIndex,
    chunk_hash,
    rrf_search,
    semantic_chunk,
    tokenize_text,
)
from app.knowledge.retrieval.semantic import format_embedding
from app.models.knowledge import KnowledgeChunk, TaskKnowledge
from app.models.task import Task
from app.models.user import User


def test_tokenize_text_porter_and_stopwords() -> None:
    tokens = tokenize_text("The deadline approaches")
    assert "deadlin" in tokens  # Porter stem of "deadline"
    assert "the" not in tokens
    assert tokens == ["deadlin", "approach"]


def test_bm25_returns_ranked_doc_ids() -> None:
    idx = InvertedIndex(user_id=1)
    idx.add_document(1, "database project deadline")
    idx.add_document(2, "buy groceries")
    idx.add_document(3, "database normalization")

    results = idx.bm25_search("database project", limit=3)
    assert results[0][0] == 1  # doc 1 shares both query terms


def test_bm25_idf_laplace_positive() -> None:
    idx = InvertedIndex(user_id=1)
    idx.add_document(1, "deadline asikaso")
    idx.add_document(2, "groceries")
    assert idx.get_bm25_idf("deadline") > 0


def test_semantic_chunk_4_sentences_0_overlap() -> None:
    chunks = semantic_chunk("One. Two. Three. Four. Five. Six. Seven.")
    assert chunks == ["One. Two. Three. Four.", "Five. Six. Seven."]


def test_semantic_chunk_single_unterminated_sentence() -> None:
    chunks = semantic_chunk("This is a single sentence without a period")
    assert chunks == ["This is a single sentence without a period"]


def test_rrf_fuses_rankings() -> None:
    bm25_results = [(1, 0.9), (2, 0.8)]
    semantic_results = [{"chunk_id": 2, "score": 0.9}, {"chunk_id": 3, "score": 0.7}]

    results = rrf_search(bm25_results, semantic_results, k=60, limit=5)
    assert [r["chunk_id"] for r in results] == [2, 1, 3]
    assert round(results[0]["rrf_score"], 4) == 0.0325
    assert round(results[1]["rrf_score"], 4) == 0.0164
    assert round(results[2]["rrf_score"], 4) == 0.0161


def test_hybrid_rrf_beats_single_systems_on_precision3() -> None:
    relevant = {1, 2, 3}
    # Each single system surfaces only 2/3 relevant in its top-3;
    # the RRF union surfaces all three.
    bm25_results = [(1, 9.0), (4, 8.0), (2, 7.0)]
    semantic_results = [
        {"chunk_id": 3, "score": 0.9},
        {"chunk_id": 2, "score": 0.8},
        {"chunk_id": 5, "score": 0.7},
    ]

    fusion = rrf_search(bm25_results, semantic_results, k=60, limit=3)
    fused_hits = sum(1 for r in fusion if r["chunk_id"] in relevant)
    bm25_hits = sum(1 for cid, _ in bm25_results[:3] if cid in relevant)
    sem_hits = sum(1 for r in semantic_results[:3] if r["chunk_id"] in relevant)

    assert fused_hits >= max(bm25_hits, sem_hits)
    assert fused_hits == 3


async def test_per_user_isolation_no_cross_retrieval(db: AsyncSession) -> None:
    user1 = User(username="u1", email="u1@example.com", password="x")
    user2 = User(username="u2", email="u2@example.com", password="x")
    db.add_all([user1, user2])
    await db.flush()

    task1 = Task(title="t1", user_id=user1.id)
    task2 = Task(title="t2", user_id=user2.id)
    db.add_all([task1, task2])
    await db.flush()

    knowledge1 = TaskKnowledge(
        user_id=user1.id, task_id=task1.id, content="deadline project asikaso"
    )
    knowledge2 = TaskKnowledge(
        user_id=user2.id, task_id=task2.id, content="groceries shopping mall"
    )
    db.add_all([knowledge1, knowledge2])
    await db.flush()

    service = UserKnowledgeIndex()
    await service.ingest_chunks(
        db,
        user_id=user1.id,
        task_id=task1.id,
        knowledge_id=knowledge1.id,
        text_chunks=["deadline project asikaso"],
        embeddings=np.ones((1, 384), dtype=np.float32),
    )
    await service.ingest_chunks(
        db,
        user_id=user2.id,
        task_id=task2.id,
        knowledge_id=knowledge2.id,
        text_chunks=["groceries shopping mall"],
        embeddings=np.zeros((1, 384), dtype=np.float32),
    )
    await db.commit()

    user1_results = await service.search(db, user_id=user1.id, query="deadline", limit=5)
    user2_results = await service.search(db, user_id=user2.id, query="groceries", limit=5)
    assert user1_results
    assert user2_results
    user1_ids = {r["chunk_id"] for r in user1_results}
    user2_ids = {r["chunk_id"] for r in user2_results}
    assert user1_ids.isdisjoint(user2_ids)


async def test_content_hash_cache_invalidation(db: AsyncSession) -> None:
    user = User(username="u3", email="u3@example.com", password="x")
    db.add(user)
    await db.flush()
    task = Task(title="t3", user_id=user.id)
    db.add(task)
    await db.flush()
    knowledge = TaskKnowledge(user_id=user.id, task_id=task.id, content="database deadline project")
    db.add(knowledge)
    await db.flush()

    service = UserKnowledgeIndex()
    await service.ingest_chunks(
        db,
        user_id=user.id,
        task_id=task.id,
        knowledge_id=knowledge.id,
        text_chunks=["database deadline project"],
        embeddings=np.ones((1, 384), dtype=np.float32),
    )
    await db.commit()

    first = await service.search(db, user_id=user.id, query="database", limit=5)
    assert first

    # Change the chunk content in the DB (same chunk count, new text).
    chunk = (
        await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.user_id == user.id))
    ).scalar_one()
    chunk.content = "asikaso grocery list"
    chunk.content_hash = chunk_hash(chunk.content)
    await db.commit()

    second = await service.search(db, user_id=user.id, query="grocery", limit=5)
    assert second, "rebuild must pick up the edited content"


async def test_chunks_persist_to_knowledge_chunks(db: AsyncSession) -> None:
    user = User(username="u4", email="u4@example.com", password="x")
    db.add(user)
    await db.flush()
    task = Task(title="t4", user_id=user.id)
    db.add(task)
    await db.flush()

    knowledge = TaskKnowledge(user_id=user.id, task_id=task.id, content="rubric text")
    db.add(knowledge)
    await db.flush()

    emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    stored = format_embedding(emb)
    row = KnowledgeChunk(
        user_id=user.id,
        task_id=task.id,
        knowledge_id=knowledge.id,
        chunk_index=0,
        content="rubric text",
        embedding=stored,
        content_hash=hashlib.sha256(b"rubric text").hexdigest(),
    )
    db.add(row)
    await db.commit()

    loaded = (
        await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id == row.id))
    ).scalar_one()
    assert loaded.embedding == stored
    assert loaded.embedding == "[0.1,0.2,0.3]"
