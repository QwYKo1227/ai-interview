"""add immutable internal offer decision audit trail

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_decision_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(), nullable=False),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.Column("rejection_detail", sa.Text(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "offer_id"],
            ["offers.tenant_id", "offers.id"],
            name="fk_offer_decision_audits_offer_id_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["users.tenant_id", "users.id"],
            name="fk_offer_decision_audits_actor_id_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_offer_decision_audits_tenant_id_id"),
    )
    op.create_index(
        "ix_offer_decision_audits_tenant_id",
        "offer_decision_audits",
        ["tenant_id"],
    )
    op.create_index(
        "ix_offer_decision_audits_offer_id",
        "offer_decision_audits",
        ["offer_id"],
    )
    op.execute('ALTER TABLE "offer_decision_audits" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "offer_decision_audits" FORCE ROW LEVEL SECURITY')
    op.execute(
        '''
        CREATE POLICY "offer_decision_audits_tenant_isolation"
        ON "offer_decision_audits"
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        '''
    )


def downgrade() -> None:
    op.drop_table("offer_decision_audits")
