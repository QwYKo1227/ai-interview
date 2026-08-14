"""grant runtime access to offer decision audits

Revision ID: d9e0f1a2b3c4
Revises: b7c8d9e0f1a3
"""

from alembic import op


revision = "d9e0f1a2b3c4"
down_revision = "b7c8d9e0f1a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON TABLE offer_decision_audits TO app_runtime"
    )


def downgrade() -> None:
    # Keep the runtime grant: the audit-backed decision endpoint exists in the
    # preceding revisions and would otherwise become unusable again.
    pass
