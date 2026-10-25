"""add llm usage reservations

Revision ID: 0ac2c06f6340
Revises: b7e4c8a91d3f
Create Date: 2026-08-26 18:46:16.746577

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ac2c06f6340"
down_revision: str | None = "b7e4c8a91d3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the per-user daily LLM reservation counter (ADR 0002)."""
    op.create_table(
        "tbl_llm_usage_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("tbl_users.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "day", name="uq_tbl_llm_usage_reservations_user_day"),
        sa.CheckConstraint(
            "reserved_tokens >= 0", name="ck_tbl_llm_usage_reservations_nonnegative"
        ),
    )
    op.create_index(
        "ix_tbl_llm_usage_reservations_user_day",
        "tbl_llm_usage_reservations",
        ["user_id", "day"],
    )


def downgrade() -> None:
    """Drop the reservation counter (in-flight prepaid estimates are discarded)."""
    op.drop_index("ix_tbl_llm_usage_reservations_user_day", table_name="tbl_llm_usage_reservations")
    op.drop_table("tbl_llm_usage_reservations")
