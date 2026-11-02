"""seed_gear_achievements

Revision ID: b64a2c1e9f03
Revises: c4e7a91f2b05
Create Date: 2026-06-01 00:00:00.000000

Seeded content for the character sheet (issue #64): the 24-row gear catalog
(per-class weapon/armor/head ladders plus all-class fillers covering the
seven slots) and the 15-badge achievement registry. Data migration by
explicit request — app/game/character_service.py's seed_gear_catalog and
app/game/achievements.py's seed_achievements upsert the same keys at runtime,
so the literals below must stay in lockstep with GEAR_CATALOG/ACHIEVEMENTS.
Downgrade deletes by key; user-owned rows (tbl_user_gear,
tbl_user_achievements) cascade away with the catalog/registry rows.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b64a2c1e9f03"
down_revision: Union[str, Sequence[str], None] = "c4e7a91f2b05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_gear = sa.table(
    "tbl_gear_items",
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("slot", sa.String),
    sa.column("klass", sa.String),
    sa.column("tier", sa.Integer),
    sa.column("stats", sa.JSON),
    sa.column("cost", sa.Integer),
    sa.column("losable", sa.Boolean),
)

_ach = sa.table(
    "tbl_achievements",
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("criteria", sa.JSON),
    sa.column("gold_reward", sa.Integer),
)

# key, name, slot, klass, tier, stats, cost — keep in sync with
# app.game.character_service.GEAR_CATALOG.
GEAR_ROWS: list[dict] = [
    {"key": "warrior-weapon-1", "name": "Training Sword", "slot": "weapon",
     "klass": "warrior", "tier": 1, "stats": {"str": 3}, "cost": 100},
    {"key": "warrior-weapon-2", "name": "Broad Sword", "slot": "weapon",
     "klass": "warrior", "tier": 2, "stats": {"str": 6}, "cost": 250},
    {"key": "warrior-armor-1", "name": "Leather Armor", "slot": "armor",
     "klass": "warrior", "tier": 1, "stats": {"con": 3}, "cost": 90},
    {"key": "warrior-armor-2", "name": "Chain Mail", "slot": "armor",
     "klass": "warrior", "tier": 2, "stats": {"con": 5}, "cost": 220},
    {"key": "warrior-head-1", "name": "Iron Helm", "slot": "head",
     "klass": "warrior", "tier": 1, "stats": {"str": 2}, "cost": 60},
    {"key": "mage-weapon-1", "name": "Apprentice Staff", "slot": "weapon",
     "klass": "mage", "tier": 1, "stats": {"int": 3}, "cost": 100},
    {"key": "mage-weapon-2", "name": "Wizard Staff", "slot": "weapon",
     "klass": "mage", "tier": 2, "stats": {"int": 6}, "cost": 250},
    {"key": "mage-armor-1", "name": "Magician Robe", "slot": "armor",
     "klass": "mage", "tier": 1, "stats": {"per": 3}, "cost": 90},
    {"key": "mage-armor-2", "name": "Archmage Robe", "slot": "armor",
     "klass": "mage", "tier": 2, "stats": {"per": 5}, "cost": 220},
    {"key": "mage-head-1", "name": "Magician Hat", "slot": "head",
     "klass": "mage", "tier": 1, "stats": {"int": 2}, "cost": 60},
    {"key": "healer-weapon-1", "name": "Novice Rod", "slot": "weapon",
     "klass": "healer", "tier": 1, "stats": {"int": 3}, "cost": 100},
    {"key": "healer-weapon-2", "name": "Acolyte Rod", "slot": "weapon",
     "klass": "healer", "tier": 2, "stats": {"int": 6}, "cost": 250},
    {"key": "healer-armor-1", "name": "Priest Robe", "slot": "armor",
     "klass": "healer", "tier": 1, "stats": {"con": 3}, "cost": 90},
    {"key": "healer-armor-2", "name": "Royal Vestments", "slot": "armor",
     "klass": "healer", "tier": 2, "stats": {"con": 5}, "cost": 220},
    {"key": "healer-head-1", "name": "Circlet", "slot": "head",
     "klass": "healer", "tier": 1, "stats": {"con": 2}, "cost": 60},
    {"key": "rogue-weapon-1", "name": "Short Dagger", "slot": "weapon",
     "klass": "rogue", "tier": 1, "stats": {"per": 3}, "cost": 100},
    {"key": "rogue-weapon-2", "name": "Hidden Blade", "slot": "weapon",
     "klass": "rogue", "tier": 2, "stats": {"per": 6}, "cost": 250},
    {"key": "rogue-armor-1", "name": "Oiled Leather", "slot": "armor",
     "klass": "rogue", "tier": 1, "stats": {"str": 3}, "cost": 90},
    {"key": "rogue-armor-2", "name": "Umbral Armor", "slot": "armor",
     "klass": "rogue", "tier": 2, "stats": {"str": 5}, "cost": 220},
    {"key": "rogue-head-1", "name": "Hood", "slot": "head",
     "klass": "rogue", "tier": 1, "stats": {"per": 2}, "cost": 60},
    {"key": "all-shield-1", "name": "Wooden Shield", "slot": "shield",
     "klass": "all", "tier": 1, "stats": {"con": 1}, "cost": 50},
    {"key": "all-body-1", "name": "Plain Shirt", "slot": "body",
     "klass": "all", "tier": 1, "stats": {"con": 1}, "cost": 40},
    {"key": "all-back-1", "name": "Traveler Cloak", "slot": "back",
     "klass": "all", "tier": 1, "stats": {"per": 1}, "cost": 40},
    {"key": "all-eyewear-1", "name": "Spectacles", "slot": "eyewear",
     "klass": "all", "tier": 1, "stats": {"int": 1}, "cost": 30},
]

# key, name, description, criteria, gold_reward — keep in sync with
# app.game.achievements.ACHIEVEMENTS.
ACHIEVEMENT_ROWS: list[dict] = [
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


def upgrade() -> None:
    op.bulk_insert(_gear, [{**row, "losable": True} for row in GEAR_ROWS])
    op.bulk_insert(_ach, ACHIEVEMENT_ROWS)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.delete(_gear).where(_gear.c.key.in_([row["key"] for row in GEAR_ROWS]))
    )
    bind.execute(
        sa.delete(_ach).where(_ach.c.key.in_([row["key"] for row in ACHIEVEMENT_ROWS]))
    )
