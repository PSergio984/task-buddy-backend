"""game_profile_class_unlocked

Revision ID: 43e0e53f38eb
Revises: c8d4e6f0a2b4
Create Date: 2026-06-02 00:00:00.000000

Sticky class-pick flag for the character sheet (issue #64): select_class is
gated on level 10, but a classed user who death-drops below 10 then pays the
respec would be locked out of re-picking forever (level < 10 rejects the
pick). class_unlocked records the first successful pick so the gate is
'unlocked OR level >= 10'; respec clears game_class only, never the flag.
Profiles already holding a class are backfilled unlocked. Schema-only plus
that one keyed backfill; downgrade drops the column.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "43e0e53f38eb"
down_revision: Union[str, Sequence[str], None] = "c8d4e6f0a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_profiles = sa.table(
    "tbl_game_profiles",
    sa.column("game_class", sa.String),
    sa.column("class_unlocked", sa.Boolean),
)


def upgrade() -> None:
    op.add_column(
        "tbl_game_profiles",
        sa.Column("class_unlocked", sa.Boolean(), server_default="0", nullable=False),
    )
    # Anyone already holding a class passed the gate — keep them unlocked.
    op.execute(
        _profiles.update()
        .where(_profiles.c.game_class.is_not(None))
        .values(class_unlocked=True)
    )


def downgrade() -> None:
    op.drop_column("tbl_game_profiles", "class_unlocked")
