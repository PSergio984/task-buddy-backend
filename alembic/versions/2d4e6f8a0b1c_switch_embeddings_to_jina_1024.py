"""switch_embeddings_to_jina_1024

Revision ID: 2d4e6f8a0b1c
Revises: 1e2f3a4b5c6d
Create Date: 2026-08-15

Provider switch: production embeddings now come from Jina
jina-embeddings-v3 (1024-dim, free tier) — Groq (now the LLM provider)
has no embedding API and OpenAI billing was rejected. The column is
altered to vector(1024); existing 1536-dim rows cannot cast down, so the
stale corpus (chunks + knowledge rows) is cleared — the boot sweep
re-ingests completed tasks with the new provider. The HNSW index is
rebuilt around the new type. SQLite (dev/CI) stores embeddings as Text
and needs no change.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d4e6f8a0b1c"
down_revision: Union[str, Sequence[str], None] = "1e2f3a4b5c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(
            op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
            table_name="tbl_knowledge_chunks",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
        # 1536-dim vectors cannot cast to vector(1024); the boot sweep
        # re-ingests completed tasks with the new provider (D-06).
        op.execute("DELETE FROM tbl_knowledge_chunks")
        op.execute("DELETE FROM tbl_knowledge")
        op.execute("ALTER TABLE tbl_knowledge_chunks ALTER COLUMN embedding TYPE vector(1024)")
        op.create_index(
            op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
            "tbl_knowledge_chunks",
            ["embedding"],
            unique=False,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(
            op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
            table_name="tbl_knowledge_chunks",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
        op.execute("DELETE FROM tbl_knowledge_chunks")
        op.execute("DELETE FROM tbl_knowledge")
        op.execute("ALTER TABLE tbl_knowledge_chunks ALTER COLUMN embedding TYPE vector(1536)")
        op.create_index(
            op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
            "tbl_knowledge_chunks",
            ["embedding"],
            unique=False,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
