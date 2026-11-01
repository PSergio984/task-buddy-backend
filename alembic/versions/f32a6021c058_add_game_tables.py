"""add_game_tables

Revision ID: f32a6021c058
Revises: e83e10d0b749
Create Date: 2026-11-01 17:48:38.927089

Creates every table for the gamified focus layer (spec: issue #59, ticket #60):
game profile + event ledger, focus sessions/phases, habits, dailies +
checklists + checks, gear catalog + inventory, achievements, game_config,
diary entries, session notes, notification prefs, and device tokens.
Blocklist/site-block tables are deferred to their own build effort.

Also seeds the "economy" game_config row with the default scoring rates —
GameRates in app/game/engine.py merges these values over its own defaults.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f32a6021c058"
down_revision: Union[str, Sequence[str], None] = "e83e10d0b749"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB on Postgres, plain JSON elsewhere (SQLite migration test cannot compile JSONB).
_json_type = sa.JSON().with_variant(JSONB(), "postgresql")

_NOW = sa.text("(CURRENT_TIMESTAMP)")

_ECONOMY_RATES = {
    "xp_per_minute": 1.0,
    "gold_per_minute": 0.2,
    "int_xp_pct": 0.025,
    "per_gold_pct": 0.02,
    "con_shield_divisor": 250.0,
    "con_shield_floor": 0.1,
    "crit_base_chance": 0.03,
    "crit_str_chance_scale": 100.0,
    "crit_mult_base": 1.5,
    "crit_mult_span": 4.0,
    "crit_mult_soft": 200.0,
    "hp_loss_base": 2.0,
    "habit_drift_base": 0.9747,
    "habit_value_min": -47.27,
    "habit_value_max": 21.27,
    "habit_xp_factor": 6.0,
    "daily_xp_cap": 500,
    "daily_gold_cap": 150.0,
    "lvl_curve_early": 25.0,
    "lvl_curve_lvl5": 150.0,
    "lvl_curve_quad_a": 0.25,
    "lvl_curve_quad_b": 10.0,
    "lvl_curve_quad_c": 139.75,
    "lvl_curve_round": 10.0,
    "crit_mult_max": 3.0,
    "difficulty": {"trivial": 0.1, "easy": 1.0, "medium": 1.5, "hard": 2.0},
}


def upgrade() -> None:
    """Create all gamified tables and seed the economy config."""
    op.create_table(
        "tbl_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("criteria", _json_type, nullable=False),
        sa.Column("gold_reward", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_achievements")),
        sa.UniqueConstraint("key", name=op.f("uq_tbl_achievements_key")),
    )
    op.create_table(
        "tbl_game_config",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", _json_type, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_tbl_game_config")),
    )
    op.create_table(
        "tbl_gear_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("klass", sa.String(length=32), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("stats", _json_type, nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("losable", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_gear_items")),
        sa.UniqueConstraint("key", name=op.f("uq_tbl_gear_items_key")),
    )
    op.create_table(
        "tbl_dailies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("recurrence", _json_type, nullable=False),
        sa.Column("streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("reminder_times", _json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_dailies_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_dailies")),
    )
    op.create_index("ix_tbl_dailies_user_id", "tbl_dailies", ["user_id"])

    op.create_table(
        "tbl_diary_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("good", sa.Text(), nullable=True),
        sa.Column("bad", sa.Text(), nullable=True),
        sa.Column("next", sa.Text(), nullable=True),
        sa.Column("freeform", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_diary_entries_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_diary_entries")),
        sa.UniqueConstraint("user_id", "entry_date", name="uq_diary_entries_user_date"),
    )

    op.create_table(
        "tbl_game_device_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_game_device_tokens_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_game_device_tokens")),
        sa.UniqueConstraint("token", name=op.f("uq_tbl_game_device_tokens_token")),
    )
    op.create_index("ix_tbl_game_device_tokens_user_id", "tbl_game_device_tokens", ["user_id"])

    op.create_table(
        "tbl_game_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_event_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", _json_type, nullable=False),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_ts", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_game_events_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_game_events")),
        sa.UniqueConstraint("user_id", "client_event_id", name="uq_game_events_user_client_event"),
    )
    # The catchup feed filters user_id + id > cursor; the uq already leads
    # with user_id so no standalone user_id index is needed.
    op.create_index("ix_game_events_user_feed", "tbl_game_events", ["user_id", "id"])

    op.create_table(
        "tbl_game_notification_prefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("prefs", _json_type, nullable=False),
        sa.Column("quiet_hours", _json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_game_notification_prefs_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_game_notification_prefs")),
        sa.UniqueConstraint("user_id", name=op.f("uq_tbl_game_notification_prefs_user_id")),
    )
    op.create_table(
        "tbl_game_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), server_default="1", nullable=False),
        sa.Column("xp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hp", sa.Float(), server_default="50", nullable=False),
        sa.Column("max_hp", sa.Float(), server_default="50", nullable=False),
        sa.Column("gold", sa.Float(), server_default="0", nullable=False),
        sa.Column("str_stat", sa.Integer(), server_default="0", nullable=False),
        sa.Column("int_stat", sa.Integer(), server_default="0", nullable=False),
        sa.Column("con_stat", sa.Integer(), server_default="0", nullable=False),
        sa.Column("per_stat", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unspent_stat_points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("game_class", sa.String(), nullable=True),
        sa.Column("auto_allocate", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("avatar_config", _json_type, nullable=False),
        sa.Column("xp_today", sa.Integer(), server_default="0", nullable=False),
        sa.Column("gold_today", sa.Float(), server_default="0", nullable=False),
        sa.Column("totals_day", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_game_profiles_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_game_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_tbl_game_profiles_user_id")),
    )
    op.create_table(
        "tbl_habits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # Values, not member names — matches the model's values_callable.
        sa.Column(
            "direction",
            sa.Enum("positive", "negative", "both", name="habitdirection"),
            nullable=False,
        ),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Float(), server_default="0", nullable=False),
        sa.Column("counter", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bind_focus", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("reminder_times", _json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_habits_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_habits")),
    )
    op.create_index("ix_tbl_habits_user_id", "tbl_habits", ["user_id"])

    op.create_table(
        "tbl_user_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("achievement_id", sa.Integer(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["achievement_id"],
            ["tbl_achievements.id"],
            name=op.f("fk_tbl_user_achievements_achievement_id_tbl_achievements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_user_achievements_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_user_achievements")),
        sa.UniqueConstraint(
            "user_id", "achievement_id", name="uq_user_achievements_user_achievement"
        ),
    )
    op.create_index(
        "ix_tbl_user_achievements_achievement_id",
        "tbl_user_achievements",
        ["achievement_id"],
    )

    op.create_table(
        "tbl_user_gear",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gear_item_id", sa.Integer(), nullable=False),
        sa.Column("equipped", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("costume", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["gear_item_id"],
            ["tbl_gear_items.id"],
            name=op.f("fk_tbl_user_gear_gear_item_id_tbl_gear_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_user_gear_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_user_gear")),
        sa.UniqueConstraint("user_id", "gear_item_id", name="uq_user_gear_user_item"),
    )
    op.create_index("ix_tbl_user_gear_gear_item_id", "tbl_user_gear", ["gear_item_id"])

    op.create_table(
        "tbl_daily_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["daily_id"],
            ["tbl_dailies.id"],
            name=op.f("fk_tbl_daily_items_daily_id_tbl_dailies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_daily_items")),
    )
    op.create_index("ix_tbl_daily_items_daily_id", "tbl_daily_items", ["daily_id"])

    op.create_table(
        "tbl_daily_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_id", sa.Integer(), nullable=False),
        sa.Column("daily_item_id", sa.Integer(), nullable=True),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["daily_id"],
            ["tbl_dailies.id"],
            name=op.f("fk_tbl_daily_checks_daily_id_tbl_dailies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["daily_item_id"],
            ["tbl_daily_items.id"],
            name=op.f("fk_tbl_daily_checks_daily_item_id_tbl_daily_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_daily_checks")),
    )
    op.create_index("ix_tbl_daily_checks_daily_id", "tbl_daily_checks", ["daily_id"])
    op.create_index("ix_tbl_daily_checks_daily_item_id", "tbl_daily_checks", ["daily_item_id"])
    # One mark per (daily, item-or-whole, day); COALESCE makes NULL item ids
    # (whole-daily checks) collide correctly on Postgres and SQLite.
    op.create_index(
        "uq_daily_checks_day",
        "tbl_daily_checks",
        [
            sa.text("daily_id"),
            sa.text("COALESCE(daily_item_id, 0)"),
            sa.text("check_date"),
        ],
        unique=True,
    )

    op.create_table(
        "tbl_focus_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("activity_label", sa.String(), nullable=True),
        sa.Column("preset", _json_type, nullable=True),
        sa.Column("pause_budget_count", sa.Integer(), nullable=False),
        sa.Column("pause_budget_seconds", sa.Integer(), nullable=False),
        sa.Column("speedrun", _json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tbl_tasks.id"],
            name=op.f("fk_tbl_focus_sessions_task_id_tbl_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_focus_sessions_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_focus_sessions")),
    )
    op.create_index("ix_tbl_focus_sessions_user_id", "tbl_focus_sessions", ["user_id"])
    op.create_index("ix_tbl_focus_sessions_task_id", "tbl_focus_sessions", ["task_id"])
    # Partial unique: at most one row with status='active' per user.
    op.create_index(
        "uq_focus_sessions_one_active",
        "tbl_focus_sessions",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "tbl_focus_phases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("planned_seconds", sa.Integer(), nullable=False),
        sa.Column("actual_seconds", sa.Integer(), nullable=True),
        sa.Column("pause_count", sa.Integer(), nullable=False),
        sa.Column("paused_seconds", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["tbl_focus_sessions.id"],
            name=op.f("fk_tbl_focus_phases_session_id_tbl_focus_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_focus_phases")),
    )
    op.create_index("ix_tbl_focus_phases_session_id", "tbl_focus_phases", ["session_id"])

    op.create_table(
        "tbl_session_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["tbl_focus_sessions.id"],
            name=op.f("fk_tbl_session_notes_session_id_tbl_focus_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tbl_users.id"],
            name=op.f("fk_tbl_session_notes_user_id_tbl_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbl_session_notes")),
    )
    op.create_index("ix_tbl_session_notes_user_id", "tbl_session_notes", ["user_id"])
    op.create_index("ix_tbl_session_notes_session_id", "tbl_session_notes", ["session_id"])

    # Seed the tunable economy rates — mirrors GameRates defaults in the engine.
    game_config = sa.table(
        "tbl_game_config",
        sa.column("key", sa.String),
        sa.column("value", _json_type),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        game_config,
        [
            {
                "key": "economy",
                "value": _ECONOMY_RATES,
                "description": "Scoring-engine tunables: curve params, stat "
                "effects, crits, drift, caps, difficulty multipliers.",
            }
        ],
    )


def downgrade() -> None:
    """Drop all gamified tables in FK-safe order.

    DATA LOSS: every game row (ledger, profile, habits, dailies, gear,
    achievements, diary, notes, prefs, tokens) is permanently discarded."""
    op.drop_table("tbl_session_notes")
    op.drop_table("tbl_focus_phases")
    op.drop_table("tbl_focus_sessions")
    op.drop_table("tbl_daily_checks")
    op.drop_table("tbl_daily_items")
    op.drop_table("tbl_dailies")
    op.drop_table("tbl_user_gear")
    op.drop_table("tbl_gear_items")
    op.drop_table("tbl_user_achievements")
    op.drop_table("tbl_achievements")
    op.drop_table("tbl_diary_entries")
    op.drop_table("tbl_game_device_tokens")
    op.drop_table("tbl_game_notification_prefs")
    op.drop_table("tbl_game_events")
    op.drop_table("tbl_habits")
    op.drop_table("tbl_game_profiles")
    op.drop_table("tbl_game_config")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS habitdirection")
