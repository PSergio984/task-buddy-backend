"""add tbl_voice_answers

Revision ID: b7e4c8a91d3f
Revises: a1c3e5f70b2d
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4c8a91d3f"
down_revision: str | None = "a1c3e5f70b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_voice_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("tbl_users.id"), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("audio_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stt_model", sa.String(), nullable=False),
        sa.Column("stt_latency_ms", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("response_time_ms", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("available_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tbl_voice_answers_user_created",
        "tbl_voice_answers",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_voice_answers_user_created", table_name="tbl_voice_answers")
    op.drop_table("tbl_voice_answers")
