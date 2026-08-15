"""switch_embeddings_to_openai_1536

Revision ID: 1e2f3a4b5c6d
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-15

Provider switch: production embeddings now come from OpenAI
text-embedding-3-small (1536-dim) — the ~470MB local model OOMs Render's
512MB tier on first knowledge call, killing the service. The column is
altered to vector(1536); the HNSW index is rebuilt around the new type.
SQLite (dev/CI) stores embeddings as Text and needs no change.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e2f3a4b5c6d"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
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
        op.execute("ALTER TABLE tbl_knowledge_chunks ALTER COLUMN embedding TYPE vector(1536)")
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
        op.execute("ALTER TABLE tbl_knowledge_chunks ALTER COLUMN embedding TYPE vector(384)")
        op.create_index(
            op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
            "tbl_knowledge_chunks",
            ["embedding"],
            unique=False,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
