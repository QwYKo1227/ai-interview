"""Add department review email reminder cooldown timestamp.

Revision ID: g8b9c0d1e2f4
Revises: f7a8b9c0d1e3
"""

import sqlalchemy as sa
from alembic import op


revision = "g8b9c0d1e2f4"
down_revision = "f7a8b9c0d1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "department_reviews",
        sa.Column("last_reminded_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("department_reviews", "last_reminded_at")
