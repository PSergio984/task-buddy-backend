"""add_plan_answers

Revision ID: 7f3d863bb907
Revises: 472e5ce15af1
Create Date: 2026-08-14 15:49:09.364222

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f3d863bb907'
down_revision: Union[str, Sequence[str], None] = '472e5ce15af1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tbl_plan_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("tbl_users.id"), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=False),
        sa.Column("pool_size", sa.Integer(), nullable=False),
        sa.Column("available_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("tbl_plan_answers")
