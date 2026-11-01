"""Unit tests for the game scoring engine (pure logic, no DB session needed)."""

import math
import random
from datetime import date

import pytest

from app.game.engine import (
    GameRates,
    apply_event,
    apply_hp_loss,
    award_gold,
    award_xp,
    clamp_habit_value,
    crit_roll,
    habit_delta,
    xp_to_next_level,
)
from app.models.game import GameProfile


def make_profile(**kwargs) -> GameProfile:
    """Detached ORM instance: no session needed, engine mutates it in memory."""
    defaults = {
        "user_id": 1,
        "level": 3,
        "xp": 0,
        "hp": 50.0,
        "max_hp": 50.0,
        "gold": 0.0,
        "str_stat": 0,
        "int_stat": 0,
        "con_stat": 0,
        "per_stat": 0,
        "unspent_stat_points": 0,
        "xp_today": 0,
        "gold_today": 0.0,
        "totals_day": date.today(),
    }
    defaults.update(kwargs)
    return GameProfile(**defaults)


@pytest.fixture()
def rates() -> GameRates:
    return GameRates()


class TestLevelCurve:
    def test_linear_early_levels(self, rates: GameRates) -> None:
        assert xp_to_next_level(1, rates) == 25
        assert xp_to_next_level(4, rates) == 100

    def test_level_five_hardcoded(self, rates: GameRates) -> None:
        assert xp_to_next_level(5, rates) == 150

    def test_quadratic_later_levels(self, rates: GameRates) -> None:
        # 0.25*36 + 60 + 139.75 = 208.75 -> 210
        assert xp_to_next_level(6, rates) == 210
        # 0.25*100 + 100 + 139.75 = 264.75 -> 260
        assert xp_to_next_level(10, rates) == 260

    def test_curve_monotonic(self, rates: GameRates) -> None:
        values = [xp_to_next_level(level, rates) for level in range(1, 60)]
        assert all(a <= b for a, b in zip(values, values[1:], strict=False))

    def test_curve_comes_from_rates(self) -> None:
        # Rates are tunable via game_config — the curve must not be a constant.
        tuned = GameRates.from_dict({"lvl_curve_early": 40.0, "lvl_curve_lvl5": 200.0})
        assert xp_to_next_level(1, tuned) == 40
        assert xp_to_next_level(5, tuned) == 200


class TestCrit:
    def test_no_crit_returns_one(self, rates: GameRates) -> None:
        # base chance 3%: a roll of 0.5 can never crit at any STR
        assert crit_roll(0.5, str_stat=200, rates=rates) == 1.0

    def test_crit_base_str(self, rates: GameRates) -> None:
        assert crit_roll(0.01, str_stat=0, rates=rates) == pytest.approx(1.5)

    def test_crit_scales_with_str(self, rates: GameRates) -> None:
        # chance = 0.03 * (1 + 100/100) = 0.06; mult = 1.5 + 400/300
        assert crit_roll(0.05, str_stat=100, rates=rates) == pytest.approx(1.5 + 4 / 3)
        assert crit_roll(0.07, str_stat=100, rates=rates) == 1.0

    def test_crit_multiplier_asymptote(self, rates: GameRates) -> None:
        # 1.5 + 4*s/(s+200) rises with STR but the spec caps the band at ~3x
        assert crit_roll(0.0, str_stat=9999, rates=rates) <= 3.0


class TestHabitDrift:
    def test_delta_at_neutral(self, rates: GameRates) -> None:
        assert habit_delta(0.0, rates) == pytest.approx(1.0)

    def test_delta_shrinks_at_high_value(self, rates: GameRates) -> None:
        assert habit_delta(21.27, rates) < habit_delta(0.0, rates)

    def test_clamp_bounds(self, rates: GameRates) -> None:
        assert clamp_habit_value(50.0, rates) == pytest.approx(21.27)
        assert clamp_habit_value(-50.0, rates) == pytest.approx(-47.27)
        assert clamp_habit_value(3.0, rates) == pytest.approx(3.0)


