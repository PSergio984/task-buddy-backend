"""diary_kind_and_profile_retention

Revision ID: d7a1f3e94b02
Revises: b41d7c2e9a01
Create Date: 2026-11-02 00:00:00.000000

Issue #67 backend: (a) add DiaryEntry.kind and replace the blanket
uq_diary_entries_user_date with a partial unique index so a user gets exactly
one stand-up per day while freeform entries stay unlimited — plus a plain
(user_id, entry_date) index for list reads, which the partial index cannot
serve (it only covers stand-up rows); (b) add GameProfile.retention
('90d' | '1y' | 'forever') — the read horizon for diary/timeline queries;
(c) add a partial unique index on tbl_session_notes.session_id so a session
gets at most one reflection note (session_id goes NULL on session delete via
SET NULL, and NULLs don't collide) and drop the now-redundant standalone
session_id index it subsumes.

Chained on the #61 revision (b41d7c2e9a01), which merges first — that branch's
file is vendored here so the chain resolves on this branch.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a1f3e94b02"
down_revision: Union[str, Sequence[str], None] = "b41d7c2e9a01"
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
    # The partial unique index only covers kind='standup' rows — plain index
    # so (user_id, entry_date) list reads don't full-scan freeform rows.
    op.create_index(
        "ix_diary_entries_user_date",
        "tbl_diary_entries",
        ["user_id", "entry_date"],
    )
    op.create_index(
        "uq_session_notes_one_per_session",
        "tbl_session_notes",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("session_id IS NOT NULL"),
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    # Redundant: the partial unique index above leads with session_id.
    op.drop_index("ix_tbl_session_notes_session_id", table_name="tbl_session_notes")


def downgrade() -> None:
    op.create_index("ix_tbl_session_notes_session_id", "tbl_session_notes", ["session_id"])
    op.drop_index("uq_session_notes_one_per_session", table_name="tbl_session_notes")
    op.drop_index("ix_diary_entries_user_date", table_name="tbl_diary_entries")
    op.drop_index("uq_diary_entries_one_standup", table_name="tbl_diary_entries")
    # Intentional data loss: the restored (user_id, entry_date) unique admits
    # at most one row per day — freeform rows cannot survive the rollback.
    op.execute("DELETE FROM tbl_diary_entries WHERE kind <> 'standup'")
    with op.batch_alter_table("tbl_diary_entries") as batch_op:
        batch_op.create_unique_constraint("uq_diary_entries_user_date", ["user_id", "entry_date"])
        batch_op.drop_column("kind")
    op.drop_column("tbl_game_profiles", "retention")
