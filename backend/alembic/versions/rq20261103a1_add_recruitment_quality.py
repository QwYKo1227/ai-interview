"""Versioned recruitment process quality and immutable audit trail.

Revision ID: rq20261103a1
Revises: l3m4n5o6p7q8
"""
from alembic import op
import sqlalchemy as sa
from app.models.tenant_constraints import TenantForeignKeyConstraint

revision = "rq20261103a1"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None

TABLES = ("recruitment_quality_policies", "recruitment_quality_bindings", "recruitment_quality_actions")


def common(name):
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id")]


def reference(table, column, target):
    return sa.ForeignKeyConstraint(["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=f"fk_{table}_{column}_tenant")


def upgrade():
    p, b, a = TABLES
    op.create_table(p, *common(p),
        sa.Column("position_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "version", name="uq_quality_policy_version"),
        reference(p, "position_id", "positions"), reference(p, "created_by", "users"))
    op.create_table(b, *common(b),
        sa.Column("subject_key", sa.String(100), nullable=False),
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=True),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "subject_key", name="uq_quality_binding_subject"),
        reference(b, "position_id", "positions"),
        TenantForeignKeyConstraint(["tenant_id", "resume_id"], ["resumes.tenant_id", "resumes.id"],
            name=f"fk_{b}_resume_id_tenant", ondelete="SET NULL", postgresql_set_null_columns=("resume_id",)),
        reference(b, "policy_id", p))
    op.create_table(a, *common(a),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("node_key", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        reference(a, "binding_id", b), reference(a, "actor_id", "users"))
    for table, columns in ((b, ["position_id", "resume_id"]), (a, ["binding_id"])):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f"""CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)""")
            op.execute(f"GRANT SELECT, INSERT ON TABLE {table} TO app_runtime")


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
