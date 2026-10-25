"""add_history_source_type

Revision ID: 742fdcbd5779
Revises: b031f6aa961e
Create Date: 2026-08-14 13:34:37.204747

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "742fdcbd5779"
down_revision: Union[str, Sequence[str], None] = "b031f6aa961e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        # ADD VALUE must commit before 'history' is usable; a later migration
        # builds a partial index on it in the same alembic transaction.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE sourcetype ADD VALUE IF NOT EXISTS 'history'")


def downgrade() -> None:
    """Downgrade schema.

    No-op: PostgreSQL cannot remove an enum value, and SQLite has no native
    enum (the column compiles to bare VARCHAR).
    """
    pass
