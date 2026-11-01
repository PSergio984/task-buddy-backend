"""add pause_started_at to focus_phases + stopwatch milestone rate

Revision ID: b41d7c2e9a01
Revises: f32a6021c058
Create Date: 2026-11-01

Ticket #61: focus session lifecycle. pause_started_at records when the current
pause began (budget accounting is wall-clock). stopwatch_milestone_xp joins the
economy config so milestone XP is tunable like every other rate.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b41d7c2e9a01"
down_revision: Union[str, Sequence[str], None] = "f32a6021c058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _update_economy(bind, mutate) -> None:
    row = bind.execute(
        sa.text("SELECT value FROM tbl_game_config WHERE key = 'economy'")
    ).fetchone()
    if row is None:
        return
    raw = row[0]
    value = dict(raw if isinstance(raw, dict) else json.loads(raw))
    mutate(value)
    stmt = (
        sa.text("UPDATE tbl_game_config SET value = CAST(:v AS jsonb) WHERE key = 'economy'")
        if bind.dialect.name == "postgresql"
        else sa.text("UPDATE tbl_game_config SET value = :v WHERE key = 'economy'")
    )
    bind.execute(stmt, {"v": json.dumps(value)})


def upgrade() -> None:
    op.add_column(
        "tbl_focus_phases",
        sa.Column("pause_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Merge the milestone rate into the economy seed row (portable JSON merge).
    _update_economy(op.get_bind(), lambda v: v.setdefault("stopwatch_milestone_xp", 25.0))
    # Session status is app-disciplined — a CHECK fails fast on typos or new
    # statuses that would silently bypass the partial one-active index.
    with op.batch_alter_table("tbl_focus_sessions") as batch:
        batch.create_check_constraint(
            "ck_focus_sessions_status",
            "status IN ('active', 'ended', 'abandoned')",
        )


def downgrade() -> None:
    with op.batch_alter_table("tbl_focus_sessions") as batch:
        batch.drop_constraint("ck_focus_sessions_status", type_="check")
    _update_economy(op.get_bind(), lambda v: v.pop("stopwatch_milestone_xp", None))
    op.drop_column("tbl_focus_phases", "pause_started_at")