class TestAwardXp:
    def test_level_up_carry_and_refill(self, rates: GameRates) -> None:
        profile = make_profile(level=1, xp=0, hp=10.0)
        outcome = award_xp(profile, 30, rates, date.today())
        assert profile.level == 2
        assert profile.xp == 5  # 30 - 25 threshold carries over
        assert profile.hp == profile.max_hp  # level-up refills HP
        assert profile.unspent_stat_points == 1
        assert outcome["levels_gained"] == 1

    def test_multiple_level_ups(self, rates: GameRates) -> None:
        profile = make_profile(level=1, xp=0)
        outcome = award_xp(profile, 160, rates, date.today())
        # 25 + 50 + 75 = 150 -> level 4, 10 carried
        assert profile.level == 4
        assert profile.xp == 10
        assert outcome["levels_gained"] == 3

    def test_daily_cap_clamps_award(self, rates: GameRates) -> None:
        profile = make_profile(level=10, xp=0, xp_today=490)
        award_xp(profile, 50, rates, date.today())
        assert profile.xp_today == 500  # capped at 500/day
        # only 10 XP actually landed, no level-up (threshold is 260 at L10)
        assert profile.xp == 10

    def test_daily_counters_reset_next_day(self, rates: GameRates) -> None:
        profile = make_profile(xp_today=500, gold_today=150.0, totals_day=date(2020, 1, 1))
        award_xp(profile, 10, rates, date.today())
        assert profile.xp_today == 10
        assert profile.totals_day == date.today()


class TestAwardGold:
    def test_simple_gain(self, rates: GameRates) -> None:
        profile = make_profile()
        award_gold(profile, 12.5, rates, date.today())
        assert profile.gold == pytest.approx(12.5)

    def test_daily_gold_cap(self, rates: GameRates) -> None:
        profile = make_profile(gold_today=149.0)
        award_gold(profile, 50.0, rates, date.today())
        assert profile.gold == pytest.approx(1.0)
        assert profile.gold_today == pytest.approx(150.0)


class TestDamage:
    def test_difficulty_scaling(self, rates: GameRates) -> None:
        profile = make_profile()
        # hpMod = -1 * P * 2 * shield; easy -> -2, medium -> -3, hard -> -4
        apply_hp_loss(profile, 2.0, rates)
        assert profile.hp == pytest.approx(48.0)

    def test_minimum_one_hp_loss(self, rates: GameRates) -> None:
        profile = make_profile()
        apply_hp_loss(profile, 0.05, rates)
        assert profile.hp == pytest.approx(49.0)

    def test_con_shield_floor(self, rates: GameRates) -> None:
        profile = make_profile(con_stat=250)
        # shield = max(0.1, 1 - 250/250) = 0.1 -> loss 2 * 0.1 = 0.2 -> min 1
        apply_hp_loss(profile, 2.0, rates)
        assert profile.hp == pytest.approx(49.0)

    def test_con_shield_partial(self, rates: GameRates) -> None:
        profile = make_profile(con_stat=125)
        # shield = 0.5 -> loss 4 * 0.5 = 2
        apply_hp_loss(profile, 4.0, rates)
        assert profile.hp == pytest.approx(48.0)


