"""Scoring engine: the single owner of all game-economy rules.

Pure functions over a GameProfile instance — no DB access, so the combinatorial
rules (curve, crits, shields, drift, death cascade, caps) are unit-testable
directly. Every award/loss in the game flows through here; all tunables come
from a GameRates loaded out of game_config, never hardcoded constants.

Formulas verified against Habitica's common scoring code, see
research/habitica-formulas.md (wayfinder #49 research).
"""

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from app.models.game import GameProfile

_ALLOCATED_STATS = ("str_stat", "int_stat", "con_stat", "per_stat")
_death_rng = random.Random()

# Config fields used as divisors or multiplicands — non-positive/non-finite
# overrides would crash or loop, so from_dict drops them back to defaults.
_POSITIVE_FIELDS = frozenset(
    {
        "con_shield_divisor",
        "crit_str_chance_scale",
        "crit_mult_soft",
        "lvl_curve_round",
        "lvl_curve_early",
        "lvl_curve_lvl5",
        "habit_drift_base",
    }
)

# Fields that must stay integral: daily_xp_cap feeds an Integer column, and
# lvl_curve_round is a bucket size — int(0.5) would collapse the level curve.
_INT_FIELDS = frozenset({"daily_xp_cap", "lvl_curve_round"})


@dataclass(frozen=True)
class GameRates:
    """Economy tunables; the "economy" row of game_config overrides defaults."""

    xp_per_minute: float = 1.0
    gold_per_minute: float = 0.2
    int_xp_pct: float = 0.025  # +2.5% XP per INT point
    per_gold_pct: float = 0.02  # +2% gold per PER point
    con_shield_divisor: float = 250.0  # shield = 1 - CON/divisor
    con_shield_floor: float = 0.1  # shield never drops below this
    crit_base_chance: float = 0.03
    crit_str_chance_scale: float = 100.0  # chance = base * (1 + STR/scale)
    crit_mult_base: float = 1.5
    crit_mult_span: float = 4.0  # mult = base + span*STR/(STR+soft)
    crit_mult_soft: float = 200.0
    hp_loss_base: float = 2.0  # damage = base * difficulty_mult * shield
    habit_drift_base: float = 0.9747
    habit_value_min: float = -47.27
    habit_value_max: float = 21.27
    habit_xp_factor: float = 6.0  # XP = delta * P * crit * INT-bonus * factor
    daily_xp_cap: int = 500
    daily_gold_cap: float = 150.0
    stopwatch_milestone_xp: float = 25.0  # XP per 25/50/75-min stopwatch chunk
    # Level curve: 25*lvl below 5, fixed 150 at 5, quadratic afterwards.
    lvl_curve_early: float = 25.0
    lvl_curve_lvl5: float = 150.0
    lvl_curve_quad_a: float = 0.25
    lvl_curve_quad_b: float = 10.0
    lvl_curve_quad_c: float = 139.75
    lvl_curve_round: float = 10.0
    crit_mult_max: float = 3.0  # spec band: crits land ~1.5-3x
    difficulty: dict[str, float] = field(
        default_factory=lambda: {"trivial": 0.1, "easy": 1.0, "medium": 1.5, "hard": 2.0}
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GameRates":
        if not data:
            return cls()
        known = set(cls.__dataclass_fields__)
        kwargs: dict[str, Any] = {}
        for key, v in data.items():
            if key not in known:
                continue
            if key == "difficulty":
                if isinstance(v, Mapping):
                    # Multipliers must stay finite and positive — a negative
                    # difficulty would invert rewards. Merge over defaults so
                    # a partial override can't orphan fallback names.
                    clean = {
                        str(name): float(mult)
                        for name, mult in v.items()
                        if isinstance(mult, (int, float))
                        and not isinstance(mult, bool)
                        and math.isfinite(mult)
                        and mult > 0
                    }
                    if clean:
                        kwargs[key] = {**cls().difficulty, **clean}
                continue
            if (
                not isinstance(v, (int, float))
                or isinstance(v, bool)
                or not math.isfinite(v)
                or (key in _POSITIVE_FIELDS and v <= 0)
                or (key in _INT_FIELDS and not float(v).is_integer())
            ):
                continue
            kwargs[key] = int(v) if key in _INT_FIELDS else v
        return cls(**kwargs)


def xp_to_next_level(level: int, rates: GameRates) -> int:
    """Habitica's toNextLevel: 25*lvl early, 150 at 5, quadratic afterwards.

    Floored at 1: a misconfigured curve can't yield a non-positive threshold,
    which would make award_xp's level-up loop non-terminating.
    """
    if level < 5:
        return max(1, int(rates.lvl_curve_early * level))
    if level == 5:
        return max(1, int(rates.lvl_curve_lvl5))
    quadratic = (
        level**2 * rates.lvl_curve_quad_a + level * rates.lvl_curve_quad_b + rates.lvl_curve_quad_c
    )
    return max(1, round(quadratic / rates.lvl_curve_round) * int(rates.lvl_curve_round))


def crit_roll(roll: float, str_stat: int, rates: GameRates) -> float:
    """Return the crit multiplier for a uniform roll in [0, 1); 1.0 = no crit."""
    chance = rates.crit_base_chance * (1 + str_stat / rates.crit_str_chance_scale)
    if roll < chance:
        mult = rates.crit_mult_base + rates.crit_mult_span * str_stat / (
            str_stat + rates.crit_mult_soft
        )
        return min(mult, rates.crit_mult_max)
    return 1.0


def habit_delta(value: float, rates: GameRates) -> float:
    """Per-click value drift step: 0.9747^V — shrinks as V rises."""
    return float(rates.habit_drift_base**value)


def clamp_habit_value(value: float, rates: GameRates) -> float:
    return max(rates.habit_value_min, min(rates.habit_value_max, value))


def _difficulty_mult(name: Any, rates: GameRates) -> float:
    try:
        return rates.difficulty[str(name)]
    except KeyError:
        raise ValueError(f"unknown difficulty: {name}") from None


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _sync_today(profile: GameProfile, today: date) -> None:
    if profile.totals_day != today:
        profile.totals_day = today
        profile.xp_today = 0
        profile.gold_today = 0.0


def award_xp(profile: GameProfile, amount: int, rates: GameRates, today: date) -> dict:
    """Apply XP under the daily cap; resolves level-ups (carry, HP refill, stat point)."""
    _sync_today(profile, today)
    applied = max(0, min(amount, rates.daily_xp_cap - profile.xp_today))
    profile.xp += applied
    profile.xp_today += applied
    levels_gained = 0
    while profile.xp >= xp_to_next_level(profile.level, rates):
        profile.xp -= xp_to_next_level(profile.level, rates)
        profile.level += 1
        levels_gained += 1
        profile.hp = profile.max_hp  # level-up refills HP
        profile.unspent_stat_points += 1
    return {"xp": applied, "levels_gained": levels_gained}


def award_gold(profile: GameProfile, amount: float, rates: GameRates, today: date) -> dict:
    """Apply gold under the daily cap."""
    _sync_today(profile, today)
    applied = max(0.0, min(amount, rates.daily_gold_cap - profile.gold_today))
    profile.gold += applied
    profile.gold_today += applied
    return {"gold": applied}


def _death(profile: GameProfile, rates: GameRates, rng: random.Random | None) -> dict:
    """Habitica revive cascade: XP/gold to 0, level -1 (floor 1), -1 allocated
    stat point, and one losable gear item (resolved by the caller once gear
    exists — flagged in the outcome)."""
    profile.level = max(1, profile.level - 1)
    profile.xp = 0
    profile.gold = 0.0
    profile.hp = profile.max_hp
    allocated = [s for s in _ALLOCATED_STATS if getattr(profile, s) > 0]
    stat_lost = None
    if allocated:
        picker = rng if rng is not None else _death_rng
        stat_lost = picker.choice(allocated)
        setattr(profile, stat_lost, getattr(profile, stat_lost) - 1)
    # gear_lost stays False until the gear resolver lands with the character ticket.
    return {"died": True, "stat_lost": stat_lost, "gear_lost": False}


def apply_hp_loss(
    profile: GameProfile,
    amount: float,
    rates: GameRates,
    rng: random.Random | None = None,
) -> dict:
    """Reduce HP by max(1, floor(amount * CON-shield)); triggers death at 0."""
    shield = max(rates.con_shield_floor, 1 - profile.con_stat / rates.con_shield_divisor)
    loss = max(1.0, float(math.floor(amount * shield)))
    profile.hp -= loss
    outcome: dict = {"hp_lost": loss, "died": False}
    if profile.hp <= 0:
        outcome.update(_death(profile, rates, rng))
    return outcome


def _finite_positive(value: Any, name: str) -> float:
    """Guards JSON numbers: rejects non-numeric, bool, inf/NaN, and
    overflow-sized magnitudes (1e308 passes isfinite but explodes downstream)."""
    # Bounds before isfinite: giant JSON ints (10**400) raise OverflowError
    # inside isfinite's int->float conversion, escaping the ValueError path.
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > 1e6
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number in (0, 1e6]")
    return float(value)


def _apply_focus_phase(
    profile: GameProfile, payload: dict, rates: GameRates, rng_roll: float, today: date
) -> dict:
    minutes = _finite_positive(payload.get("minutes"), "focus_phase_completed minutes")
    p = _difficulty_mult(payload.get("difficulty", "easy"), rates)
    mult = crit_roll(rng_roll, profile.str_stat, rates)
    xp = _round_half_up(
        minutes * rates.xp_per_minute * p * (1 + rates.int_xp_pct * profile.int_stat) * mult
    )
    gold = math.ceil(
        minutes * rates.gold_per_minute * p * (1 + rates.per_gold_pct * profile.per_stat) * mult
    )
    outcome: dict = {"scored": True, "crit": mult > 1.0}
    outcome.update(award_xp(profile, xp, rates, today))
    outcome.update(award_gold(profile, gold, rates, today))
    return outcome


def _apply_habit_click(
    profile: GameProfile,
    payload: dict,
    rates: GameRates,
    rng_roll: float,
    rng: random.Random | None,
    today: date,
) -> dict:
    direction = payload.get("direction")
    if direction not in ("positive", "negative"):
        raise ValueError("habit_click requires direction 'positive' or 'negative'")
    value = payload.get("value", 0.0)
    # Bounds before isfinite: giant JSON ints overflow int->float inside it.
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or abs(value) > 1e6
        or not math.isfinite(value)
    ):
        raise ValueError("habit_click value must be a finite number")
    # Clamp first: extremes would explode 0.9747**V and inflate rewards.
    # shortcut: value is client-claimed until #62 persists Habit.value —
    # bounded to 3.36x neutral reward by the clamp; upgrade when habits
    # land and score from stored state.
    value = clamp_habit_value(float(value), rates)
    delta = habit_delta(value, rates)
    p = _difficulty_mult(payload.get("difficulty", "easy"), rates)
    if direction == "negative":
        # Negative clicks only cost HP — never XP or gold.
        base = delta * p * rates.hp_loss_base
        outcome = apply_hp_loss(profile, base, rates, rng)
        outcome.update(
            {"scored": True, "delta": -delta, "new_value": clamp_habit_value(value - delta, rates)}
        )
        return outcome
    mult = crit_roll(rng_roll, profile.str_stat, rates)
    xp = _round_half_up(
        delta * (1 + rates.int_xp_pct * profile.int_stat) * p * mult * rates.habit_xp_factor
    )
    gold = math.ceil(delta * p * mult * (1 + rates.per_gold_pct * profile.per_stat))
    outcome = {
        "scored": True,
        "crit": mult > 1.0,
        "delta": delta,
        "new_value": clamp_habit_value(value + delta, rates),
    }
    outcome.update(award_xp(profile, xp, rates, today))
    outcome.update(award_gold(profile, gold, rates, today))
    return outcome


