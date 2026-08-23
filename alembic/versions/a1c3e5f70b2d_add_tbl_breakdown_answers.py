"""add tbl_breakdown_answers

Revision ID: a1c3e5f70b2d
Revises: 2d4e6f8a0b1c
Create Date: 2026-08-23

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c3e5f70b2d"
down_revision: str | None = "2d4e6f8a0b1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_breakdown_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("tbl_users.id"), nullable=False
        ),
        sa.Column(
            "context_task_id", sa.Integer(), sa.ForeignKey("tbl_tasks.id"), nullable=True
        ),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("response_time_ms", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("input_chars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tbl_breakdown_answers_user_created",
        "tbl_breakdown_answers",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_breakdown_answers_user_created", table_name="tbl_breakdown_answers"
    )
    op.drop_table("tbl_breakdown_answers")
