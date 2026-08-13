"""Ingest pipeline: extract -> chunk -> embed -> persist to tbl_knowledge_chunks."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embeddings import aembed_texts
from app.knowledge.retrieval import UserKnowledgeIndex
from app.knowledge.retrieval.semantic import semantic_chunk
from app.knowledge.sources import source_registry
from app.models.knowledge import TaskKnowledge


async def ingest_knowledge(db: AsyncSession, knowledge: TaskKnowledge) -> list[int]:
    """Extract, chunk, embed, and persist a knowledge row's content. Returns chunk ids."""
    source = source_registry.create(knowledge.source_type, {"content": knowledge.content})
    text = source.extract()

    chunks = semantic_chunk(text)
    if not chunks:
        return []

    embeddings = await aembed_texts(chunks)
    return await UserKnowledgeIndex().ingest_chunks(
        db,
        user_id=knowledge.user_id,
        task_id=knowledge.task_id,
        knowledge_id=knowledge.id,
        text_chunks=chunks,
        embeddings=embeddings,
    )
