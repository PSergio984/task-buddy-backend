"""Pydantic contracts for the /api/v1/game endpoints."""

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.game.engine import SERVER_EVENT_TYPES
from app.models.game import GameProfile

_PAYLOAD_MAX_BYTES = 16 * 1024


class GameEventIn(BaseModel):
    """One queued client event submitted for authoritative application."""

    client_event_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    client_ts: datetime
    payload: dict = Field(default_factory=dict)

    @field_validator("client_event_id")
    @classmethod
    def no_server_namespace(cls, v: str) -> str:
        # Server-authored events own the "server:" prefix — a client could
        # otherwise squat a server id and suppress the real event via dedupe.
        if v.startswith("server:"):
            raise ValueError("client_event_id prefix 'server:' is reserved")
        return v

    @field_validator("type")
    @classmethod
    def no_server_event_type(cls, v: str) -> str:
        # Session-lifecycle types are server-authored — a client claiming
        # them could award itself milestone/phase XP or forge history.
        if v in SERVER_EVENT_TYPES:
            raise ValueError(f"event type '{v}' is server-authored")
        return v

    @field_validator("client_ts")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        # Naive timestamps are assumed UTC so ledger ordering never mixes
        # aware and naive values (which would crash the batch sort).
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)

    @field_validator("payload")
    @classmethod
    def cap_payload_size(cls, v: dict) -> dict:
        # "_"-prefixed keys are server-reserved (e.g. "_outcome"); overwriting
        # client data in the ledger would silently hide it.
        if any(key.startswith("_") for key in v):
            raise ValueError("payload keys starting with '_' are reserved")
        # Cap bytes so a batch can't grow the ledger unboundedly, and reject
        # non-finite floats in unused fields — dumps would emit Infinity,
        # which JSONB rejects with a 500 at insert time.
        try:
            size = len(
                json.dumps(v, default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")
            )
        except ValueError:
            raise ValueError("payload contains a non-finite number") from None
        if size > _PAYLOAD_MAX_BYTES:
            raise ValueError("payload exceeds 16 KB")
        return v


class GameEventBatch(BaseModel):
    """Batch sync payload; transactional — all valid events or none."""

    events: list[GameEventIn] = Field(min_length=1, max_length=500)


class GameEventResult(BaseModel):
    client_event_id: str
    status: Literal["applied", "duplicate"]


class GameProfileRead(BaseModel):
    """Authoritative RPG totals as returned to the client."""

    level: int
    xp: int
    xp_to_next_level: int
    hp: float
    max_hp: float
    gold: float
    str_stat: int
    int_stat: int
    con_stat: int
    per_stat: int
    unspent_stat_points: int
    game_class: str | None
    avatar_config: dict
    xp_today: int
    gold_today: float

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_profile(cls, profile: GameProfile, xp_to_next: int) -> "GameProfileRead":
        # Read only exposed fields — touching server_default columns after a
        # flush would trigger an expired-attribute lazy load (async-unsafe).
        # Daily counters reset inside award_* only; a next-day read must
        # report zero rather than yesterday's earnings.
        is_today = profile.totals_day == datetime.now(timezone.utc).date()
        return cls(
            level=profile.level,
            xp=profile.xp,
            xp_to_next_level=xp_to_next,
            hp=profile.hp,
            max_hp=profile.max_hp,
            gold=profile.gold,
            str_stat=profile.str_stat,
            int_stat=profile.int_stat,
            con_stat=profile.con_stat,
            per_stat=profile.per_stat,
            unspent_stat_points=profile.unspent_stat_points,
            game_class=profile.game_class,
            avatar_config=profile.avatar_config or {},
            xp_today=profile.xp_today if is_today else 0,
            gold_today=profile.gold_today if is_today else 0.0,
        )


class GameSyncResponse(BaseModel):
    """Authoritative totals plus per-event application results."""

    profile: GameProfileRead
    results: list[GameEventResult]
    applied: int
    duplicates: int
    server_time: datetime


class GameEventRead(BaseModel):
    """One ledger row in the catchup feed."""

    id: int
    client_event_id: str
    type: str
    payload: dict
    client_ts: datetime
    server_ts: datetime

    model_config = ConfigDict(from_attributes=True)


class GameEventsFeedResponse(BaseModel):
    events: list[GameEventRead]
    server_time: datetime


class SessionPhaseIn(BaseModel):
    """One leg of a focus plan: focus minutes or a break between focus legs."""

    kind: Literal["focus", "break"]
    minutes: int = Field(gt=0, le=600)


class SessionStartIn(BaseModel):
    """Open a focus session. mode=stopwatch ignores `phases` (open-ended)."""

    mode: Literal["timer", "stopwatch"] = "timer"
    phases: list[SessionPhaseIn] | None = Field(default=None, max_length=32)
    task_id: int | None = None
    tag_id: int | None = None
    activity_label: str | None = Field(default=None, max_length=200)
    difficulty: Literal["trivial", "easy", "medium", "hard"] = "easy"
    auto_start_breaks: bool = True
    auto_start_focus: bool = False
    pause_budget_count: int = Field(default=3, ge=0, le=20)
    pause_budget_seconds: int = Field(default=300, gt=0, le=3600)


class SessionPhaseOut(BaseModel):
    seq: int
    kind: str
    status: str
    planned_seconds: int
    actual_seconds: int | None
    pause_count: int
    paused_seconds: int
    pause_started_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class FocusSessionOut(BaseModel):
    id: int
    mode: str
    status: str
    task_id: int | None
    activity_label: str | None
    preset: dict | None
    pause_budget_count: int
    pause_budget_seconds: int
    started_at: datetime
    ended_at: datetime | None
    phases: list[SessionPhaseOut]


class SessionActionResponse(BaseModel):
    """Session view after evaluation + the applied action, with totals."""

    session: FocusSessionOut
    profile: GameProfileRead | None
    server_time: datetime