def _apply_damage(
    profile: GameProfile, payload: dict, rates: GameRates, rng: random.Random | None
) -> dict:
    if "amount" in payload:
        base = _finite_positive(payload["amount"], "damage amount")
    else:
        base = rates.hp_loss_base * _difficulty_mult(payload.get("difficulty", "easy"), rates)
    outcome = apply_hp_loss(profile, base, rates, rng)
    outcome["scored"] = True
    return outcome


def _apply_stopwatch_milestone(
    profile: GameProfile,
    payload: dict,
    rates: GameRates,
    rng_roll: float,
    rng: random.Random | None,
    today: date,
) -> dict:
    """One fixed XP chunk per milestone crossed (25/50/75 min), claimed on
    stop — no per-minute accrual, so marathons can't farm."""
    milestones = payload.get("milestones", 1)
    if (
        not isinstance(milestones, int)
        or isinstance(milestones, bool)
        or milestones < 1
        or milestones > 100
    ):
        raise ValueError("stopwatch_milestone requires integer milestones in [1, 100]")
    mult = crit_roll(rng_roll, profile.str_stat, rates)
    xp = _round_half_up(milestones * rates.stopwatch_milestone_xp * mult)
    outcome = {"scored": True, "type": "stopwatch_milestone", "crit": mult > 1.0}
    outcome.update(award_xp(profile, xp, rates, today))
    return outcome


