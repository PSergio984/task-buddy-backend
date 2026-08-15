"""pre_dogfood_hardening

Revision ID: 1a2b3c4d5e6f
Revises: 7f3d863bb907
Create Date: 2026-08-15

Pre-dogfood hardening batch:
- Partial unique index enforcing one HISTORY corpus row per task (D-07 race).
- FK covering indexes for the knowledge/plan tables (Supabase advisor
  findings — these are the RAG hot paths during the dogfood window).
- Revoke EXECUTE on the RLS bootstrap helper from anon/authenticated
  (SECURITY DEFINER must not be callable over PostgREST).
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "7f3d863bb907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tbl_knowledge_task_history
        ON tbl_knowledge (task_id, source_type)
        WHERE source_type = 'history'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_task_id
        ON tbl_knowledge (task_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_user_id
        ON tbl_knowledge (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_answers_task_id
        ON tbl_knowledge_answers (task_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_answers_user_id
        ON tbl_knowledge_answers (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_chunks_knowledge_id
        ON tbl_knowledge_chunks (knowledge_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_chunks_task_id
        ON tbl_knowledge_chunks (task_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_chunks_user_id
        ON tbl_knowledge_chunks (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_feedback_answer_id
        ON tbl_knowledge_feedback (answer_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_knowledge_feedback_user_id
        ON tbl_knowledge_feedback (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_plan_answers_user_id
        ON tbl_plan_answers (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tbl_subtasks_user_id
        ON tbl_subtasks (user_id)
        """
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # SECURITY DEFINER helper must not be callable over PostgREST; guarded
        # so a Postgres without the helper still migrates.
        op.execute(
            """
            DO $$
            BEGIN
              EXECUTE 'REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated';
            EXCEPTION WHEN undefined_function THEN NULL;
            END $$;
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
              EXECUTE 'GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO anon, authenticated';
            EXCEPTION WHEN undefined_function THEN NULL;
            END $$;
            """
        )
    op.execute("DROP INDEX IF EXISTS ix_tbl_subtasks_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_plan_answers_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_feedback_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_feedback_answer_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_chunks_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_chunks_task_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_chunks_knowledge_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_answers_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_answers_task_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tbl_knowledge_task_id")
    op.execute("DROP INDEX IF EXISTS uq_tbl_knowledge_task_history")
