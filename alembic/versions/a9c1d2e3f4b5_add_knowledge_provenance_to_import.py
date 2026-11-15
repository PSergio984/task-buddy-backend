"""add knowledge provenance to import

Revision ID: a9c1d2e3f4b5
Revises: f5a8c2d91b47
Create Date: 2026-11-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c1d2e3f4b5"
down_revision: str | None = "f5a8c2d91b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Allow knowledge notes to exist before or without a task (standalone note / note-to-tasks source)
    with op.batch_alter_table("tbl_knowledge") as batch_op:
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=True)

    # 2. Allow knowledge chunks to exist without a specific task_id
    with op.batch_alter_table("tbl_knowledge_chunks") as batch_op:
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=True)

    # 3. Add provenance back-reference on tasks pointing to the source note
    with op.batch_alter_table("tbl_tasks") as batch_op:
        batch_op.add_column(sa.Column("source_knowledge_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tbl_tasks_source_knowledge_id_tbl_knowledge",
            "tbl_knowledge",
            ["source_knowledge_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_tbl_tasks_source_knowledge_id", ["source_knowledge_id"])


def downgrade() -> None:
    with op.batch_alter_table("tbl_tasks") as batch_op:
        batch_op.drop_index("ix_tbl_tasks_source_knowledge_id")
        batch_op.drop_constraint(
            "fk_tbl_tasks_source_knowledge_id_tbl_knowledge", type_="foreignkey"
        )
        batch_op.drop_column("source_knowledge_id")

    conn = op.get_bind()
    unattached = conn.execute(
        sa.text("SELECT count(*) FROM tbl_knowledge WHERE task_id IS NULL")
    ).scalar()
    if unattached and unattached > 0:
        raise RuntimeError(
            f"Cannot downgrade: found {unattached} standalone knowledge row(s) (task_id IS NULL). "
            "Reassign or delete these rows before downgrading to avoid data loss."
        )

    with op.batch_alter_table("tbl_knowledge_chunks") as batch_op:
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("tbl_knowledge") as batch_op:
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=False)
