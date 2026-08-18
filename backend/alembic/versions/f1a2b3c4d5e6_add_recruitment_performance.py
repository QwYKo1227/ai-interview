"""add recruitment performance management

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


TABLES = (
    "recruitment_performance_configs",
    "recruitment_hc_slots",
    "recruitment_pauses",
    "resume_status_events",
    "recruitment_settlements",
)

APPEND_ONLY_TABLES = {
    "recruitment_performance_configs",
    "resume_status_events",
    "recruitment_settlements",
}


def _tenant_table(name: str) -> None:
    op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
    op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {name}_tenant_isolation ON {name}
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
        """
    )
    privileges = "SELECT, INSERT" if name in APPEND_ONLY_TABLES else "SELECT, INSERT, UPDATE, DELETE"
    op.execute(f"GRANT {privileges} ON TABLE {name} TO app_runtime")


def upgrade() -> None:
    op.add_column("offers", sa.Column("actual_onboarded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("offers", sa.Column("onboarding_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True))

    def common():
        return [
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        ]
    op.create_table(
        "recruitment_performance_configs",
        *common(),
        sa.Column("effective_year", sa.Integer(), nullable=False),
        sa.Column("effective_quarter", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_days", sa.JSON(), nullable=False),
        sa.Column("time_coefficients", sa.JSON(), nullable=False),
        sa.Column("result_coefficients", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_recruitment_performance_configs_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "effective_year", "effective_quarter", "version", name="uq_recruitment_performance_config_period_version"),
    )
    op.create_table(
        "recruitment_hc_slots",
        *common(),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("round_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_resume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recruitment_round", sa.Integer(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "position_id"], ["positions.tenant_id", "positions.id"], name="fk_recruitment_hc_slots_position_id_tenant", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_recruitment_hc_slots_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "position_id", "slot_number", name="uq_recruitment_hc_slot_number"),
    )
    op.create_index("ix_recruitment_hc_slots_position_id", "recruitment_hc_slots", ["position_id"])
    op.create_table(
        "recruitment_pauses",
        *common(),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id", "slot_id"], ["recruitment_hc_slots.tenant_id", "recruitment_hc_slots.id"], name="fk_recruitment_pauses_slot_id_tenant", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_recruitment_pauses_tenant_id_id"),
    )
    op.create_index("ix_recruitment_pauses_slot_id", "recruitment_pauses", ["slot_id"])
    op.create_table(
        "resume_status_events",
        *common(),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_status", sa.String(), nullable=True),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "resume_id"], ["resumes.tenant_id", "resumes.id"], name="fk_resume_status_events_resume_id_tenant", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_resume_status_events_tenant_id_id"),
    )
    op.create_index("ix_resume_status_events_resume_id", "resume_status_events", ["resume_id"])
    op.create_index("ix_resume_status_events_occurred_at", "resume_status_events", ["occurred_at"])
    op.create_table(
        "recruitment_settlements",
        *common(),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("settled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_recruitment_settlements_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "period", "version", name="uq_recruitment_settlement_version"),
    )
    op.create_index("ix_recruitment_settlements_period", "recruitment_settlements", ["period"])

    op.execute('ALTER TABLE "positions" DISABLE ROW LEVEL SECURITY')
    op.execute(
        """
        INSERT INTO recruitment_hc_slots (
            id, tenant_id, position_id, slot_number, status, assigned_at,
            round_started_at, recruitment_round, created_at
        )
        SELECT gen_random_uuid(), p.tenant_id, p.id, slot_number, 'active',
               p.created_at AT TIME ZONE 'UTC', CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP
        FROM positions p
        CROSS JOIN LATERAL generate_series(1, GREATEST(COALESCE(p.headcount, 1), 1)) slot_number
        WHERE p.deleted_at IS NULL AND p.status::text NOT IN ('CLOSED', 'CANCELLED')
        """
    )
    op.execute('ALTER TABLE "positions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" FORCE ROW LEVEL SECURITY')

    for table in TABLES:
        _tenant_table(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("offers", "onboarding_confirmed_by")
    op.drop_column("offers", "actual_onboarded_at")
