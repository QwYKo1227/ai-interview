"""Add durable department review history fields.

Revision ID: f7a8b9c0d1e3
Revises: e6f7a8b9c0d1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "f7a8b9c0d1e3"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "department_reviews",
        sa.Column("reviewed_position_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "department_reviews",
        sa.Column("reviewed_position_title", sa.String(), nullable=True),
    )
    op.add_column(
        "department_reviews",
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.execute(
        """
        UPDATE department_reviews AS review
        SET reviewed_position_id = resume.position_id,
            reviewed_position_title = position.title,
            completed_at = CASE
                WHEN review.is_completed THEN COALESCE(review.updated_at, review.created_at)
                ELSE NULL
            END
        FROM resumes AS resume
        LEFT JOIN positions AS position
          ON position.id = resume.position_id
         AND position.tenant_id = resume.tenant_id
        WHERE review.resume_id = resume.id
          AND review.tenant_id = resume.tenant_id
        """
    )


def downgrade() -> None:
    op.drop_column("department_reviews", "completed_at")
    op.drop_column("department_reviews", "reviewed_position_title")
    op.drop_column("department_reviews", "reviewed_position_id")
