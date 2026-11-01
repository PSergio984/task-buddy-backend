"""diary_kind_and_profile_retention

Revision ID: d7a1f3e94b02
Revises: f32a6021c058
Create Date: 2026-11-02 00:00:00.000000

Issue #67 backend: (a) add DiaryEntry.kind and replace the blanket
uq_diary_entries_user_date with a partial unique index so a user gets exactly
one stand-up per day while freeform entries stay unlimited; (b) add
GameProfile.retention ('90d' | '1y' | 'forever') — the read horizon for
diary/timeline queries; (c) add a partial unique index on
tbl_session_notes.session_id so a session gets at most one reflection note
(session_id goes NULL on session delete via SET NULL, and NULLs don't collide).

This head runs parallel to the #61 branch off the same parent — a known,
expected multi-head; do not merge them here.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a1f3e94b02"
down_revision: Union[str, Sequence[str], None] = "f32a6021c058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_game_profiles",
        sa.Column("retention", sa.String(length=16), server_default="forever", nullable=False),
    )
    # Existing diary rows predate freeform entries — they're all stand-ups.
    with op.batch_alter_table("tbl_diary_entries") as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(length=16), server_default="standup", nullable=False)
        )
        batch_op.drop_constraint("uq_diary_entries_user_date")
    op.create_index(
        "uq_diary_entries_one_standup",
        "tbl_diary_entries",
        ["user_id", "entry_date"],
        unique=True,
        sqlite_where=sa.text("kind = 'standup'"),
        postgresql_where=sa.text("kind = 'standup'"),
    )
    op.create_index(
        "uq_session_notes_one_per_session",
        "tbl_session_notes",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("session_id IS NOT NULL"),
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_session_notes_one_per_session", table_name="tbl_session_notes")
    op.drop_index("uq_diary_entries_one_standup", table_name="tbl_diary_entries")
    with op.batch_alter_table("tbl_diary_entries") as batch_op:
        batch_op.create_unique_constraint("uq_diary_entries_user_date", ["user_id", "entry_date"])
        batch_op.drop_column("kind")
    op.drop_column("tbl_game_profiles", "retention")
