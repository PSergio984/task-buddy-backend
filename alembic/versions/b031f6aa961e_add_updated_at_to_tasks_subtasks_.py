"""add_updated_at_to_tasks_subtasks_projects

Revision ID: b031f6aa961e
Revises: 7c9e2f4a1d8b
Create Date: 2026-08-13 22:35:52.954280

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b031f6aa961e"
down_revision: Union[str, Sequence[str], None] = "7c9e2f4a1d8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tbl_tasks",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.add_column(
        "tbl_subtasks",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.add_column(
        "tbl_projects",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tbl_projects", "updated_at")
    op.drop_column("tbl_subtasks", "updated_at")
    op.drop_column("tbl_tasks", "updated_at")
