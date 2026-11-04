"""Pydantic contracts for /api/v1/game/activity — the Stats/Activity tab feed.

Separate module from schemas/game.py to keep merge surface zero while
parallel game tickets land (same convention as the router/crud splits).
"""

from datetime import date, datetime

from pydantic import BaseModel


class ActivityDay(BaseModel):
    """One calendar cell of the contribution grid.

    score = focus_minutes + Σ(weight × event count); tier is the intensity
    bucket the client colors — index into ActivityGridResponse.tier_thresholds
    (tier 0 = no activity). `events` is the per-type count map for tooltips.
    """

    date: date
    score: float
    focus_minutes: float
    # Score-eligible per-type counts, NOT raw ledger activity: unscored rows
    # (forged types, failed clicks, lifecycle noise) are excluded, and a
    # weight-0 type can appear while adding 0 to the score.
    events: dict[str, int]
    tier: int


class ActivityGridResponse(BaseModel):
    """The filled grid: one row per UTC day in [start, end], empty days
    included (tier 0) so the client never fills gaps itself."""

    start: date
    end: date
    days: list[ActivityDay]
    # Sorted score cutoffs: tier n applies when score >= tier_thresholds[n-1].
    tier_thresholds: list[float]
    server_time: datetime


class ActivityBestDay(BaseModel):
    date: date
    score: float


class SpeedrunPB(BaseModel):
    """One activity label's standing beat-your-best record (all-time).

    set_at is when the current record was set — records strictly improve,
    so the earliest completed run at the best time owns it.
    """

    activity_label: str
    best_seconds: int
    attempts: int
    set_at: datetime


class ActivityStatsResponse(BaseModel):
    """The profile stat set, computed over the same window convention as the
    grid (defaults: trailing 365 UTC days). Streaks count consecutive days
    with score > 0; a scoreless today can't break the current one."""

    start: date
    end: date
    avg_hours_per_day: float
    total_hours: float
    current_streak: int
    longest_streak: int
    best_day: ActivityBestDay | None
    # Score sum over the 7 days ending at server-today, clipped to the
    # window — a window ending earlier legitimately reads lower.
    weekly_total: float
    # All-time per-label records (not window-scoped): the stats window
    # bounds streaks/hours, but a PB is a PB whenever it was set.
    speedrun_pbs: list[SpeedrunPB]
    server_time: datetime
