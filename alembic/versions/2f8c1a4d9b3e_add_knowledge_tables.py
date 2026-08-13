"""add_knowledge_tables

Revision ID: 2f8c1a4d9b3e
Revises: ed27f78207cd
Create Date: 2026-08-12 17:30:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f8c1a4d9b3e"
down_revision: Union[str, Sequence[str], None] = "ed27f78207cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB on Postgres, plain JSON elsewhere (SQLite migration test cannot compile JSONB).
_json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    """Create the knowledge, knowledge answer, and knowledge feedback tables."""
    op.create_table(
        "tbl_knowledge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_type",
            # Values, not member names — matches the model's values_callable.
            sa.Enum("note", "file", "url", name="sourcetype"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", _json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_knowledge_user_id_tbl_users"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tbl_tasks.id"],
            name=op.f("fk_tbl_knowledge_task_id_tbl_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_knowledge")),
    )
    op.create_table(
        "tbl_knowledge_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=False),
        sa.Column("retrieved_chunks", _json_type, nullable=False),
        sa.Column(
            "judge_verdict",
            sa.Enum("RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT", name="judgeverdict"),
            nullable=True,
        ),
        sa.Column("judge_explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_knowledge_answers_user_id_tbl_users"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tbl_tasks.id"],
            name=op.f("fk_tbl_knowledge_answers_task_id_tbl_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_knowledge_answers")),
    )
    op.create_table(
        "tbl_knowledge_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating IN (-1, 1)",
            name="ck_tbl_knowledge_feedback_rating",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_knowledge_feedback_user_id_tbl_users"),
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["tbl_knowledge_answers.id"],
            name=op.f("fk_tbl_knowledge_feedback_answer_id_tbl_knowledge_answers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_knowledge_feedback")),
    )


def downgrade() -> None:
    """Drop the knowledge tables in reverse dependency order."""
    op.drop_table("tbl_knowledge_feedback")
    op.drop_table("tbl_knowledge_answers")
    op.drop_table("tbl_knowledge")
