"""Pydantic contracts for the /api/v1/game endpoints."""

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.game import GameProfile

_PAYLOAD_MAX_BYTES = 16 * 1024


class GameEventIn(BaseModel):
    """One queued client event submitted for authoritative application."""

    client_event_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    client_ts: datetime
    payload: dict = Field(default_factory=dict)

    @field_validator("client_ts")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        # Naive timestamps are assumed UTC so ledger ordering never mixes
        # aware and naive values (which would crash the batch sort).
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)

    @field_validator("payload")
    @classmethod
    def cap_payload_size(cls, v: dict) -> dict:
        # The ledger stores payloads verbatim in JSONB; cap them so a 500-event
        # batch can't grow a user's ledger unboundedly.
        if len(json.dumps(v, default=str, ensure_ascii=False).encode("utf-8")) > _PAYLOAD_MAX_BYTES:
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
            xp_today=profile.xp_today,
            gold_today=profile.gold_today,
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
