"""add tenant-specific ASR configuration

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
"""

from alembic import op
import sqlalchemy as sa


revision = "t9u0v1w2x3y4"
down_revision = "s8t9u0v1w2x3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "system_configs",
        sa.Column(
            "asr_provider",
            sa.String(),
            nullable=False,
            server_default="openai_compatible",
        ),
    )
    op.add_column("system_configs", sa.Column("asr_base_url", sa.String(), nullable=True))
    op.add_column(
        "system_configs",
        sa.Column(
            "asr_model",
            sa.String(),
            nullable=False,
            server_default="paraformer-offline",
        ),
    )
    op.add_column("system_configs", sa.Column("asr_api_key", sa.String(), nullable=True))


def downgrade():
    op.drop_column("system_configs", "asr_api_key")
    op.drop_column("system_configs", "asr_model")
    op.drop_column("system_configs", "asr_base_url")
    op.drop_column("system_configs", "asr_provider")
