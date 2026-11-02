"""game_events_client_ts_idx

Revision ID: c8d4e6f0a2b4
Revises: b64a2c1e9f03
Create Date: 2026-06-01 00:00:01.000000

Event-index rider for the character work (issue #64): ingest applies each
batch in (user_id, client_ts) order — this composite index keeps that sort
(and timeline reads that range-scan client_ts) off the seq-scan path.
Schema-only and reversible; the model mirrors it in
GameEvent.__table_args__.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d4e6f0a2b4"
down_revision: Union[str, Sequence[str], None] = "b64a2c1e9f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_game_events_user_client_ts",
        "tbl_game_events",
        ["user_id", "client_ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_events_user_client_ts", table_name="tbl_game_events")
