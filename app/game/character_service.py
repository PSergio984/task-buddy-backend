"""Character sheet orchestration: stat allocation, class pick, respec (issue #64).

The engine stays pure (no DB); this service owns the profile mutations the
economy endpoints need — spending unspent points, the level-10 class gate,
the paid respec — plus the post-scoring hook every profile-mutating path
shares: auto-distribute new points (when enabled), then evaluate grants.

Auto-distribute: each unspent point goes to the lower-allocated of the
class's two affinity stats (primary breaks ties); classless users balance
across all four. Points never exceed STAT_POINT_CAP.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import engine
from app.game.engine import GameRates
from app.models.game import GameProfile


# --- Stat allocation --------------------------------------------------------


def allocate_points(profile: GameProfile, points: dict) -> None:
    """Spend unspent points into the allocated pool; ValueError on bad input.

    The unspent balance is the hard bound — overdrafts and cap breaches are
    rejected atomically (nothing is applied before every check passes).
    """
    if not isinstance(points, dict) or not points:
        raise ValueError("points must be a non-empty mapping of stat -> count")
    clean: dict[str, int] = {}
    for key, n in points.items():
        if key not in engine.STAT_KEYS:
            raise ValueError(f"unknown stat '{key}'")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > engine.STAT_POINT_CAP:
            raise ValueError("point counts must be positive integers")
        clean[key] = n
    total = sum(clean.values())
    if total > profile.unspent_stat_points:
        raise ValueError("not enough unspent stat points")
    allocated = sum(getattr(profile, c) for c in engine.STAT_COLUMN.values())
    if allocated + total > engine.STAT_POINT_CAP:
        raise ValueError(f"total allocated stats are capped at {engine.STAT_POINT_CAP}")
    for key, n in clean.items():
        column = engine.STAT_COLUMN[key]
        setattr(profile, column, getattr(profile, column) + n)
    profile.unspent_stat_points -= total


def distribute_unspent(profile: GameProfile) -> int:
    """Auto-assign every unspent point; returns how many were assigned.

    Class affinity pair first (the lower-allocated wins, primary breaks
    ties); classless users balance across all four stats. Distribution
    stops at the total-allocated cap — the rest stays unspent.
    """
    order = engine.CLASSES.get(profile.game_class or "", engine.STAT_KEYS)
    assigned = 0
    while profile.unspent_stat_points > 0:
        allocated = sum(getattr(profile, c) for c in engine.STAT_COLUMN.values())
        if allocated >= engine.STAT_POINT_CAP:
            break
        pick = min(
            order,
            key=lambda k: (getattr(profile, engine.STAT_COLUMN[k]), order.index(k)),
        )
        column = engine.STAT_COLUMN[pick]
        setattr(profile, column, getattr(profile, column) + 1)
        profile.unspent_stat_points -= 1
        assigned += 1
    return assigned


# --- Class ------------------------------------------------------------------


def select_class(profile: GameProfile, klass: str) -> None:
    """Set the user's class; gated on the level-10 unlock and a clean slate."""
    if klass not in engine.CLASSES:
        raise ValueError(f"unknown class '{klass}'")
    if profile.game_class is not None:
        raise ValueError("respec first to change class")
    if profile.level < engine.CLASS_MIN_LEVEL:
        raise ValueError(f"class unlocks at level {engine.CLASS_MIN_LEVEL}")
    profile.game_class = klass


def respec(profile: GameProfile, rates: GameRates) -> float:
    """Debit the respec cost, clear the class, refund allocated points.

    Returns the gold paid. Refunding to unspent is what "re-opens choice"
    means for stats — the user re-spends the pool after re-picking.
    """
    if profile.game_class is None:
        raise ValueError("no class to respec")
    cost = float(rates.respec_gold_cost)
    if profile.gold < cost:
        raise ValueError("not enough gold for respec")
    profile.gold -= cost
    profile.game_class = None
    refunded = 0
    for column in engine.STAT_COLUMN.values():
        refunded += getattr(profile, column)
        setattr(profile, column, 0)
    profile.unspent_stat_points += refunded
    return cost


async def unequip_mismatched(db: AsyncSession, user_id: int, klass: str | None) -> None:
    """Strip equipped items whose ladder isn't `klass` or 'all'.

    Runs after a respec (klass=None — every class piece comes off) and a
    re-pick, so owned cross-class gear stays owned but never stays worn.
    """
    for user_gear, item in await game_crud.list_equipped_gear(db, user_id):
        if item.klass != "all" and item.klass != klass:
            user_gear.equipped = False


async def post_score(
    db: AsyncSession,
    user_id: int,
    profile: GameProfile,
    rates: GameRates,
    today: date,
) -> None:
    """Post-scoring hook shared by every profile-mutating path.

    Auto-distribute first so achievement eval sees the settled profile;
    the grant pass lands with the achievement slice. Callers hold the
    profile lock.
    """
    if profile.auto_allocate:
        distribute_unspent(profile)
