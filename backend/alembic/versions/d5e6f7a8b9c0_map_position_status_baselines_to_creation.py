"""Map historical position status baselines to position creation times.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

from alembic import op


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("position_events", "positions"):
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    op.execute(
        """
        UPDATE position_events AS event
        SET occurred_at = position.created_at AT TIME ZONE 'UTC'
        FROM positions AS position
        WHERE event.tenant_id = position.tenant_id
          AND event.position_id = position.id
          AND event.event_type = 'STATUS_BASELINE'
          AND event.occurred_at <> position.created_at AT TIME ZONE 'UTC'
        """
    )

    for table in ("positions", "position_events"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # The deployment timestamp used for the historical baseline was not a
    # business event and cannot be reconstructed safely after correction.
    pass
