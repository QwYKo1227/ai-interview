"""add durable asynchronous ASR job state

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "v1w2x3y4z5a6"
down_revision = "u0v1w2x3y4z5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("interviews", sa.Column("asr_job_id", sa.String(), nullable=True))
    op.add_column(
        "interviews",
        sa.Column("asr_job_status", sa.String(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "interviews",
        sa.Column("asr_job_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "interviews",
        sa.Column("asr_job_next_poll_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "asr_job_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "interviews",
        sa.Column("asr_job_delete_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    for name in [
        "asr_job_delete_pending",
        "asr_job_history",
        "asr_job_next_poll_at",
        "asr_job_attempts",
        "asr_job_status",
        "asr_job_id",
    ]:
        op.drop_column("interviews", name)
