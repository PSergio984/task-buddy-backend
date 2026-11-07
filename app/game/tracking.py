"""Activity-tracking rules: day scores, intensity tiers, and profile stats.

Pure math over pre-aggregated rows (no DB access): the CRUD layer buckets
ledger events and focus phases per UTC day, and this module turns those
buckets into the contribution-grid series and the profile stat set.

Day score = focus minutes + Σ(event weight × count). Tunables come from the
"activity_weights" row of tbl_game_config — a JSONB value shaped like:

    {
        "weights": {"habit_click": 2, ...},
        "tier_thresholds": [1, 15, 35, 60]
    }

"weights" merges over the defaults (a partial override can't orphan types;
set a weight to 0 to mute a type); "tier_thresholds" replaces the default
ladder wholesale when it's a strictly-increasing list of positive numbers.
A missing/invalid row falls back to the code defaults below — no seed
migration is required.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game_tracking as tracking_crud

# Default per-type points. Only positive-activity types score: a day with
# nothing but lifecycle rows (session_started, phase_*) or failures stays 0.
# focus_phase_completed is deliberately 0 — its minutes already land in
# focus_minutes (phase rows for server-run sessions, payload.minutes for
# offline-synced client events), so a weight would double-count.
# damage/session_abandoned score 0: showing up counts only when it lands.
DEFAULT_WEIGHTS: dict[str, float] = {
    "focus_phase_completed": 0.0,
    "habit_click": 2.0,
    # Live since #63: daily_service.score_check emits scored daily_check
    # rows. Any future emitter MUST stamp _outcome.scored=True or the row
    # is filtered before weighting.
    "daily_check": 3.0,
    "stopwatch_milestone": 1.0,
    "damage": 0.0,
    "session_abandoned": 0.0,
    # speedrun_completed/failed weigh 0: the run's minutes already land in
    # focus_minutes via the completed phase row (same no-double-count rule
    # as focus_phase_completed). record_set scores like a milestone.
    "speedrun_completed": 0.0,
    "speedrun_failed": 0.0,
    "record_set": 1.0,
    # Phone-down markers (#70) carry no score: they're lifecycle evidence,
    # not activity — the phase's minutes already land in focus_minutes.
    "phone_down_span": 0.0,
    "phone_down_violation": 0.0,
}

# Score cutoffs for tiers 1..4 (tier 0 = no activity). 5 intensities like
# GitHub's grid. Defaults assume ~25-50 focus min is a normal day (tier 2)
# and 60+ a big one (tier 4).
DEFAULT_TIER_THRESHOLDS: tuple[float, ...] = (1.0, 15.0, 35.0, 60.0)

# Hard cap on the inclusive [start, end] span — bounds the filled day rows.
MAX_RANGE_DAYS = 366
DEFAULT_WINDOW_DAYS = 365


def _finite_nonneg(value: Any) -> float | None:
    """Numeric config guard mirroring GameRates.from_dict rules."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


@dataclass(frozen=True)
class ActivityRates:
    """Resolved weights + tier ladder; the activity_weights row overrides."""

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    tier_thresholds: tuple[float, ...] = DEFAULT_TIER_THRESHOLDS

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActivityRates":
        if not data:
            return cls()
        rates = cls()
        raw_weights = data.get("weights")
        if isinstance(raw_weights, Mapping):
            merged = dict(rates.weights)
            for name, value in raw_weights.items():
                clean = _finite_nonneg(value)
                if clean is not None:
                    merged[str(name)] = clean
            # Pinned: this type's contribution is its minutes (phase rows +
            # client payload), never a per-event weight — a config override
            # would silently reintroduce the double-count.
            merged["focus_phase_completed"] = 0.0
            # Same double-count hazard: completed speedrun phases already
            # feed focus_minutes ("speedrun" joined the CRUD focus kinds).
            # speedrun_failed needs no pin — failed runs leave no completed
            # phase, so a weight there scores nothing twice.
            merged["speedrun_completed"] = 0.0
            # Phone-down marker rows are evidence, not activity — a config
            # override can't give a span report or a violation a day-score.
            merged["phone_down_span"] = 0.0
            merged["phone_down_violation"] = 0.0
            rates = cls(weights=merged, tier_thresholds=rates.tier_thresholds)
        raw_tiers = data.get("tier_thresholds")
        if isinstance(raw_tiers, (list, tuple)) and 1 <= len(raw_tiers) <= 8:
            cleaned: list[float] = []
            valid = True
            for v in raw_tiers:
                c = _finite_nonneg(v)
                if c is None or c <= 0:
                    valid = False
                    break
                cleaned.append(c)
            if valid and len(set(cleaned)) == len(cleaned) and cleaned == sorted(cleaned):
                rates = cls(weights=rates.weights, tier_thresholds=tuple(cleaned))
        return rates


