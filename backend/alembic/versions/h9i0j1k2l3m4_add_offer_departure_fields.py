"""add offer departure registration fields

Revision ID: h9i0j1k2l3m4
Revises: g8b9c0d1e2f4
"""

import sqlalchemy as sa
from alembic import op


revision = "h9i0j1k2l3m4"
down_revision = "g8b9c0d1e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE offerstatus ADD VALUE IF NOT EXISTS 'DEPARTED'")
    op.add_column("offers", sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("offers", sa.Column("departure_recorded_by", sa.UUID(), nullable=True))
    op.add_column("offers", sa.Column("departure_reason", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("departure_released_hc", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("offers", "departure_released_hc")
    op.drop_column("offers", "departure_reason")
    op.drop_column("offers", "departure_recorded_by")
    op.drop_column("offers", "departed_at")
    # PostgreSQL enum values cannot be removed safely while rows may reference them.
