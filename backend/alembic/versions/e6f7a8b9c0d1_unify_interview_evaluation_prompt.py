"""Unify interview evaluation prompt configuration.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

from alembic import op


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "system_configs" DISABLE ROW LEVEL SECURITY')
    op.execute(
        """
        UPDATE system_configs
        SET prompt_configs = (
            COALESCE(prompt_configs::jsonb, '{}'::jsonb)
            - 'generate_interview_evaluation'
            - 'generate_interview_evaluation_from_transcript'
        )::json
        """
    )
    op.execute('ALTER TABLE "system_configs" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "system_configs" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Removed tenant-specific prompts cannot be reconstructed safely.
    pass
