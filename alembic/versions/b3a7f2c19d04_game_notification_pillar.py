"""game_notification_pillar

Revision ID: b3a7f2c19d04
Revises: 43e0e53f38eb
Create Date: 2026-12-20 00:00:00.000000

Notifications pillar of the gamified focus layer (issue #68): extend the
notificationtype enum with the game kinds — reminders (habit/daily),
warnings (streak_risk, low_hp, daily_missed, death), alerts (phase_end) and
celebrations (level_up, achievement, record — the last lands with #69 but
rides this ALTER so no second enum migration is needed) — and add the
`meta` JSONB column the dispatcher uses for dedup keys and entity links.

Postgres enum values are append-only (ALTER TYPE ... ADD VALUE IF NOT
EXISTS); SQLite stores the column as varchar so the enum section is a
dialect-guarded no-op there. Downgrade drops `meta` only — Postgres offers
no enum-value removal short of recreating the type.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3a7f2c19d04"
down_revision: Union[str, Sequence[str], None] = "43e0e53f38eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB on Postgres, plain JSON elsewhere (SQLite migration test cannot compile JSONB).
_json_type = sa.JSON().with_variant(JSONB(), "postgresql")

_NEW_KINDS = (
    "HABIT_REMINDER",
    "DAILY_REMINDER",
    "STREAK_RISK",
    "LOW_HP",
    "DAILY_MISSED",
    "DEATH",
    "PHASE_END",
    "LEVEL_UP",
    "ACHIEVEMENT",
    "RECORD",
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for kind in _NEW_KINDS:
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{kind}'")
    op.add_column("tbl_notifications", sa.Column("meta", _json_type, nullable=True))


def downgrade() -> None:
    op.drop_column("tbl_notifications", "meta")
    # Postgres enum values can't be dropped without recreating the type —
    # the extra labels are inert, so downgrade leaves them in place.
