"""add multi-tenant foundation

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-07-21

"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "l1m2n3o4p5q6"
down_revision: Union[str, None] = "k0l1m2n3o4p5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_TENANT_CODE = "careray"
# Tenant.status is a non-native SQLAlchemy Enum configured with enum values,
# so PostgreSQL stores the lowercase value rather than the enum member name.
DEFAULT_TENANT_STATUS = "active"

TENANT_TABLES = (
    "users",
    "positions",
    "question_banks",
    "resumes",
    "department_reviews",
    "interviews",
    "interview_panels",
    "offers",
    "offer_templates",
    "coding_tests",
    "coding_submissions",
    "system_configs",
    "workflows",
    "workflow_nodes",
    "workflow_edges",
    "workflow_executions",
    "workflow_node_executions",
)

GLOBAL_TABLES = (
    "tenants",
    "tenant_domains",
    "platform_users",
    "platform_audit_logs",
    "public_access_tokens",
)


def _create_global_tables(existing_tables: set[str]) -> None:
    if "tenants" not in existing_tables:
        op.create_table(
            "tenants",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "status",
                sa.Enum(
                    "active",
                    "disabled",
                    name="tenantstatus",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=False,
            ),
            sa.Column("logo_url", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_tenants_code", "tenants", ["code"], unique=True)
        existing_tables.add("tenants")

    if "tenant_domains" not in existing_tables:
        op.create_table(
            "tenant_domains",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("domain", sa.String(255), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("domain", name="uq_tenant_domains_domain"),
        )
        op.create_index(
            "ix_tenant_domains_tenant_id",
            "tenant_domains",
            ["tenant_id"],
            unique=False,
        )
        op.create_index(
            "uq_tenant_domains_primary_per_tenant",
            "tenant_domains",
            ["tenant_id"],
            unique=True,
            postgresql_where=sa.text("is_primary"),
        )
        existing_tables.add("tenant_domains")

    if "platform_users" not in existing_tables:
        op.create_table(
            "platform_users",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_platform_users_email", "platform_users", ["email"], unique=True
        )
        existing_tables.add("platform_users")

    if "platform_audit_logs" not in existing_tables:
        op.create_table(
            "platform_audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column(
                "target_tenant_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["actor_id"], ["platform_users.id"]),
            sa.ForeignKeyConstraint(["target_tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_platform_audit_logs_actor_id",
            "platform_audit_logs",
            ["actor_id"],
            unique=False,
        )
        op.create_index(
            "ix_platform_audit_logs_target_tenant_id",
            "platform_audit_logs",
            ["target_tenant_id"],
            unique=False,
        )
        existing_tables.add("platform_audit_logs")

    if "public_access_tokens" not in existing_tables:
        op.create_table(
            "public_access_tokens",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_public_access_tokens_token_hash",
            "public_access_tokens",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            "ix_public_access_tokens_tenant_id",
            "public_access_tokens",
            ["tenant_id"],
            unique=False,
        )
        op.create_index(
            "ix_public_access_tokens_resource_id",
            "public_access_tokens",
            ["resource_id"],
            unique=False,
        )
        existing_tables.add("public_access_tokens")


def _default_tenant_id(bind) -> uuid.UUID:
    tenant_id = bind.execute(
        sa.text("SELECT id FROM tenants WHERE code = :code").bindparams(
            code=DEFAULT_TENANT_CODE
        )
    ).scalar_one_or_none()
    if tenant_id is not None:
        return tenant_id

    tenant_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO tenants "
            "(id, code, name, status, created_at, updated_at) "
            "VALUES (:id, :code, :name, :status, now(), now())"
        ).bindparams(
            sa.bindparam("id", value=tenant_id, type_=postgresql.UUID(as_uuid=True)),
            code=DEFAULT_TENANT_CODE,
            name="CareRay",
            status=DEFAULT_TENANT_STATUS,
        )
    )
    return tenant_id


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_map(inspector, table_name: str) -> dict[str, dict]:
    return {index["name"]: index for index in inspector.get_indexes(table_name)}


def _unique_constraint_map(inspector, table_name: str) -> dict[str, dict]:
    return {
        constraint["name"]: constraint
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint["name"]
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Global tables are migration-owned but may already exist in installations
    # that bootstrapped metadata directly before this Alembic revision existed.
    _create_global_tables(existing_tables)
    default_tenant_id = _default_tenant_id(bind)

    # Add every nullable ownership column before backfilling any table.
    scoped_tables = [table for table in TENANT_TABLES if table in existing_tables]
    inspector = sa.inspect(bind)
    for table in scoped_tables:
        if "tenant_id" not in _column_names(inspector, table):
            op.add_column(
                table,
                sa.Column(
                    "tenant_id", postgresql.UUID(as_uuid=True), nullable=True
                ),
            )

    # Backfill all legacy rows to the one reusable default tenant.
    for table in scoped_tables:
        bind.execute(
            sa.text(
                f'UPDATE "{table}" '
                "SET tenant_id = :tenant_id WHERE tenant_id IS NULL"
            ).bindparams(
                sa.bindparam(
                    "tenant_id",
                    value=default_tenant_id,
                    type_=postgresql.UUID(as_uuid=True),
                )
            )
        )

    # Only after the data is owned do we add tenant indexes and constraints.
    inspector = sa.inspect(bind)
    for table in scoped_tables:
        foreign_keys = inspector.get_foreign_keys(table)
        if not any(fk["constrained_columns"] == ["tenant_id"] for fk in foreign_keys):
            op.create_foreign_key(
                f"fk_{table}_tenant_id_tenants",
                table,
                "tenants",
                ["tenant_id"],
                ["id"],
            )

        tenant_index = f"ix_{table}_tenant_id"
        if tenant_index not in _index_map(inspector, table):
            op.create_index(tenant_index, table, ["tenant_id"], unique=False)

    if "users" in scoped_tables:
        inspector = sa.inspect(bind)
        user_indexes = _index_map(inspector, "users")
        if user_indexes.get("ix_users_email", {}).get("unique"):
            op.drop_index("ix_users_email", table_name="users")
            op.create_index("ix_users_email", "users", ["email"], unique=False)

        user_uniques = _unique_constraint_map(inspector, "users")
        for name, constraint in user_uniques.items():
            if constraint["column_names"] == ["email"]:
                op.drop_constraint(name, "users", type_="unique")

        user_uniques = _unique_constraint_map(sa.inspect(bind), "users")
        if "uq_users_tenant_email" not in user_uniques:
            op.create_unique_constraint(
                "uq_users_tenant_email", "users", ["tenant_id", "email"]
            )
        if "uq_users_tenant_id_id" not in user_uniques:
            op.create_unique_constraint(
                "uq_users_tenant_id_id", "users", ["tenant_id", "id"]
            )

    if "system_configs" in scoped_tables:
        system_uniques = _unique_constraint_map(sa.inspect(bind), "system_configs")
        if "uq_system_configs_singleton_key" in system_uniques:
            op.drop_constraint(
                "uq_system_configs_singleton_key", "system_configs", type_="unique"
            )
        system_checks = {
            constraint["name"]
            for constraint in sa.inspect(bind).get_check_constraints("system_configs")
        }
        if "ck_system_configs_singleton_key_true" in system_checks:
            op.drop_constraint(
                "ck_system_configs_singleton_key_true", "system_configs", type_="check"
            )
        if "uq_system_configs_tenant" not in _unique_constraint_map(
            sa.inspect(bind), "system_configs"
        ):
            op.create_unique_constraint(
                "uq_system_configs_tenant", "system_configs", ["tenant_id"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "tenants" in existing_tables:
        other_tenant_count = bind.execute(
            sa.text("SELECT count(*) FROM tenants WHERE code <> :code").bindparams(
                code=DEFAULT_TENANT_CODE
            )
        ).scalar_one()
        if other_tenant_count:
            raise RuntimeError(
                "Cannot downgrade multi-tenant foundation while non-careray "
                "tenants exist"
            )

    scoped_tables = [table for table in TENANT_TABLES if table in existing_tables]

    if "system_configs" in scoped_tables:
        system_uniques = _unique_constraint_map(sa.inspect(bind), "system_configs")
        if "uq_system_configs_tenant" in system_uniques:
            op.drop_constraint(
                "uq_system_configs_tenant", "system_configs", type_="unique"
            )

    if "users" in scoped_tables:
        user_uniques = _unique_constraint_map(sa.inspect(bind), "users")
        for name in ("uq_users_tenant_email", "uq_users_tenant_id_id"):
            if name in user_uniques:
                op.drop_constraint(name, "users", type_="unique")

    inspector = sa.inspect(bind)
    for table in reversed(scoped_tables):
        if "tenant_id" not in _column_names(inspector, table):
            continue
        tenant_index = f"ix_{table}_tenant_id"
        if tenant_index in _index_map(inspector, table):
            op.drop_index(tenant_index, table_name=table)
        for foreign_key in inspector.get_foreign_keys(table):
            if (
                foreign_key["constrained_columns"] == ["tenant_id"]
                and foreign_key["name"]
            ):
                op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    if "users" in scoped_tables:
        user_indexes = _index_map(sa.inspect(bind), "users")
        if "ix_users_email" in user_indexes:
            op.drop_index("ix_users_email", table_name="users")
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "system_configs" in scoped_tables:
        op.create_unique_constraint(
            "uq_system_configs_singleton_key",
            "system_configs",
            ["singleton_key"],
        )
        op.create_check_constraint(
            "ck_system_configs_singleton_key_true",
            "system_configs",
            "singleton_key IS TRUE",
        )

    for table in reversed(GLOBAL_TABLES):
        if table in existing_tables:
            op.drop_table(table)