def apply_event(
    profile: GameProfile,
    event_type: str,
    payload: dict,
    rates: GameRates,
    rng_roll: float = 1.0,
    rng: random.Random | None = None,
    today: date | None = None,
) -> dict:
    """Score one event against the profile.

    rng_roll is the caller's uniform [0,1) draw used for crit resolution —
    injectable so scoring is deterministic in tests. rng drives the death
    cascade's stat pick (same idea, seedable). today is the UTC day used for
    daily-cap bookkeeping; one value per event so a midnight-straddling award
    can't split xp/gold across two day counters. Event types without a scoring
    rule are stored in the ledger but move no totals (later build tickets
    register their own types here).
    """
    day = today or datetime.now(timezone.utc).date()
    if event_type == "focus_phase_completed":
        return _apply_focus_phase(profile, payload, rates, rng_roll, day)
    if event_type == "habit_click":
        return _apply_habit_click(profile, payload, rates, rng_roll, rng, day)
    if event_type == "damage":
        return _apply_damage(profile, payload, rates, rng)
    if event_type == "session_abandoned":
        # Abandon reasons carry the session's difficulty for HP scaling.
        return _apply_damage(profile, payload, rates, rng)
    if event_type == "stopwatch_milestone":
        return _apply_stopwatch_milestone(profile, payload, rates, rng_roll, rng, day)
    return {"scored": False}
