"""add the published position status used by the runtime model

Revision ID: p5q6r7s8t9u0
Revises: o4p5q6r7s8t9
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "p5q6r7s8t9u0"
down_revision: Union[str, None] = "o4p5q6r7s8t9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE positionstatus ADD VALUE IF NOT EXISTS 'PUBLISHED'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum label without rebuilding the type.  Keep
    # the compatibility label so rollback never destroys published positions.
    pass
