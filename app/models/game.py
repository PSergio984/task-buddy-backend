"""Gamified-focus-layer models: RPG profile, event ledger, focus, habits,
dailies, gear, achievements, config, diary, notes, and notification prefs."""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# JSONB on Postgres, plain JSON everywhere else (SQLite test DB cannot compile JSONB).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class HabitDirection(str, enum.Enum):
    """Which click directions a habit accepts."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOTH = "both"


class GameProfile(Base):
    """Cached RPG totals for a user; the event ledger is the source of truth."""

    __tablename__ = "tbl_game_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # XP progress within the current level (Habitica-style, resets on death).
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    hp: Mapped[float] = mapped_column(Float, default=50.0, server_default="50", nullable=False)
    max_hp: Mapped[float] = mapped_column(Float, default=50.0, server_default="50", nullable=False)
    gold: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    # The four stat columns are the ALLOCATED pool — what unspent points buy
    # into and what the death cascade decrements. Spec's "base" stats are
    # level-derived and land with the character sheet (#64), not stored here.
    str_stat: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    int_stat: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    con_stat: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    per_stat: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    unspent_stat_points: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    game_class: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_allocate: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    # DiceBear config blob: {style, seed, traits, costume}
    avatar_config: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    # Daily-cap bookkeeping; reset when totals_day rolls over.
    xp_today: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    gold_today: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    totals_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Diary/timeline read horizon: '90d' | '1y' | 'forever'. A read filter
    # only — nothing is deleted when the window shrinks.
    retention: Mapped[str] = mapped_column(
        String(16), default="forever", server_default="forever", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GameEvent(Base):
    """Immutable event ledger row; client_event_id is the idempotency key."""

    __tablename__ = "tbl_game_events"
    __table_args__ = (
        UniqueConstraint("user_id", "client_event_id", name="uq_game_events_user_client_event"),
        # The catchup feed filters user_id + id > cursor; the uq above already
        # leads with user_id, so no standalone user_id index is needed.
        Index("ix_game_events_user_feed", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    client_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Python-side default: consistent microsecond server_ts across SQLite and
    # Postgres (CURRENT_TIMESTAMP is second-granularity on SQLite).
    server_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class FocusSession(Base):
    """One focus timer run; at most one active session per user (API-enforced)."""

    __tablename__ = "tbl_focus_sessions"
    __table_args__ = (
        # Partial unique: at most one row with status='active' per user.
        Index(
            "uq_focus_sessions_one_active",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    activity_label: Mapped[str | None] = mapped_column(String, nullable=True)
    preset: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    pause_budget_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    pause_budget_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    speedrun: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FocusPhase(Base):
    """A single work/break phase inside a session — the scored unit."""

    __tablename__ = "tbl_focus_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_focus_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    planned_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pause_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Habit(Base):
    """A +/- scored counter with value drift; can bind to focus for auto-clicks."""

    __tablename__ = "tbl_habits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction: Mapped[HabitDirection] = mapped_column(
        SQLEnum(HabitDirection, values_callable=lambda members: [m.value for m in members]),
        default=HabitDirection.BOTH,
        nullable=False,
    )
    difficulty: Mapped[str] = mapped_column(String(16), default="easy", nullable=False)
    # Habitica-style hidden value driving drift; clamped [-47.27, +21.27].
    value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    counter: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    bind_focus: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    reminder_times: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Daily(Base):
    """A recurring checklist day-item with a forgiving streak rule."""

    __tablename__ = "tbl_dailies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(16), default="easy", nullable=False)
    # Recurrence rule blob, e.g. {"kind": "weekdays", "days": [1,3,5]}
    recurrence: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    reminder_times: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DailyItem(Base):
    """A recurring checklist sub-item inside a daily."""

    __tablename__ = "tbl_daily_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_dailies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DailyCheck(Base):
    """One completion mark for a daily (or a sub-item) on a given date."""

    __tablename__ = "tbl_daily_checks"
    __table_args__ = (
        # One mark per (daily, item-or-whole, day). daily_item_id is NULL for
        # whole-daily checks; COALESCE makes the constraint treat NULL as a
        # real key on both Postgres and SQLite.
        Index(
            "uq_daily_checks_day",
            "daily_id",
            func.coalesce(sa.column("daily_item_id"), 0),
            "check_date",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_dailies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    daily_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_daily_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    check_date: Mapped[date] = mapped_column(Date, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GearItem(Base):
    """Catalog row for purchasable equipment (seeded content)."""

    __tablename__ = "tbl_gear_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slot: Mapped[str] = mapped_column(String(32), nullable=False)
    klass: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Raw stat bonuses, e.g. {"str": 3, "con": 0, "int": 0, "per": 0}
    stats: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Free/special items can't be lost on death (Habitica losableItems rule).
    losable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class UserGear(Base):
    """A user's owned gear; equipment vs costume are independent flags."""

    __tablename__ = "tbl_user_gear"
    __table_args__ = (UniqueConstraint("user_id", "gear_item_id", name="uq_user_gear_user_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    gear_item_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_gear_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipped: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    costume: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Achievement(Base):
    """Registry row describing one earnable achievement."""

    __tablename__ = "tbl_achievements"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Machine-readable trigger, e.g. {"kind": "level", "threshold": 10}
    criteria: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    gold_reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class UserAchievement(Base):
    """An achievement earned by a user."""

    __tablename__ = "tbl_user_achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_user_achievements_user_achievement"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    achievement_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameConfig(Base):
    """Tunable rate table; one JSONB value per key (e.g. "economy")."""

    __tablename__ = "tbl_game_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JsonType, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class DiaryEntry(Base):
    """A user-authored diary entry: one stand-up per day, unlimited freeform."""

    __tablename__ = "tbl_diary_entries"
    __table_args__ = (
        # Partial unique: at most one stand-up row per (user, day);
        # kind='freeform' rows are unlimited.
        Index(
            "uq_diary_entries_one_standup",
            "user_id",
            "entry_date",
            unique=True,
            sqlite_where=text("kind = 'standup'"),
            postgresql_where=text("kind = 'standup'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # 'standup' rows are unique per (user, entry_date); 'freeform' are not.
    kind: Mapped[str] = mapped_column(
        String(16), default="standup", server_default="standup", nullable=False
    )
    good: Mapped[str | None] = mapped_column(Text, nullable=True)
    bad: Mapped[str | None] = mapped_column(Text, nullable=True)
    next: Mapped[str | None] = mapped_column(Text, nullable=True)
    freeform: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SessionNote(Base):
    """A skippable reflection note prompted after a focus session."""

    __tablename__ = "tbl_session_notes"
    __table_args__ = (
        # One note per session; rows keep NULL session_id after the session
        # row is deleted (SET NULL), and NULLs never collide.
        Index(
            "uq_session_notes_one_per_session",
            "session_id",
            unique=True,
            sqlite_where=text("session_id IS NOT NULL"),
            postgresql_where=text("session_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_focus_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameNotificationPref(Base):
    """Per-type x channel notification matrix plus the global quiet window."""

    __tablename__ = "tbl_game_notification_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # {"streak_risk": {"push": true, "email": false, ...}, ...}
    prefs: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    # {"start": "22:00", "end": "08:00"} — timer alerts exempt.
    quiet_hours: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GameDeviceToken(Base):
    """A push-delivery device token (Expo) registered for a user."""

    __tablename__ = "tbl_game_device_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
