"""Character sheet orchestration: stat allocation, class pick, respec (issue #64).

The engine stays pure (no DB); this service owns the profile mutations the
economy endpoints need — spending unspent points, the level-10 class gate,
the paid respec — plus the post-scoring hook every profile-mutating path
shares: auto-distribute new points (when enabled), then evaluate grants.

Auto-distribute: each unspent point goes to the lower-allocated of the
class's two affinity stats (primary breaks ties); classless users balance
across all four. Points never exceed STAT_POINT_CAP.
"""

import random

from sqlalchemy import Insert, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import achievements, engine
from app.game.engine import GameRates
from app.models.game import GameProfile, GearItem, UserGear

# Seeded content (issue #64): a short ladder per class on weapon/armor/head,
# plus all-class fillers so every one of the seven slots can be worn. Ladder
# rule: tier N requires owning the same slot+klass piece at tier N-1.
GEAR_CATALOG: list[dict] = [
    # key, name, slot, klass, tier, stats, cost
    {
        "key": "warrior-weapon-1",
        "name": "Training Sword",
        "slot": "weapon",
        "klass": "warrior",
        "tier": 1,
        "stats": {"str": 3},
        "cost": 100,
    },
    {
        "key": "warrior-weapon-2",
        "name": "Broad Sword",
        "slot": "weapon",
        "klass": "warrior",
        "tier": 2,
        "stats": {"str": 6},
        "cost": 250,
    },
    {
        "key": "warrior-armor-1",
        "name": "Leather Armor",
        "slot": "armor",
        "klass": "warrior",
        "tier": 1,
        "stats": {"con": 3},
        "cost": 90,
    },
    {
        "key": "warrior-armor-2",
        "name": "Chain Mail",
        "slot": "armor",
        "klass": "warrior",
        "tier": 2,
        "stats": {"con": 5},
        "cost": 220,
    },
    {
        "key": "warrior-head-1",
        "name": "Iron Helm",
        "slot": "head",
        "klass": "warrior",
        "tier": 1,
        "stats": {"str": 2},
        "cost": 60,
    },
    {
        "key": "mage-weapon-1",
        "name": "Apprentice Staff",
        "slot": "weapon",
        "klass": "mage",
        "tier": 1,
        "stats": {"int": 3},
        "cost": 100,
    },
    {
        "key": "mage-weapon-2",
        "name": "Wizard Staff",
        "slot": "weapon",
        "klass": "mage",
        "tier": 2,
        "stats": {"int": 6},
        "cost": 250,
    },
    {
        "key": "mage-armor-1",
        "name": "Magician Robe",
        "slot": "armor",
        "klass": "mage",
        "tier": 1,
        "stats": {"per": 3},
        "cost": 90,
    },
    {
        "key": "mage-armor-2",
        "name": "Archmage Robe",
        "slot": "armor",
        "klass": "mage",
        "tier": 2,
        "stats": {"per": 5},
        "cost": 220,
    },
    {
        "key": "mage-head-1",
        "name": "Magician Hat",
        "slot": "head",
        "klass": "mage",
        "tier": 1,
        "stats": {"int": 2},
        "cost": 60,
    },
    {
        "key": "healer-weapon-1",
        "name": "Novice Rod",
        "slot": "weapon",
        "klass": "healer",
        "tier": 1,
        "stats": {"int": 3},
        "cost": 100,
    },
    {
        "key": "healer-weapon-2",
        "name": "Acolyte Rod",
        "slot": "weapon",
        "klass": "healer",
        "tier": 2,
        "stats": {"int": 6},
        "cost": 250,
    },
    {
        "key": "healer-armor-1",
        "name": "Priest Robe",
        "slot": "armor",
        "klass": "healer",
        "tier": 1,
        "stats": {"con": 3},
        "cost": 90,
    },
    {
        "key": "healer-armor-2",
        "name": "Royal Vestments",
        "slot": "armor",
        "klass": "healer",
        "tier": 2,
        "stats": {"con": 5},
        "cost": 220,
    },
    {
        "key": "healer-head-1",
        "name": "Circlet",
        "slot": "head",
        "klass": "healer",
        "tier": 1,
        "stats": {"con": 2},
        "cost": 60,
    },
    {
        "key": "rogue-weapon-1",
        "name": "Short Dagger",
        "slot": "weapon",
        "klass": "rogue",
        "tier": 1,
        "stats": {"per": 3},
        "cost": 100,
    },
    {
        "key": "rogue-weapon-2",
        "name": "Hidden Blade",
        "slot": "weapon",
        "klass": "rogue",
        "tier": 2,
        "stats": {"per": 6},
        "cost": 250,
    },
    {
        "key": "rogue-armor-1",
        "name": "Oiled Leather",
        "slot": "armor",
        "klass": "rogue",
        "tier": 1,
        "stats": {"str": 3},
        "cost": 90,
    },
    {
        "key": "rogue-armor-2",
        "name": "Umbral Armor",
        "slot": "armor",
        "klass": "rogue",
        "tier": 2,
        "stats": {"str": 5},
        "cost": 220,
    },
    {
        "key": "rogue-head-1",
        "name": "Hood",
        "slot": "head",
        "klass": "rogue",
        "tier": 1,
        "stats": {"per": 2},
        "cost": 60,
    },
    {
        "key": "all-shield-1",
        "name": "Wooden Shield",
        "slot": "shield",
        "klass": "all",
        "tier": 1,
        "stats": {"con": 1},
        "cost": 50,
    },
    {
        "key": "all-body-1",
        "name": "Plain Shirt",
        "slot": "body",
        "klass": "all",
        "tier": 1,
        "stats": {"con": 1},
        "cost": 40,
    },
    {
        "key": "all-back-1",
        "name": "Traveler Cloak",
        "slot": "back",
        "klass": "all",
        "tier": 1,
        "stats": {"per": 1},
        "cost": 40,
    },
    {
        "key": "all-eyewear-1",
        "name": "Spectacles",
        "slot": "eyewear",
        "klass": "all",
        "tier": 1,
        "stats": {"int": 1},
        "cost": 30,
    },
]


