"""add_daily_misses

Revision ID: c4e7a91f2b05
Revises: d7a1f3e94b02
Create Date: 2026-05-15 00:00:00.000000

Creates tbl_daily_misses — the daily-miss sweep's (issue #63) correctness
record. One row per evaluated scheduled unit left unchecked past grace; the
(daily_id, scheduled_day) unique constraint is the dedupe anchor that makes
the sweep idempotent across overlapping deploys (ADR 0001): both instances
compute the same unit day, the loser's insert hits the constraint, and only
the winner applies HP loss / streak changes.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e7a91f2b05"
down_revision: Union[str, Sequence[str], None] = "d7a1f3e94b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("(CURRENT_TIMESTAMP)")


def upgrade() -> None:
    op.create_table(
        "tbl_daily_misses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_day", sa.Date(), nullable=False),
        sa.Column("frozen", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("hp_lost", sa.Float(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["daily_id"],
            ["tbl_dailies.id"],
            name=op.f("fk_tbl_daily_misses_daily_id_tbl_dailies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_daily_misses_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_daily_misses")),
        sa.UniqueConstraint("daily_id", "scheduled_day", name="uq_daily_misses_daily_day"),
    )
    op.create_index("ix_tbl_daily_misses_user_id", "tbl_daily_misses", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tbl_daily_misses_user_id", table_name="tbl_daily_misses")
    op.drop_table("tbl_daily_misses")