async def load_rates(db: AsyncSession) -> ActivityRates:
    """Read the activity_weights config row; absent -> code defaults."""
    return ActivityRates.from_dict(await tracking_crud.get_activity_config(db))


def tier_for(score: float, tier_thresholds: tuple[float, ...]) -> int:
    """0..len(thresholds): count of thresholds the score reaches."""
    return sum(1 for t in tier_thresholds if score >= t)


def day_score(focus_minutes: float, event_counts: Mapping[str, int], rates: ActivityRates) -> float:
    """focus minutes + Σ(weight × count); unknown types weigh 0."""
    return focus_minutes + sum(
        rates.weights.get(event_type, 0.0) * count for event_type, count in event_counts.items()
    )


def build_days(
    start: date,
    end: date,
    focus_minutes_by_day: Mapping[date, float],
    event_counts_by_day: Mapping[date, Mapping[str, int]],
    rates: ActivityRates,
) -> list[dict]:
    """One filled row per calendar day in [start, end] — the grid needs empty
    days rendered as tier-0 cells, so the server emits them rather than
    leaving the client to fill. `events` carries only score-eligible counts
    (the CRUD layer already filters unscored rows — it is not raw ledger
    activity)."""
    days = []
    day = start
    while day <= end:
        minutes = focus_minutes_by_day.get(day, 0.0)
        counts = dict(event_counts_by_day.get(day, {}))
        # Tier tests the SAME rounded score the row ships — a client
        # recomputing tier from score+thresholds must get this tier.
        score = round(day_score(minutes, counts, rates), 2)
        days.append(
            {
                "date": day,
                "score": score,
                "focus_minutes": round(minutes, 2),
                "events": counts,
                "tier": tier_for(score, rates.tier_thresholds),
            }
        )
        day += timedelta(days=1)
    return days


def _streaks(days: list[dict], today: date) -> tuple[int, int]:
    """(current, longest) streaks of consecutive days with score > 0.

    Current streak is anchored at the window's last day; when that day is
    today and still scoreless it's skipped — the day isn't over, so the
    streak can't be called broken yet.
    """
    longest = 0
    run = 0
    for row in days:
        if row["score"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    current = 0
    i = len(days) - 1
    if i >= 0 and days[i]["date"] == today and days[i]["score"] <= 0:
        i -= 1
    while i >= 0 and days[i]["score"] > 0:
        current += 1
        i -= 1
    return current, longest


def summarize(days: list[dict], today: date, speedrun_pbs: list[dict] | None = None) -> dict:
    """The profile stat set over the window's day rows.

    avg_hours_per_day divides by window length (zero days count — it's the
    honest daily rate). weekly_total covers the 7 days ending at
    server-today clipped to the window — a window ending earlier legitimately
    reads lower. best_day is the highest-score day, earliest on ties.
    speedrun_pbs is caller-fetched: records are all-time, not window-scoped
    (the PB board can't live inside the day-row aggregation).
    """
    total_minutes = sum(row["focus_minutes"] for row in days)
    total_hours = total_minutes / 60.0
    current, longest = _streaks(days, today)
    scored = [row for row in days if row["score"] > 0]
    best = max(scored, key=lambda row: (row["score"], -row["date"].toordinal()), default=None)
    week_floor = today - timedelta(days=6)
    weekly_total = sum(row["score"] for row in days if row["date"] >= week_floor)
    return {
        "avg_hours_per_day": round(total_hours / len(days), 2) if days else 0.0,
        "total_hours": round(total_hours, 2),
        "current_streak": current,
        "longest_streak": longest,
        "best_day": ({"date": best["date"], "score": best["score"]} if best is not None else None),
        "weekly_total": round(weekly_total, 2),
        "speedrun_pbs": speedrun_pbs or [],
    }
