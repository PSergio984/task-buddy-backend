"""Pydantic contracts for the /api/v1/game endpoints."""

import json
import re
from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.game.engine import SERVER_EVENT_TYPES
from app.models.game import GameProfile, HabitDirection

_PAYLOAD_MAX_BYTES = 16 * 1024
_TEXT_MAX_LEN = 10_000

_HabitDirection = Literal["positive", "negative", "both"]
_Difficulty = Literal["trivial", "easy", "medium", "hard"]
_REMINDER_TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


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
        # aware and naive values (which would crash the batch sort). Aware
        # values are converted to UTC — SQLite drops the offset on write, and
        # re-labeling a local wall time as UTC mis-buckets the day views.
        aware = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        try:
            return aware.astimezone(timezone.utc)
        except OverflowError:
            # The instant is representable locally but its UTC form isn't —
            # reject as input error, not a server crash.
            raise ValueError("client_ts out of representable range") from None

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
    retention: str

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
            # Column default applies at flush; an unflushed profile reads None.
            retention=profile.retention or "forever",
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


def _blank_to_none(v: Optional[str]) -> Optional[str]:
    # Whitespace-only text normalizes to NULL, not an empty-looking row.
    if v is None:
        return None
    v = v.strip()
    return v or None


class DiaryEntryIn(BaseModel):
    """A new diary entry; kind picks the uniqueness rule."""

    kind: Literal["standup", "freeform"] = "standup"
    # Missing -> today (UTC). Client may backfill a missed day.
    entry_date: Optional[date] = None
    good: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    bad: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    next: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    freeform: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)

    @field_validator("good", "bad", "next", "freeform")
    @classmethod
    def normalize_text(cls, v: Optional[str]) -> Optional[str]:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def require_some_content(self) -> "DiaryEntryIn":
        # An all-NULL row is a diary page entry with nothing on it.
        if not any((self.good, self.bad, self.next, self.freeform)):
            raise ValueError("entry needs at least one of good/bad/next/freeform")
        return self


class DiaryEntryUpdate(BaseModel):
    """Partial update; only the four text fields are mutable."""

    good: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    bad: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    next: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    freeform: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)

    @field_validator("good", "bad", "next", "freeform")
    @classmethod
    def normalize_text(cls, v: Optional[str]) -> Optional[str]:
        return _blank_to_none(v)


class DiaryEntryRead(BaseModel):
    id: int
    kind: str
    entry_date: date
    good: str | None
    bad: str | None
    next: str | None
    freeform: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiaryListResponse(BaseModel):
    entries: list[DiaryEntryRead]
    # True when the query window held more rows than `limit` returned.
    has_more: bool = False


class SessionNoteIn(BaseModel):
    """The end-of-session reflection note; one per session."""

    content: str = Field(min_length=1, max_length=_TEXT_MAX_LEN)

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("content must not be blank")
        return v


class SessionNoteRead(BaseModel):
    id: int
    session_id: int | None
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RetentionIn(BaseModel):
    retention: Literal["90d", "1y", "forever"]


def _clean_title(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError("title must not be blank")
    return v


def _clean_reminder_times(v: Optional[list[str]]) -> Optional[list[str]]:
    if v is None:
        return None
    for t in v:
        if not isinstance(t, str) or _REMINDER_TIME_RE.fullmatch(t) is None:
            raise ValueError("reminder times must be 'HH:MM' 24-hour strings")
    return v


class HabitIn(BaseModel):
    """A new habit: a +/- counter with optional reminders and focus binding."""

    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    direction: _HabitDirection = "both"
    difficulty: _Difficulty = "easy"
    # Scheduled times the notification ticket delivers; storage only here.
    reminder_times: list[str] = Field(default_factory=list, max_length=24)
    bind_focus: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str) -> str:
        return _clean_title(v) or v

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, v: Optional[str]) -> Optional[str]:
        return _blank_to_none(v)

    @field_validator("reminder_times")
    @classmethod
    def check_reminder_times(cls, v: list[str]) -> list[str]:
        return _clean_reminder_times(v) or []


class HabitUpdate(BaseModel):
    """Partial update; value/counter are engine-owned and never mutable."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    direction: Optional[_HabitDirection] = None
    difficulty: Optional[_Difficulty] = None
    reminder_times: Optional[list[str]] = Field(None, max_length=24)
    bind_focus: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: Optional[str]) -> Optional[str]:
        return _clean_title(v)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, v: Optional[str]) -> Optional[str]:
        return _blank_to_none(v)

    @field_validator("reminder_times")
    @classmethod
    def check_reminder_times(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        return _clean_reminder_times(v)

    @model_validator(mode="after")
    def no_null_on_required_fields(self) -> "HabitUpdate":
        # Only notes is nullable — an explicit null on a required field would
        # write NULL into a non-nullable column at commit time.
        for name in ("title", "direction", "difficulty", "reminder_times", "bind_focus"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class HabitRead(BaseModel):
    """Full habit row; `value` is the hidden drift state the UI badges."""

    id: int
    title: str
    notes: str | None
    direction: HabitDirection
    difficulty: str
    value: float
    counter: int
    bind_focus: bool
    reminder_times: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HabitClickIn(BaseModel):
    """One +/- click; client_event_id dedupes retries and batch replays."""

    direction: Literal["positive", "negative"]
    client_event_id: Optional[str] = Field(None, min_length=1, max_length=128)

    @field_validator("client_event_id")
    @classmethod
    def no_server_namespace(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.startswith("server:"):
            raise ValueError("client_event_id prefix 'server:' is reserved")
        return v


class HabitClickResponse(BaseModel):
    """Post-click habit plus authoritative totals for the HUD."""

    habit: HabitRead
    profile: GameProfileRead
    status: Literal["applied", "duplicate"]
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


class TimelinePhase(BaseModel):
    """One work/break phase — a sub-block inside a session block."""

    seq: int
    kind: str
    status: str
    planned_seconds: int
    actual_seconds: int | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TimelineSessionBlock(BaseModel):
    """A focus session rendered as a span on the day's time axis."""

    id: int
    mode: str
    status: str
    task_id: int | None
    activity_label: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    phases: list[TimelinePhase]


class TimelineMarker(BaseModel):
    """One ledger event rendered as a point marker on the time axis."""

    id: int
    type: str
    ts: datetime
    outcome: dict | None


class TimelineDayResponse(BaseModel):
    """Merged day view: session blocks, ledger markers, and the day's diary."""

    date: date
    sessions: list[TimelineSessionBlock]
    markers: list[TimelineMarker]
    diary: list[DiaryEntryRead]
    server_time: datetime


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