# Columns the seed literal owns — `key` is the match anchor, `losable`
# stays a schema-level default (not catalog data).
_SEED_FIELDS = ("name", "slot", "klass", "tier", "stats", "cost")


def _insert_missing(db: AsyncSession, rows: list[dict]) -> Insert:
    """INSERT ... ON CONFLICT (key) DO NOTHING for the active dialect —
    a concurrent seeder's committed rows win instead of 500ing this txn
    (dialect switch per the budget.py precedent; both backends expose
    on_conflict_do_nothing)."""
    if db.get_bind().dialect.name == "postgresql":
        return postgres_insert(GearItem).values(rows).on_conflict_do_nothing(index_elements=["key"])
    return sqlite_insert(GearItem).values(rows).on_conflict_do_nothing(index_elements=["key"])


async def seed_gear_catalog(db: AsyncSession) -> None:
    """Upsert GEAR_CATALOG rows; the code literal is the single source.

    Runtime seeding (not a data migration) so SQLite test schemas, which
    never run Alembic, get the same catalog prod does on first read.
    Missing keys insert; rows whose fields drifted from the literal update
    in place — a catalog edit can't silently die on an already-seeded DB.

    Persists on the caller's first committed write: GET-path inserts roll
    back on seedless DBs (acceptable — self-heals on the first write).
    """
    existing = {row.key: row for row in (await db.execute(select(GearItem))).scalars().all()}
    for seed in GEAR_CATALOG:
        item = existing.get(seed["key"])
        if item is not None and any(getattr(item, f) != seed[f] for f in _SEED_FIELDS):
            for field in _SEED_FIELDS:
                setattr(item, field, seed[field])
    missing = [row for row in GEAR_CATALOG if row["key"] not in existing]
    if missing:
        await db.execute(_insert_missing(db, missing))


# --- Gear -------------------------------------------------------------------