class TestDeathCascade:
    def test_death_penalties(self, rates: GameRates) -> None:
        profile = make_profile(level=8, xp=100, gold=55.0, hp=1.0, str_stat=5)
        apply_hp_loss(profile, 10.0, rates)
        assert profile.hp == profile.max_hp  # revived
        assert profile.xp == 0
        assert profile.gold == 0
        assert profile.level == 7
        assert profile.str_stat == 4  # one allocated point lost

    def test_level_floor(self, rates: GameRates) -> None:
        profile = make_profile(level=1, hp=1.0)
        apply_hp_loss(profile, 50.0, rates)
        assert profile.level == 1

    def test_death_picks_only_allocated_stat(self, rates: GameRates) -> None:
        profile = make_profile(level=8, hp=1.0, int_stat=3, str_stat=0, per_stat=0, con_stat=0)
        apply_hp_loss(profile, 10.0, rates)
        assert profile.int_stat == 2  # only allocated stat could be lost

    def test_death_rng_is_seeded_deterministic(self, rates: GameRates) -> None:
        # Two allocated stats -> the stat lost depends on the injected RNG draw.
        results = set()
        for seed in range(20):
            profile = make_profile(level=8, hp=1.0, int_stat=3, str_stat=3)
            outcome = apply_hp_loss(profile, 10.0, rates, rng=random.Random(seed))
            results.add(outcome["stat_lost"])
            assert (profile.int_stat, profile.str_stat) in {(2, 3), (3, 2)}
        assert results == {"int_stat", "str_stat"}  # both picks reachable

    def test_death_reports_no_gear_lost_yet(self, rates: GameRates) -> None:
        # The gear resolver lands in a later ticket; until then nothing is lost.
        profile = make_profile(level=8, hp=1.0)
        outcome = apply_hp_loss(profile, 10.0, rates, rng=random.Random(0))
        assert outcome["died"] is True
        assert outcome["gear_lost"] is False


