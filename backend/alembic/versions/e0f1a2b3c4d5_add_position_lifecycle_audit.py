"""add position lifecycle audit and soft deletion

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE positionstatus ADD VALUE IF NOT EXISTS 'PAUSED'")
    op.execute("ALTER TYPE positionstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")

    op.add_column("positions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("positions", sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("positions", sa.Column("delete_reason", sa.Text(), nullable=True))
    op.execute(
        """
        ALTER TABLE positions
        ADD CONSTRAINT fk_positions_deleted_by_tenant
        FOREIGN KEY (tenant_id, deleted_by)
        REFERENCES users (tenant_id, id)
        ON DELETE SET NULL (deleted_by)
        """
    )
    op.create_index("ix_positions_deleted_at", "positions", ["deleted_at"])

    position_event_type = postgresql.ENUM(
        "INITIAL_STATUS",
        "STATUS_BASELINE",
        "STATUS_CHANGED",
        "INITIAL_OWNER",
        "OWNER_CHANGED",
        "SOFT_DELETED",
        "RESTORED",
        name="positioneventtype",
        create_type=False,
    )
    position_event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "position_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", position_event_type, nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_position_events_position_id_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_position_events_tenant_id_id"),
    )
    op.execute(
        """
        ALTER TABLE position_events
        ADD CONSTRAINT fk_position_events_actor_id_tenant
        FOREIGN KEY (tenant_id, actor_id)
        REFERENCES users (tenant_id, id)
        ON DELETE SET NULL (actor_id)
        """
    )
    op.create_index("ix_position_events_tenant_id", "position_events", ["tenant_id"])
    op.create_index("ix_position_events_position_id", "position_events", ["position_id"])
    op.create_index("ix_position_events_event_type", "position_events", ["event_type"])
    op.create_index("ix_position_events_occurred_at", "position_events", ["occurred_at"])

    # Forced tenant RLS prevents migration-wide baselines from seeing rows.
    op.execute('ALTER TABLE "positions" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "users" DISABLE ROW LEVEL SECURITY')
    op.execute(
        """
        INSERT INTO position_events (
            id, tenant_id, position_id, event_type, old_value, new_value,
            actor_id, actor_name, reason, occurred_at, event_metadata
        )
        SELECT
            gen_random_uuid(), tenant_id, id, 'STATUS_BASELINE', NULL, status::text,
            NULL, NULL, '历史数据基线', CURRENT_TIMESTAMP, '{"backfilled": true}'::json
        FROM positions
        """
    )
    op.execute(
        """
        INSERT INTO position_events (
            id, tenant_id, position_id, event_type, old_value, new_value,
            actor_id, actor_name, reason, occurred_at, event_metadata
        )
        SELECT
            gen_random_uuid(), p.tenant_id, p.id, 'INITIAL_OWNER', NULL,
            COALESCE(p.hiring_manager_history::jsonb->0->>'old_owner_id', p.hiring_manager_id::text),
            NULL, NULL, '历史负责人基线', p.created_at AT TIME ZONE 'UTC',
            '{"backfilled": true}'::json
        FROM positions p
        WHERE COALESCE(p.hiring_manager_history::jsonb->0->>'old_owner_id', p.hiring_manager_id::text) IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO position_events (
            id, tenant_id, position_id, event_type, old_value, new_value,
            actor_id, actor_name, reason, occurred_at, event_metadata
        )
        SELECT
            gen_random_uuid(), p.tenant_id, p.id, 'OWNER_CHANGED',
            item.value->>'old_owner_id', item.value->>'new_owner_id',
            actor.id, COALESCE(actor.full_name, actor.email), item.value->>'reason',
            (item.value->>'changed_at')::timestamptz, '{"backfilled": true}'::json
        FROM positions p
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(p.hiring_manager_history::jsonb, '[]'::jsonb))
            WITH ORDINALITY AS item(value, ordinal)
        LEFT JOIN users actor
            ON actor.tenant_id = p.tenant_id
            AND actor.id = NULLIF(item.value->>'actor_id', '')::uuid
        """
    )
    op.execute('ALTER TABLE "users" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "users" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "positions" FORCE ROW LEVEL SECURITY')

    op.execute('ALTER TABLE "position_events" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "position_events" FORCE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY position_events_tenant_isolation
        ON position_events
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT ON TABLE position_events TO app_runtime")


def downgrade() -> None:
    op.drop_table("position_events")
    op.execute("DROP TYPE IF EXISTS positioneventtype")
    op.drop_index("ix_positions_deleted_at", table_name="positions")
    op.drop_constraint("fk_positions_deleted_by_tenant", "positions", type_="foreignkey")
    op.drop_column("positions", "delete_reason")
    op.drop_column("positions", "deleted_by")
    op.drop_column("positions", "deleted_at")
    # PostgreSQL enum values are intentionally retained for safe rollback.