async def gear_stat_bonus(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Sum the raw stats of everything equipped — the engine's stat_bonus."""
    bonus: dict[str, int] = {}
    for _user_gear, item in await game_crud.list_equipped_gear(db, user_id):
        for key, n in (item.stats or {}).items():
            if key in engine.STAT_KEYS:
                bonus[key] = bonus.get(key, 0) + int(n)
    return bonus


async def buy_gear(
    db: AsyncSession, user_id: int, profile: GameProfile, item: GearItem
) -> UserGear:
    """Debit gold for a catalog item; ValueError on any rule breach.

    Rules: not already owned; class lock ('all' or the user's class); ladder
    order (tier N needs the N-1 piece of the same slot+klass); enough gold.
    """
    if item.klass != "all" and profile.game_class != item.klass:
        raise ValueError(f"'{item.key}' is locked to the {item.klass} class")
    if await game_crud.get_user_gear(db, user_id, item.id) is not None:
        raise ValueError("item already owned")
    if item.tier > 1:
        prev = await game_crud.find_gear_item(
            db, slot=item.slot, klass=item.klass, tier=item.tier - 1
        )
        if prev is None or await game_crud.get_user_gear(db, user_id, prev.id) is None:
            raise ValueError("buy the previous ladder tier first")
    if profile.gold < item.cost:
        raise ValueError("not enough gold")
    profile.gold -= item.cost
    user_gear = UserGear(user_id=user_id, gear_item_id=item.id, equipped=False, costume=False)
    db.add(user_gear)
    await db.flush()
    return user_gear


async def set_equipped(
    db: AsyncSession, user_id: int, profile: GameProfile, key: str, on: bool
) -> None:
    """Wear or remove a catalog item; ValueError when the move is illegal.

    One item per slot: equipping bumps whatever already fills the slot.
    Class-locked pieces can only be worn by their class.
    """
    item = await game_crud.get_gear_item(db, key)
    if item is None:
        raise ValueError(f"unknown gear item '{key}'")
    user_gear = await game_crud.get_user_gear(db, user_id, item.id)
    if user_gear is None:
        raise ValueError("item not owned")
    if on:
        if item.klass != "all" and profile.game_class != item.klass:
            raise ValueError(f"'{item.key}' is locked to the {item.klass} class")
        # One per slot: bump the current occupant, then take the slot.
        result = await db.execute(
            select(UserGear)
            .join(GearItem, UserGear.gear_item_id == GearItem.id)
            .where(
                UserGear.user_id == user_id,
                UserGear.equipped.is_(True),
                GearItem.slot == item.slot,
                UserGear.id != user_gear.id,
            )
        )
        for other in result.scalars():
            other.equipped = False
    user_gear.equipped = on


async def list_catalog(db: AsyncSession, user_id: int) -> list[dict]:
    """Catalog rows merged with the user's owned/equipped flags."""
    await seed_gear_catalog(db)
    owned = {ug.gear_item_id: ug for ug in await game_crud.list_user_gear(db, user_id)}
    rows = []
    for item in await game_crud.list_gear_catalog(db):
        ug = owned.get(item.id)
        rows.append({"item": item, "owned": ug is not None, "equipped": bool(ug and ug.equipped)})
    return rows


async def lose_random_gear(
    db: AsyncSession, user_id: int, rng: random.Random | None = None
) -> str | None:
    """Delete one random LOSABLE owned item; returns its catalog key.

    The death cascade loses owned gear, not just worn pieces — Habitica's
    revive picks from the whole losable pool. rng is injectable so tests
    can pin the pick; None falls back to the module generator.
    """
    result = await db.execute(
        select(UserGear, GearItem)
        .join(GearItem, UserGear.gear_item_id == GearItem.id)
        .where(UserGear.user_id == user_id, GearItem.losable.is_(True))
    )
    rows = list(result.all())
    if not rows:
        return None
    picker = rng if rng is not None else random
    user_gear, item = picker.choice(rows)
    await db.delete(user_gear)
    # autoflush is off project-wide: without a flush the dead row stays
    # visible to this transaction's own gear queries, so later events in
    # the same batch would still score with the lost item's stats.
    await db.flush()
    return str(item.key)


async def resolve_death_gear(
    db: AsyncSession,
    user_id: int,
    outcome: dict,
    rng: random.Random | None = None,
) -> None:
    """Finish the death cascade the pure engine flagged: pick the lost gear.

    Mutates `outcome` in place — callers run this before the row lands in
    the ledger so _outcome carries gear_lost/gear_lost_key, not the
    engine's placeholder.
    """
    if not outcome.get("died"):
        return
    lost = await lose_random_gear(db, user_id, rng)
    outcome["gear_lost"] = lost is not None
    outcome["gear_lost_key"] = lost


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
    """Set the user's class; gated on the level-10 unlock and a clean slate.

    The unlock is sticky: a first pick flips class_unlocked, which respec
    and death level-drops never clear — a classed-then-deleveled user can
    still re-pick below level 10 after paying for the respec.
    """
    if klass not in engine.CLASSES:
        raise ValueError(f"unknown class '{klass}'")
    if profile.game_class is not None:
        raise ValueError("respec first to change class")
    if not profile.class_unlocked and profile.level < engine.CLASS_MIN_LEVEL:
        raise ValueError(f"class unlocks at level {engine.CLASS_MIN_LEVEL}")
    profile.game_class = klass
    profile.class_unlocked = True


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
) -> None:
    """Post-scoring hook shared by every profile-mutating path.

    Auto-distribute first so achievement eval sees the settled profile;
    the grant pass lands with the achievement slice. Callers hold the
    profile lock.
    """
    if profile.auto_allocate:
        distribute_unspent(profile)
    # Grants run under the same profile lock so concurrent scoring paths
    # can't double-award; evaluation is a no-op when nothing new qualifies.
    await achievements.evaluate(db, user_id, profile)
