"""Achievement registry and grant evaluation (issue #64).

15 seeded badges across the spec's buckets — levels, streaks, focus totals,
firsts, records, perfect days — each paying a tiered gold reward. Evaluation
runs inside the post-score hook under the caller's profile lock; grants are
idempotent via the (user_id, achievement_id) unique constraint plus the
earned-set prefilter, so replays and retries award nothing twice.

Sources: the scored ledger row is canonical for firsts and focus totals
(offline claims and server-side sessions both write focus_phase_completed
with `minutes` and `_outcome.scored`); streak/record reads use the live
aggregate columns (Daily.streak, Habit.counter); perfect_day counts whole-
daily done checks per date against the user's active dailies.
"""

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import (
    Achievement,
    Daily,
    DailyCheck,
    GameEvent,
    GameProfile,
    Habit,
    UserAchievement,
    UserGear,
)

# Seeded content — gold_reward tiers: firsts 10, milestones 25-40, long-term
# feats 50-100.
ACHIEVEMENTS: list[dict] = [
    {"key": "level-10", "name": "Novice", "description": "Reach level 10",
     "criteria": {"kind": "level", "threshold": 10}, "gold_reward": 25},
    {"key": "level-25", "name": "Veteran", "description": "Reach level 25",
     "criteria": {"kind": "level", "threshold": 25}, "gold_reward": 50},
    {"key": "level-50", "name": "Master", "description": "Reach level 50",
     "criteria": {"kind": "level", "threshold": 50}, "gold_reward": 100},
    {"key": "first-focus", "name": "First Steps",
     "description": "Complete a focus phase",
     "criteria": {"kind": "first", "what": "focus_phase_completed"},
     "gold_reward": 10},
    {"key": "first-habit", "name": "Habitual",
     "description": "Score a habit click",
     "criteria": {"kind": "first", "what": "habit_click"}, "gold_reward": 10},
    {"key": "first-daily", "name": "Daily Grind",
     "description": "Check off a daily",
     "criteria": {"kind": "first", "what": "daily_check"}, "gold_reward": 10},
    {"key": "first-gear", "name": "Geared Up",
     "description": "Own a piece of gear",
     "criteria": {"kind": "gear_owned", "threshold": 1}, "gold_reward": 10},
    {"key": "class-picked", "name": "Specialist",
     "description": "Choose a class", "criteria": {"kind": "class"},
     "gold_reward": 15},
    {"key": "focus-100", "name": "Focused",
     "description": "Log 100 total focus minutes",
     "criteria": {"kind": "focus_total", "threshold": 100}, "gold_reward": 25},
    {"key": "focus-1000", "name": "Deep Diver",
     "description": "Log 1000 total focus minutes",
     "criteria": {"kind": "focus_total", "threshold": 1000}, "gold_reward": 75},
    {"key": "marathon", "name": "Marathon Mind",
     "description": "Complete one focus phase of 45+ minutes",
     "criteria": {"kind": "phase_minutes", "threshold": 45}, "gold_reward": 40},
    {"key": "streak-7", "name": "On a Roll",
     "description": "Reach a 7-day daily streak",
     "criteria": {"kind": "streak", "threshold": 7}, "gold_reward": 30},
    {"key": "streak-21", "name": "Unstoppable",
     "description": "Reach a 21-day daily streak",
     "criteria": {"kind": "streak", "threshold": 21}, "gold_reward": 80},
    {"key": "perfect-day", "name": "Perfect Day",
     "description": "Check every daily in one day",
     "criteria": {"kind": "perfect_day"}, "gold_reward": 50},
    {"key": "clicker-50", "name": "Persistent",
     "description": "Reach +50 on one habit's counter",
     "criteria": {"kind": "habit_counter", "threshold": 50}, "gold_reward": 35},
]


async def seed_achievements(db: AsyncSession) -> None:
    """Insert missing ACHIEVEMENTS rows; idempotent on key."""
    existing = set((await db.execute(select(Achievement.key))).scalars().all())
    missing = [row for row in ACHIEVEMENTS if row["key"] not in existing]
    if missing:
        await db.execute(insert(Achievement).values(missing))


def _scored_events(db: AsyncSession, user_id: int, event_type: str):
    """Select over the scored ledger for one event type."""
    return select(GameEvent).where(
        GameEvent.user_id == user_id,
        GameEvent.type == event_type,
        GameEvent.payload["_outcome"]["scored"].as_boolean(),
    )


