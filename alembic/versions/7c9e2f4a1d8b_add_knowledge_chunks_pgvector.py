"""add_knowledge_chunks_pgvector

Revision ID: 7c9e2f4a1d8b
Revises: 2f8c1a4d9b3e
Create Date: 2026-08-12 18:10:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c9e2f4a1d8b"
down_revision: Union[str, Sequence[str], None] = "2f8c1a4d9b3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the knowledge chunks table with a pgvector embedding column."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "tbl_knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384).with_variant(sa.Text(), "sqlite"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_id"],
            ["tbl_knowledge.id"],
            name=op.f("fk_tbl_knowledge_chunks_knowledge_id_tbl_knowledge"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tbl_tasks.id"],
            name=op.f("fk_tbl_knowledge_chunks_task_id_tbl_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_knowledge_chunks_user_id_tbl_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_knowledge_chunks")),
    )
    op.create_index(
        op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
        "tbl_knowledge_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Drop the HNSW index before the chunk table."""
    op.drop_index(
        op.f("ix_tbl_knowledge_chunks_embedding_hnsw"),
        table_name="tbl_knowledge_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("tbl_knowledge_chunks")
