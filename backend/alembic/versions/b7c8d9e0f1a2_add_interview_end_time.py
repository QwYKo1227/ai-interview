"""add interview end time

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("interview_end_time", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interviews", "interview_end_time")
