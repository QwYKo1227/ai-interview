"""backfill HC slot assignment times from position creation

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

from alembic import op


revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "recruitment_hc_slots" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" DISABLE ROW LEVEL SECURITY')
    op.execute(
        """
        UPDATE recruitment_hc_slots AS slot
        SET assigned_at = position.created_at AT TIME ZONE 'UTC'
        FROM positions AS position
        WHERE slot.tenant_id = position.tenant_id
          AND slot.position_id = position.id
        """
    )
    op.execute('ALTER TABLE "positions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.execute('ALTER TABLE "recruitment_hc_slots" DISABLE ROW LEVEL SECURITY')
    op.execute("UPDATE recruitment_hc_slots SET assigned_at = created_at")
    op.execute('ALTER TABLE "recruitment_hc_slots" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" FORCE ROW LEVEL SECURITY')
