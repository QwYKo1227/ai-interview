"""Map legacy HC round starts to their position creation times.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from alembic import op


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("recruitment_hc_slots", "positions", "position_events"):
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    op.execute(
        """
        UPDATE recruitment_hc_slots AS slot
        SET round_started_at = position.created_at AT TIME ZONE 'UTC'
        FROM positions AS position
        WHERE slot.tenant_id = position.tenant_id
          AND slot.position_id = position.id
          AND slot.round_started_at = slot.created_at
          AND slot.round_started_at <> position.created_at AT TIME ZONE 'UTC'
          AND EXISTS (
              SELECT 1
              FROM position_events AS event
              WHERE event.tenant_id = slot.tenant_id
                AND event.position_id = slot.position_id
                AND event.event_type = 'STATUS_BASELINE'
                AND event.occurred_at = slot.round_started_at
          )
        """
    )

    for table in ("position_events", "positions", "recruitment_hc_slots"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # The deployment-time baseline timestamp is not domain data and cannot be
    # reconstructed safely after the repair. Keep the corrected round start.
    pass
