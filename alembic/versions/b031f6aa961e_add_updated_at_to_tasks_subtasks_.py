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
    for table in ("tbl_tasks", "tbl_subtasks", "tbl_projects"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("(CURRENT_TIMESTAMP)"),
                    nullable=False,
                )
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("tbl_projects", "tbl_subtasks", "tbl_tasks"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("updated_at")
