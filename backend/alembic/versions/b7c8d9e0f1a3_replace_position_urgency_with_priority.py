"""replace position urgency with priority and add category

Revision ID: b7c8d9e0f1a3
Revises: c8d9e0f1a2b3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


revision = "b7c8d9e0f1a3"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenant RLS is forced on this table. Data migrations run without a tenant
    # context, so temporarily disable RLS or the backfill silently updates 0 rows.
    op.execute('ALTER TABLE "positions" DISABLE ROW LEVEL SECURITY')

    position_category = ENUM(
        "UNCATEGORIZED",
        "CAMPUS",
        "DOMESTIC_FUNCTIONAL",
        "DOMESTIC_RD",
        "OVERSEAS",
        "EXECUTIVE_EXPERT",
        name="positioncategory",
        create_type=False,
    )
    position_category.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "positions",
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "positions",
        sa.Column(
            "category",
            position_category,
            server_default="UNCATEGORIZED",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE positions
        SET priority = CASE urgency::text
            WHEN 'LOW' THEN 1
            WHEN 'MEDIUM' THEN 3
            WHEN 'HIGH' THEN 4
            WHEN 'URGENT' THEN 5
            ELSE 3
        END
        """
    )
    op.create_check_constraint(
        "ck_positions_priority_range",
        "positions",
        "priority BETWEEN 1 AND 5",
    )
    op.drop_column("positions", "urgency")
    op.execute("DROP TYPE IF EXISTS positionurgency")
    op.execute('ALTER TABLE "positions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.execute('ALTER TABLE "positions" DISABLE ROW LEVEL SECURITY')

    position_urgency = ENUM(
        "LOW", "MEDIUM", "HIGH", "URGENT", name="positionurgency", create_type=False
    )
    position_urgency.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "positions",
        sa.Column("urgency", position_urgency, server_default="MEDIUM", nullable=False),
    )
    op.execute(
        """
        UPDATE positions
        SET urgency = CASE
            WHEN priority <= 1 THEN 'LOW'::positionurgency
            WHEN priority <= 3 THEN 'MEDIUM'::positionurgency
            WHEN priority = 4 THEN 'HIGH'::positionurgency
            ELSE 'URGENT'::positionurgency
        END
        """
    )
    op.drop_constraint("ck_positions_priority_range", "positions", type_="check")
    op.drop_column("positions", "category")
    op.drop_column("positions", "priority")
    op.execute("DROP TYPE IF EXISTS positioncategory")
    op.execute('ALTER TABLE "positions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" FORCE ROW LEVEL SECURITY')
