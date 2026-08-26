"""drop users confirmation failed

Revision ID: e83e10d0b749
Revises: 0ac2c06f6340
Create Date: 2026-08-26 21:42:18.829081

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e83e10d0b749"
down_revision: str | None = "0ac2c06f6340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop tbl_users.confirmation_failed (dead marker).

    DATA LOSS: existing confirmation_failed flag values are permanently
    discarded by this upgrade, by design. Sanctioned by the ADR-ingested
    decision (04-CONTEXT): the marker was write-only — nothing reads it —
    and recovery is user-driven resend.
    """
    op.drop_column("tbl_users", "confirmation_failed")


def downgrade() -> None:
    """Restore the column; prior flags are unrecoverable (restore as false)."""
    op.add_column(
        "tbl_users",
        sa.Column("confirmation_failed", sa.Boolean(), server_default="0", nullable=False),
    )
