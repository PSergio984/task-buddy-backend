"""Pydantic contracts for the /api/v1/game endpoints."""

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.game import notification_kinds
from app.game.engine import (
    AT_TS_SKEW_SECONDS,
    SERVER_EVENT_TYPES,
    STAT_KEYS,
    STAT_POINT_CAP,
    effective_stat,
)
from app.models.game import GameProfile, HabitDirection

_PAYLOAD_MAX_BYTES = 16 * 1024
_TEXT_MAX_LEN = 10_000
# Server-authored ledger rows own this client_event_id namespace — a
# client claiming it could suppress the real event via dedupe.
SERVER_ID_PREFIX = "server:"
# client_ts bounds: far-past/future instants pass astimezone but overflow
# timedelta subtraction in scoring windows (OverflowError -> 500 the batch).
_CLIENT_TS_MIN_YEAR = 1900
_CLIENT_TS_MAX_YEAR = 2200

_HabitDirection = Literal["positive", "negative", "both"]
_Difficulty = Literal["trivial", "easy", "medium", "hard"]
_REMINDER_TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _check_json_blob(v: dict, field: str) -> None:
    # Shared stored-blob guard: cap bytes so JSONB columns can't grow
    # unboundedly, and reject non-finite floats — dumps would emit Infinity,
    # which Postgres JSONB accepts on write but JSONResponse.render 500s on
    # for every read (SQLite silently poisons the row instead).
    def reject_nul(node: object) -> None:
        # Postgres JSONB also rejects NUL bytes inside stored strings, but
        # an escaped "\u0000" survives the dumps probe below — walk the
        # parsed tree (keys too) to catch them before db.flush().
        if isinstance(node, str):
            if "\x00" in node:
                raise ValueError(f"{field} contains a NUL character")
        elif isinstance(node, dict):
            for key, member in node.items():
                reject_nul(key)
                reject_nul(member)
        elif isinstance(node, list):
            for item in node:
                reject_nul(item)

    reject_nul(v)
    try:
        size = len(json.dumps(v, default=str, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except ValueError:
        raise ValueError(f"{field} contains a non-finite number") from None
    if size > _PAYLOAD_MAX_BYTES:
        raise ValueError(f"{field} exceeds 16 KB")


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
        # Casefolded: the ledger's server-prefix scans are case-insensitive.
        if v.lower().startswith(SERVER_ID_PREFIX):
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
            utc = aware.astimezone(timezone.utc)
        except OverflowError:
            # The instant is representable locally but its UTC form isn't —
            # reject as input error, not a server crash.
            raise ValueError("client_ts out of representable range") from None
        if not (_CLIENT_TS_MIN_YEAR <= utc.year <= _CLIENT_TS_MAX_YEAR):
            # Far-past/future instants are accepted by astimezone but overflow
            # when scoring subtracts windows (timedelta near datetime.min) —
            # the uncaught OverflowError would 500 the whole batch.
            raise ValueError("client_ts out of supported range")
        # Scoring windows derive [client_ts - minutes, client_ts] — a
        # future-dated instant would slide the whole window past the
        # violations it should have caught (forgery, not clock skew).
        if utc > datetime.now(timezone.utc) + timedelta(seconds=AT_TS_SKEW_SECONDS):
            raise ValueError("client_ts in the future")
        return utc

    @field_validator("payload")
    @classmethod
    def cap_payload_size(cls, v: dict) -> dict:
        # "_"-prefixed keys are server-reserved (e.g. "_outcome"); overwriting
        # client data in the ledger would silently hide it.
        if any(key.startswith("_") for key in v):
            raise ValueError("payload keys starting with '_' are reserved")
        # Cap bytes so a batch can't grow the ledger unboundedly, and reject
        # non-finite floats in unused fields.
        _check_json_blob(v, "payload")
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
    # Allocated + equipped-gear bonus — the stats the engine scores with;
    # the sheet displays these (str_stat etc. stay the allocated pool).
    str_effective: int
    int_effective: int
    con_effective: int
    per_effective: int
    unspent_stat_points: int
    game_class: str | None
    class_unlocked: bool
    auto_allocate: bool
    avatar_config: dict
    xp_today: int
    gold_today: float
    retention: str
    # Stamped like the event/sync responses: profile writes must join the
    # client's server_time-ordered cache merge.
    server_time: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_profile(
        cls,
        profile: GameProfile,
        xp_to_next: int,
        stat_bonus: Mapping[str, int] | None = None,
    ) -> "GameProfileRead":
        # Read only exposed fields — touching server_default columns after a
        # flush would trigger an expired-attribute lazy load (async-unsafe).
        # Daily counters reset inside award_* only; a next-day read must
        # report zero rather than yesterday's earnings.
        now = datetime.now(timezone.utc)
        is_today = profile.totals_day == now.date()
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
            str_effective=effective_stat(profile, "str_stat", stat_bonus),
            int_effective=effective_stat(profile, "int_stat", stat_bonus),
            con_effective=effective_stat(profile, "con_stat", stat_bonus),
            per_effective=effective_stat(profile, "per_stat", stat_bonus),
            unspent_stat_points=profile.unspent_stat_points,
            game_class=profile.game_class,
            class_unlocked=bool(profile.class_unlocked),
            auto_allocate=bool(profile.auto_allocate),
            avatar_config=profile.avatar_config or {},
            xp_today=profile.xp_today if is_today else 0,
            gold_today=profile.gold_today if is_today else 0.0,
            # Column default applies at flush; an unflushed profile reads None.
            retention=profile.retention or "forever",
            # Snapshot-time stamp (set at profile load/lock in
            # get_or_create_profile), not response-build time — a build-time
            # stamp would let a stale read outrank a fresher concurrent write.
            # Falls back to build-time for profiles that bypass the helper.
            server_time=getattr(profile, "_loaded_at", None) or now,
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


class AvatarConfigIn(BaseModel):
    """Replacement avatar_config blob: DiceBear {style, seed, traits, costume}.

    Stored as given — the picker owns the option vocabulary, so the API only
    shapes the envelope (forward-compatible with new DiceBear traits). The
    content allowlist is enforced client-side in src/lib/avatar.ts;
    envelope-only validation here is deliberate.
    """

    avatar_config: dict

    @field_validator("avatar_config")
    @classmethod
    def check_shape(cls, v: dict) -> dict:
        for key in ("style", "seed"):
            if key in v and not isinstance(v[key], str):
                raise ValueError(f"avatar_config.{key} must be a string")
        for key in ("traits", "costume"):
            if key in v:
                if not isinstance(v[key], dict):
                    raise ValueError(f"avatar_config.{key} must be an object")
                # Members are Record<string,string> client-side — a stored
                # array/number/empty member renders nothing and is silently
                # dropped on the next picker save.
                if any(not isinstance(member, str) or not member for member in v[key].values()):
                    raise ValueError(f"avatar_config.{key} members must be non-empty strings")
        # The blob is echoed on every GET /profile — same guard as payloads.
        _check_json_blob(v, "avatar_config")
        return v


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
        if v is not None and v.lower().startswith(SERVER_ID_PREFIX):
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


class SpeedrunIn(BaseModel):
    """Speedrun variant config (mode="speedrun").

    time_boxed runs a fixed countdown against budget_minutes; beat_best is
    an open stopwatch against the activity label's standing record. The
    mode-conditional requirements (budget required for time_boxed, no
    budget on beat_best) are enforced service-side like the timer mode's
    phases requirement — a model_validator would surface 422, not the
    contract's 400.
    """

    kind: Literal["time_boxed", "beat_best"]
    budget_minutes: int | None = Field(default=None, gt=0, le=600)


class SessionStartIn(BaseModel):
    """Open a focus session. mode=stopwatch/speedrun ignores `phases`."""

    mode: Literal["timer", "stopwatch", "speedrun"] = "timer"
    phases: list[SessionPhaseIn] | None = Field(default=None, max_length=32)
    task_id: int | None = None
    tag_id: int | None = None
    activity_label: str | None = Field(default=None, max_length=200)
    difficulty: Literal["trivial", "easy", "medium", "hard"] = "easy"
    auto_start_breaks: bool = True
    auto_start_focus: bool = False
    pause_budget_count: int = Field(default=3, ge=0, le=20)
    pause_budget_seconds: int = Field(default=300, gt=0, le=3600)
    speedrun: SpeedrunIn | None = None
    # Phone-down overlay (#70): gates productive pay on client-reported
    # orientation evidence. Incompatible with speedrun and stopwatch modes —
    # the service layer rejects the combo 400 like the other mode-conditional
    # rules.
    phone_down: bool = False


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
    speedrun: dict | None
    # Phone-down overlay blob (#70): {enabled, spans, violations,
    # penalized_violation_ats, reported_client_event_ids} — None when the
    # overlay was never enabled.
    phone_down: dict | None
    phases: list[SessionPhaseOut]

    @field_validator("phone_down", mode="before")
    @classmethod
    def strip_internal_blob_keys(cls, v: dict | None) -> dict | None:
        # The dedupe belt and charge bookkeeping are server-internal —
        # the client's copy needs only what end cards/history render.
        # Filtered COPY: mutating the ORM blob in place would poison it.
        if isinstance(v, dict):
            return {
                k: x
                for k, x in v.items()
                if k not in ("reported_client_event_ids", "penalized_violation_ats")
            }
        return v


class SessionActionResponse(BaseModel):
    """Session view after evaluation + the applied action, with totals."""

    session: FocusSessionOut
    profile: GameProfileRead | None
    server_time: datetime


# --- Dailies (issue #63) ---------------------------------------------------


class RecurrenceDaily(BaseModel):
    """Every day."""

    kind: Literal["daily"] = "daily"


class RecurrenceWeekdays(BaseModel):
    """Specific weekdays; Python convention 0=Monday .. 6=Sunday."""

    kind: Literal["weekdays"]
    days: list[int] = Field(min_length=1, max_length=7)

    @field_validator("days")
    @classmethod
    def check_days(cls, v: list[int]) -> list[int]:
        if any(not isinstance(d, int) or isinstance(d, bool) or d < 0 or d > 6 for d in v):
            raise ValueError("days must be integers 0 (Mon) .. 6 (Sun)")
        return sorted(set(v))


class RecurrenceEveryNDays(BaseModel):
    """Every N days from an anchor (defaults to the write day server-side)."""

    kind: Literal["every_n_days"]
    interval: int = Field(ge=1, le=365)
    anchor: Optional[date] = None


class RecurrenceTimesPerWeek(BaseModel):
    """C completions per ISO week (Mon–Sun); any day is a check-in day."""

    kind: Literal["times_per_week"]
    count: int = Field(ge=1, le=7)


RecurrenceIn = Annotated[
    RecurrenceDaily | RecurrenceWeekdays | RecurrenceEveryNDays | RecurrenceTimesPerWeek,
    Field(discriminator="kind"),
]


class DailyItemIn(BaseModel):
    """A checklist sub-item; position defaults to list order."""

    title: str = Field(min_length=1, max_length=200)
    position: Optional[int] = Field(None, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str) -> str:
        return _clean_title(v) or v


class DailyIn(BaseModel):
    """A new daily: recurrence + optional checklist + reminder times."""

    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    difficulty: _Difficulty = "easy"
    recurrence: RecurrenceIn = Field(default_factory=RecurrenceDaily)
    items: list[DailyItemIn] = Field(default_factory=list, max_length=30)
    reminder_times: list[str] = Field(default_factory=list, max_length=24)

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


class DailyUpdate(BaseModel):
    """Partial update; streak is engine-owned and never mutable. A provided
    `items` list fully replaces the checklist."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=_TEXT_MAX_LEN)
    difficulty: Optional[_Difficulty] = None
    recurrence: Optional[RecurrenceIn] = None
    items: Optional[list[DailyItemIn]] = Field(None, max_length=30)
    reminder_times: Optional[list[str]] = Field(None, max_length=24)
    active: Optional[bool] = None

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
    def no_null_on_required_fields(self) -> "DailyUpdate":
        for name in ("title", "difficulty", "recurrence", "items", "reminder_times", "active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DailyItemRead(BaseModel):
    id: int
    title: str
    position: int
    done_today: bool = False

    model_config = ConfigDict(from_attributes=True)


class DailyRead(BaseModel):
    """Full daily row plus the checklist and today's completion state."""

    id: int
    title: str
    notes: str | None
    difficulty: str
    recurrence: dict
    streak: int
    active: bool
    reminder_times: list[str]
    items: list[DailyItemRead]
    completed_today: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_rows(
        cls,
        daily,
        items: list,
        done_item_ids: set[int],
        master_done: bool,
    ) -> "DailyRead":
        return cls(
            id=daily.id,
            title=daily.title,
            notes=daily.notes,
            difficulty=daily.difficulty,
            recurrence=daily.recurrence or {},
            streak=daily.streak,
            active=daily.active,
            reminder_times=daily.reminder_times or [],
            items=[
                DailyItemRead(
                    id=item.id,
                    title=item.title,
                    position=item.position,
                    done_today=item.id in done_item_ids,
                )
                for item in items
            ],
            completed_today=master_done,
            created_at=daily.created_at,
            updated_at=daily.updated_at,
        )


class DailyCheckIn(BaseModel):
    """One check on a daily (whole) or a sub-item; check_date backfills for
    offline-queued check-ins and defaults to today (UTC). done=false un-marks
    without clawing back already-paid rewards."""

    daily_item_id: Optional[int] = Field(None, ge=1)
    check_date: Optional[date] = None
    done: bool = True
    client_event_id: Optional[str] = Field(None, min_length=1, max_length=128)

    @field_validator("client_event_id")
    @classmethod
    def no_server_namespace(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.lower().startswith(SERVER_ID_PREFIX):
            raise ValueError("client_event_id prefix 'server:' is reserved")
        return v


class DailyCheckResponse(BaseModel):
    """Post-check daily plus authoritative totals for the HUD."""

    daily: DailyRead
    profile: GameProfileRead
    status: Literal["applied", "duplicate"]
    server_time: datetime


# --- Character sheet (issue #64) ---------------------------------------------


class StatAllocateIn(BaseModel):
    """Manual stat-point spend: {"str": 2, "int": 1} — the sum is debited
    from unspent_stat_points, each stat capped at STAT_POINT_CAP."""

    points: dict[str, Annotated[int, Field(ge=1, le=STAT_POINT_CAP)]] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def known_stats(cls, v: dict[str, int]) -> dict[str, int]:
        for key in v:
            if key not in STAT_KEYS:
                raise ValueError(f"unknown stat '{key}'")
        return v


class CharacterUpdateIn(BaseModel):
    """Character settings; auto_allocate hands level-up points to the
    affinity-based distributor instead of the unspent pool."""

    auto_allocate: bool


class ClassSelectIn(BaseModel):
    """The level-10 class pick; respec re-opens this choice for gold."""

    game_class: Literal["warrior", "mage", "healer", "rogue"]


class GearItemRead(BaseModel):
    """One catalog row merged with the viewer's owned/equipped/costume flags."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    slot: str
    klass: str
    tier: int
    stats: dict
    cost: int
    losable: bool
    owned: bool
    equipped: bool
    costume: bool

    @classmethod
    def from_row(cls, row: dict) -> "GearItemRead":
        item = row["item"]
        return cls(
            key=item.key,
            name=item.name,
            slot=item.slot,
            klass=item.klass,
            tier=item.tier,
            stats=item.stats or {},
            cost=item.cost,
            losable=bool(item.losable),
            owned=row["owned"],
            equipped=row["equipped"],
            costume=row["costume"],
        )


class GearListResponse(BaseModel):
    """Post-mutation catalog plus authoritative totals for the HUD —
    buy/equip change gold/stats, so the profile rides along (sibling of
    HabitClickResponse/DailyCheckResponse)."""

    items: list[GearItemRead]
    profile: GameProfileRead


class GearBuyIn(BaseModel):
    """Buy one catalog item for gold."""

    key: str = Field(min_length=1, max_length=64)


class GearEquipIn(BaseModel):
    """Wear (equipped=true) or remove (false) an owned item; one per slot."""

    key: str = Field(min_length=1, max_length=64)
    equipped: bool = True


class GearCostumeIn(BaseModel):
    """Show (costume=true) or hide (false) an owned item's look; one per
    slot. Visual only — independent of the equipped flag."""

    key: str = Field(min_length=1, max_length=64)
    costume: bool = True


class AchievementRead(BaseModel):
    """One registry row; earned_at is None until the badge is granted."""

    key: str
    name: str
    description: str | None
    gold_reward: int
    earned_at: datetime | None

    @classmethod
    def from_row(cls, row: dict) -> "AchievementRead":
        ach = row["achievement"]
        return cls(
            key=ach.key,
            name=ach.name,
            description=ach.description,
            gold_reward=ach.gold_reward,
            earned_at=row["earned_at"],
        )


# --- Notifications (issue #68) -----------------------------------------------


class QuietHoursIn(BaseModel):
    """The global quiet window: local wall-time bounds in the pref tz.

    `timezone` is the local-time answer until a real user tz lands (#63).
    `start == end` is a degenerate window — it disables quiet hours
    entirely (the gate evaluates never-quiet), not "quiet all day".
    """

    start: str = "22:00"
    end: str = "08:00"
    timezone: str = "UTC"

    # A typo'd key ("timzone") must 422, not silently drop the block.
    model_config = ConfigDict(extra="forbid")

    @field_validator("start", "end")
    @classmethod
    def check_hhmm(cls, v: str) -> str:
        if _REMINDER_TIME_RE.fullmatch(v) is None:
            raise ValueError("quiet hours must be 'HH:MM' 24-hour strings")
        return v

    @field_validator("timezone")
    @classmethod
    def check_iana_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        # OSError: directory-like names ("America") under a packaged tzdata —
        # those are invalid zones too, and must surface as 422 not 500.
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError(f"unknown IANA timezone '{v}'") from None
        return v


class NotificationPrefsIn(BaseModel):
    """Replacement prefs blob: {kind: {in_app, push, email}} + quiet window.

    Kinds are the lowercase game NotificationType values; kinds/channels
    outside the known sets are rejected, and non-bool flags never coerce.
    Unmentioned kinds/channels simply fall back to defaults at dispatch.
    """

    prefs: dict[str, dict[str, StrictBool]] = Field(default_factory=dict)
    quiet_hours: QuietHoursIn = Field(default_factory=QuietHoursIn)

    # A typo'd key ("quite_hours") must 422, not silently drop the block.
    model_config = ConfigDict(extra="forbid")

    @field_validator("prefs")
    @classmethod
    def check_matrix(cls, v: dict[str, dict[str, StrictBool]]) -> dict[str, dict[str, StrictBool]]:
        for kind, channels in v.items():
            if kind not in notification_kinds.KIND_KEYS:
                raise ValueError(f"unknown notification kind '{kind}'")
            for channel in channels:
                if channel not in notification_kinds.CHANNELS:
                    raise ValueError(f"unknown notification channel '{channel}'")
        return v


class NotificationPrefsRead(NotificationPrefsIn):
    """The effective prefs as stored/served — same shape as the write body."""


class DeviceTokenIn(BaseModel):
    """Register (upsert) a push-delivery device token."""

    platform: str = Field(min_length=1, max_length=32)
    token: str = Field(min_length=1, max_length=512)


class DeviceTokenRead(BaseModel):
    id: int
    platform: str
    token: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
