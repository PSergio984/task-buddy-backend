"""add_performance_indexes

Revision ID: ed27f78207cd
Revises: b09a9405a8af
Create Date: 2026-05-16 15:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ed27f78207cd'
down_revision: str | None = '4f7c8440bd82'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # tbl_tasks
    op.create_index(op.f('ix_tbl_tasks_user_id'), 'tbl_tasks', ['user_id'], unique=False)
    op.create_index(op.f('ix_tbl_tasks_project_id'), 'tbl_tasks', ['project_id'], unique=False)

    # tbl_projects
    op.create_index(op.f('ix_tbl_projects_user_id'), 'tbl_projects', ['user_id'], unique=False)

    # tbl_tags
    op.create_index(op.f('ix_tbl_tags_user_id'), 'tbl_tags', ['user_id'], unique=False)

    # tbl_subtasks
    op.create_index(op.f('ix_tbl_subtasks_task_id'), 'tbl_subtasks', ['task_id'], unique=False)

    # tbl_audit_logs
    op.create_index(op.f('ix_tbl_audit_logs_user_id'), 'tbl_audit_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_tbl_audit_logs_created_at'), 'tbl_audit_logs', ['created_at'], unique=False)

    # tbl_notifications
    op.create_index(op.f('ix_tbl_notifications_user_id'), 'tbl_notifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_tbl_notifications_created_at'), 'tbl_notifications', ['created_at'], unique=False)

    # tbl_push_subscriptions
    op.create_index(op.f('ix_tbl_push_subscriptions_user_id'), 'tbl_push_subscriptions', ['user_id'], unique=False)

    # tbl_task_tags
    op.create_index(op.f('ix_tbl_task_tags_tag_id'), 'tbl_task_tags', ['tag_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tbl_task_tags_tag_id'), table_name='tbl_task_tags')
    op.drop_index(op.f('ix_tbl_push_subscriptions_user_id'), table_name='tbl_push_subscriptions')
    op.drop_index(op.f('ix_tbl_notifications_created_at'), table_name='tbl_notifications')
    op.drop_index(op.f('ix_tbl_notifications_user_id'), table_name='tbl_notifications')
    op.drop_index(op.f('ix_tbl_audit_logs_created_at'), table_name='tbl_audit_logs')
    op.drop_index(op.f('ix_tbl_audit_logs_user_id'), table_name='tbl_audit_logs')
    op.drop_index(op.f('ix_tbl_subtasks_task_id'), table_name='tbl_subtasks')
    op.drop_index(op.f('ix_tbl_tags_user_id'), table_name='tbl_tags')
    op.drop_index(op.f('ix_tbl_projects_user_id'), table_name='tbl_projects')
    op.drop_index(op.f('ix_tbl_tasks_project_id'), table_name='tbl_tasks')
    op.drop_index(op.f('ix_tbl_tasks_user_id'), table_name='tbl_tasks')
