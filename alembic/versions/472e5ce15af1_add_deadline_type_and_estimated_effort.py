"""add_deadline_type_and_estimated_effort

Revision ID: 472e5ce15af1
Revises: 742fdcbd5779
Create Date: 2026-08-14 15:25:46.005892

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '472e5ce15af1'
down_revision: Union[str, Sequence[str], None] = '742fdcbd5779'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE TYPE deadlinetype AS ENUM ('soft','hard')")
    with op.batch_alter_table("tbl_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("estimated_effort_minutes", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "deadline_type",
                sa.Enum("soft", "hard", name="deadlinetype", create_type=False),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tbl_tasks") as batch_op:
        batch_op.drop_column("deadline_type")
        batch_op.drop_column("estimated_effort_minutes")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS deadlinetype")
