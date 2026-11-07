"""add phone_down blob to focus_sessions + phone-down index/rates

Revision ID: 9c2f7d4a1e5b
Revises: b3a7f2c19d04
Create Date: 2026-12-21 00:00:00.000000

Ticket #70: phone-down focus mode. The per-session overlay state
({enabled, spans, violations, penalized_violation_ats,
reported_client_event_ids}) rides one nullable JSON blob — the same
pattern as the speedrun column in f32a6021c058.

Three riders: ix_game_events_user_type_ts covers the (user_id, type,
server_ts >= floor) scans the span-ingest violation check and the
repeat-window penalty run per applied event / scored phase;
ix_focus_sessions_user_ended covers the verified-streak walk's
user-wide ended_at scans (backward btree serves its DESC ordering);
the four phone_down_* rate keys seed into the economy row via
setdefault-merge (b41d7c2e9a01's stopwatch_milestone_xp precedent) so
operators see the knobs.

DATA LOSS on downgrade: drop_column permanently discards every session's
adjudicated span/violation state (same precedent as e83e10d0b749).
"""

import json
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c2f7d4a1e5b"
down_revision: Union[str, Sequence[str], None] = "b3a7f2c19d04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB on Postgres, plain JSON elsewhere (SQLite migration test cannot compile JSONB).
_json_type = sa.JSON().with_variant(JSONB(), "postgresql")


def _update_economy(bind, mutate) -> None:
    row = bind.execute(
        sa.text("SELECT value FROM tbl_game_config WHERE key = 'economy'")
    ).fetchone()
    if row is None:
        return
    raw = row[0]
    parsed = raw if isinstance(raw, dict) else json.loads(raw)
    if not isinstance(parsed, dict):
        # A corrupt economy row (array/scalar JSON) must not be clobbered
        # with seeded-only keys — skip rather than TypeError mid-upgrade.
        return
    value = dict(parsed)
    mutate(value)
    stmt = (
        sa.text("UPDATE tbl_game_config SET value = CAST(:v AS jsonb) WHERE key = 'economy'")
        if bind.dialect.name == "postgresql"
        else sa.text("UPDATE tbl_game_config SET value = :v WHERE key = 'economy'")
    )
    bind.execute(stmt, {"v": json.dumps(value)})


def _seed_phone_down_rates(value: dict) -> None:
    value.setdefault("phone_down_unverified_xp_factor", 0.5)
    value.setdefault("phone_down_verified_streak_xp_pct", 0.10)
    value.setdefault("phone_down_verified_streak_xp_cap", 0.50)
    value.setdefault("phone_down_violation_repeat_window_hours", 24)


def upgrade() -> None:
    op.add_column(
        "tbl_focus_sessions",
        sa.Column("phone_down", _json_type, nullable=True),
    )
    op.create_index(
        "ix_game_events_user_type_ts",
        "tbl_game_events",
        ["user_id", "type", "server_ts"],
    )
    op.create_index(
        "ix_focus_sessions_user_ended",
        "tbl_focus_sessions",
        ["user_id", "ended_at"],
    )
    _update_economy(op.get_bind(), _seed_phone_down_rates)


def downgrade() -> None:
    # The four phone_down_* keys are left in the economy row: setdefault
    # may have preserved operator-set values, and a leftover key is
    # harmless config (b41d7c2e9a01 precedent).
    op.drop_index("ix_focus_sessions_user_ended", table_name="tbl_focus_sessions")
    op.drop_index("ix_game_events_user_type_ts", table_name="tbl_game_events")
    op.drop_column("tbl_focus_sessions", "phone_down")