async def _meets(
    db: AsyncSession, user_id: int, profile: GameProfile, criteria: dict
) -> bool:
    """True when the criteria's live check passes. Unknown kinds never grant."""
    kind = criteria.get("kind")
    threshold = criteria.get("threshold", 0)
    if kind == "level":
        return profile.level >= threshold
    if kind == "class":
        return profile.game_class is not None
    if kind == "first":
        result = await db.execute(_scored_events(db, user_id, criteria["what"]).limit(1))
        return result.first() is not None
    if kind == "gear_owned":
        result = await db.execute(
            select(func.count())
            .select_from(UserGear)
            .where(UserGear.user_id == user_id)
        )
        return int(result.scalar_one()) >= threshold
    if kind == "focus_total":
        result = await db.execute(
            select(func.sum(GameEvent.payload["minutes"].as_float())).where(
                GameEvent.user_id == user_id,
                GameEvent.type == "focus_phase_completed",
                GameEvent.payload["_outcome"]["scored"].as_boolean(),
            )
        )
        return float(result.scalar_one() or 0.0) >= threshold
    if kind == "phase_minutes":
        result = await db.execute(
            select(func.max(GameEvent.payload["minutes"].as_float())).where(
                GameEvent.user_id == user_id,
                GameEvent.type == "focus_phase_completed",
                GameEvent.payload["_outcome"]["scored"].as_boolean(),
            )
        )
        return float(result.scalar_one() or 0.0) >= threshold
    if kind == "streak":
        result = await db.execute(
            select(func.max(Daily.streak)).where(Daily.user_id == user_id)
        )
        return int(result.scalar_one() or 0) >= threshold
    if kind == "habit_counter":
        result = await db.execute(
            select(func.max(Habit.counter)).where(Habit.user_id == user_id)
        )
        return int(result.scalar_one() or 0) >= threshold
    if kind == "perfect_day":
        active = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Daily)
                    .where(Daily.user_id == user_id, Daily.active.is_(True))
                )
            ).scalar_one()
        )
        if active == 0:
            return False
        result = await db.execute(
            select(func.count(func.distinct(DailyCheck.daily_id)))
            .join(Daily, DailyCheck.daily_id == Daily.id)
            .where(
                Daily.user_id == user_id,
                Daily.active.is_(True),
                DailyCheck.daily_item_id.is_(None),
                DailyCheck.done.is_(True),
            )
            .group_by(DailyCheck.check_date)
        )
        return any(count >= active for count in result.scalars().all())
    return False


async def evaluate(
    db: AsyncSession, user_id: int, profile: GameProfile
) -> list[Achievement]:
    """Grant every met-but-unearned achievement; return the newly granted.

    The profile lock the caller holds serializes evaluation, so the
    earned-set prefilter is authoritative — the unique constraint is only
    the belt-and-braces for it.
    """
    # autoflush is off project-wide: the caller's pending GameEvent rows
    # must hit the table before event-based criteria can see them.
    await db.flush()
    await seed_achievements(db)
    earned_ids = set(
        (
            await db.execute(
                select(UserAchievement.achievement_id).where(
                    UserAchievement.user_id == user_id
                )
            )
        ).scalars().all()
    )
    pending = [
        row
        for row in (await db.execute(select(Achievement))).scalars().all()
        if row.id not in earned_ids
    ]
    granted: list[Achievement] = []
    for achievement in pending:
        if await _meets(db, user_id, profile, achievement.criteria or {}):
            db.add(UserAchievement(user_id=user_id, achievement_id=achievement.id))
            profile.gold += achievement.gold_reward
            granted.append(achievement)
    return granted


async def list_for_user(db: AsyncSession, user_id: int) -> list[dict]:
    """Registry rows merged with the viewer's earned_at (None = unearned)."""
    await seed_achievements(db)
    result = await db.execute(
        select(Achievement, UserAchievement.earned_at)
        .outerjoin(
            UserAchievement,
            (UserAchievement.achievement_id == Achievement.id)
            & (UserAchievement.user_id == user_id),
        )
        .order_by(Achievement.id)
    )
    return [
        {"achievement": ach, "earned_at": earned_at}
        for ach, earned_at in result.all()
    ]