class TestApplyEvent:
    def test_focus_phase_scores_xp_and_gold(self, rates: GameRates) -> None:
        profile = make_profile()
        outcome = apply_event(
            profile,
            "focus_phase_completed",
            {"minutes": 25, "difficulty": "easy"},
            rates,
            rng_roll=1.0,
        )
        # xp = 25 * 1.0/min * P(1) * INT(1) * crit(1) = 25 (< 75 threshold, no level-up)
        assert profile.xp == 25
        assert profile.gold == pytest.approx(5.0)
        assert outcome["scored"] is True

    def test_focus_phase_int_bonus(self, rates: GameRates) -> None:
        profile = make_profile(int_stat=40, level=50)
        apply_event(
            profile,
            "focus_phase_completed",
            {"minutes": 10, "difficulty": "easy"},
            rates,
            rng_roll=1.0,
        )
        # xp = 10 * (1 + 0.025*40) = 20
        assert profile.xp == 20

    def test_focus_phase_difficulty_multiplier(self, rates: GameRates) -> None:
        profile = make_profile(level=50)
        apply_event(
            profile,
            "focus_phase_completed",
            {"minutes": 10, "difficulty": "hard"},
            rates,
            rng_roll=1.0,
        )
        assert profile.xp == 20

    def test_habit_click_positive_scores(self, rates: GameRates) -> None:
        profile = make_profile(level=50)
        outcome = apply_event(
            profile,
            "habit_click",
            {"direction": "positive", "difficulty": "easy", "value": 0.0},
            rates,
            rng_roll=1.0,
        )
        # delta = 0.9747^0 = 1 -> xp = round(1 * 1 * 1 * 1 * 6) = 6, gold = ceil(1) = 1
        assert profile.xp == 6
        assert profile.gold == pytest.approx(1.0)
        assert outcome["delta"] == pytest.approx(1.0)

    def test_habit_click_negative_damages_only(self, rates: GameRates) -> None:
        profile = make_profile()
        apply_event(
            profile,
            "habit_click",
            {"direction": "negative", "difficulty": "easy", "value": 0.0},
            rates,
            rng_roll=1.0,
        )
        assert profile.hp == pytest.approx(48.0)  # -2 at easy, CON 0
        assert profile.xp == 0
        assert profile.gold == 0

    def test_damage_event_amount(self, rates: GameRates) -> None:
        profile = make_profile()
        apply_event(profile, "damage", {"amount": 4}, rates, rng_roll=1.0)
        assert profile.hp == pytest.approx(46.0)

    def test_damage_event_difficulty(self, rates: GameRates) -> None:
        profile = make_profile()
        apply_event(profile, "damage", {"difficulty": "hard"}, rates, rng_roll=1.0)
        assert profile.hp == pytest.approx(46.0)  # 2 * P(2) = 4

    def test_unknown_event_not_scored(self, rates: GameRates) -> None:
        profile = make_profile()
        outcome = apply_event(profile, "speedrun_started", {"label": "5k"}, rates, rng_roll=1.0)
        assert outcome["scored"] is False
        assert profile.xp == 0
        assert profile.hp == pytest.approx(50.0)

    def test_invalid_payload_raises(self, rates: GameRates) -> None:
        profile = make_profile()
        with pytest.raises(ValueError):
            apply_event(profile, "focus_phase_completed", {"minutes": -5}, rates, rng_roll=1.0)

    def test_invalid_difficulty_raises(self, rates: GameRates) -> None:
        profile = make_profile()
        with pytest.raises(ValueError):
            apply_event(
                profile,
                "focus_phase_completed",
                {"minutes": 25, "difficulty": "impossible"},
                rates,
                rng_roll=1.0,
            )

    def test_non_finite_minutes_raises(self, rates: GameRates) -> None:
        # JSON "Infinity" parses to float inf; must 400, not 500 on floor(inf).
        profile = make_profile()
        for bad in (float("inf"), float("-inf"), float("nan")):
            with pytest.raises(ValueError):
                apply_event(
                    profile,
                    "focus_phase_completed",
                    {"minutes": bad},
                    rates,
                    rng_roll=1.0,
                )

    def test_huge_finite_minutes_raises(self, rates: GameRates) -> None:
        # 1e308 passes isfinite but overflows to inf inside the award formula.
        profile = make_profile()
        with pytest.raises(ValueError):
            apply_event(
                profile,
                "focus_phase_completed",
                {"minutes": 1e308},
                rates,
                rng_roll=1.0,
            )

    def test_extreme_habit_value_is_clamped(self, rates: GameRates) -> None:
        # value=-1e9 would explode 0.9747**value and inflate rewards; clamp first.
        profile = make_profile()
        outcome = apply_event(
            profile,
            "habit_click",
            {"direction": "positive", "value": -1e9},
            rates,
            rng_roll=1.0,
        )
        assert outcome["scored"] is True
        assert math.isfinite(outcome["delta"])

    def test_rates_from_dict_drops_bad_divisors(self) -> None:
        tuned = GameRates.from_dict(
            {
                "lvl_curve_round": 0,
                "con_shield_divisor": -5.0,
                "crit_str_chance_scale": float("nan"),
                "lvl_curve_early": 0,
            }
        )
        # Bad values fall back to defaults rather than ZeroDivision/inf loops.
        assert tuned.lvl_curve_round == 10.0
        assert tuned.con_shield_divisor == 250.0
        assert tuned.crit_str_chance_scale == 100.0
        assert xp_to_next_level(1, tuned) >= 1

    def test_rates_from_dict_preserves_difficulty_override(self) -> None:
        tuned = GameRates.from_dict(
            {"difficulty": {"trivial": 0.5, "easy": 2.0, "evil": -3.0, "nan": float("nan")}}
        )
        # Valid multipliers override; non-finite and non-positive entries drop.
        assert tuned.difficulty["trivial"] == 0.5
        assert tuned.difficulty["easy"] == 2.0
        assert "evil" not in tuned.difficulty
        assert "nan" not in tuned.difficulty

    def test_rates_from_dict_drops_nonpositive_drift_base(self) -> None:
        # habit_drift_base=0 would explode 0**negative_value in habit_delta.
        tuned = GameRates.from_dict({"habit_drift_base": 0.0})
        assert tuned.habit_drift_base == 0.9747

    def test_non_numeric_habit_value_raises(self, rates: GameRates) -> None:
        profile = make_profile()
        with pytest.raises(ValueError):
            apply_event(
                profile,
                "habit_click",
                {"direction": "positive", "value": None},
                rates,
                rng_roll=1.0,
            )

    def test_non_finite_damage_raises(self, rates: GameRates) -> None:
        profile = make_profile()
        with pytest.raises(ValueError):
            apply_event(profile, "damage", {"amount": float("inf")}, rates, rng_roll=1.0)
