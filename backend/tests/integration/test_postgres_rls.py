from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config.tenant_session import TenantCapableSession, TenantSession
from app.models.base import Base
from app.models.file_models import StoredFile
from app.models.models import Position, Resume, User, UserRole
from app.models.tenant_constraints import TenantForeignKeyConstraint
from app.models.workflow_models import Workflow
from app.schemas.tenant import TenantOnboardingRequest
from app.services.public_token_service import issue_public_token, resolve_public_token
from app.services.tenant_service import create_tenant_with_admin


BACKEND_DIR = Path(__file__).parents[2]
TENANT_TABLES = {
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
    "stored_files",
}
GLOBAL_TABLES = {
    "tenants",
    "tenant_domains",
    "platform_users",
    "platform_audit_logs",
    "public_access_tokens",
}
APPLICATION_TABLES = TENANT_TABLES | GLOBAL_TABLES
TEST_POSTGRES_CONTAINER = os.getenv(
    "TEST_POSTGRES_CONTAINER", "ai-interview-rls-test-postgres-1"
)


def _url_with_credentials(url: str, username: str, password: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or "localhost"
    host = f"[{hostname}]" if ":" in hostname else hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    netloc = f"{quote(username)}:{quote(password)}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _wait_for_postgres(url: str, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as exc:
            last_error = exc
            time.sleep(0.5)
        finally:
            engine.dispose()
    raise AssertionError(f"PostgreSQL test service did not become ready: {last_error}")


def _run_alembic(url: str, *arguments: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://ignored:ignored@127.0.0.1:1/ignored"
    env["MIGRATION_DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )


def _run_role_script() -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "exec",
            TEST_POSTGRES_CONTAINER,
            "sh",
            "/docker-entrypoint-initdb.d/01-app-roles.sh",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )


@pytest.fixture(scope="session")
def runtime_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL RLS integration tests")
    return url


@pytest.fixture(scope="session")
def migration_database_url(runtime_database_url: str) -> str:
    return os.getenv("TEST_MIGRATION_DATABASE_URL") or _url_with_credentials(
        runtime_database_url,
        "app_migration",
        "migration_test_password",
    )


@pytest.fixture(scope="session")
def admin_database_url(runtime_database_url: str) -> str:
    return _url_with_credentials(
        runtime_database_url,
        "postgres",
        "postgres_test_password",
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database(runtime_database_url: str, migration_database_url: str):
    _wait_for_postgres(migration_database_url)
    result = _run_alembic(migration_database_url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run_role_script()
    assert result.returncode == 0, result.stdout + result.stderr
    yield


@pytest.fixture(scope="session")
def runtime_engine(migrated_database, runtime_database_url: str):
    engine = create_engine(runtime_database_url, pool_size=1, max_overflow=0)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migration_engine(migrated_database, migration_database_url: str):
    engine = create_engine(migration_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def tenant_pair(migration_engine):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, code, name, status, created_at, updated_at) "
                "VALUES (:id, :code, :name, 'active', now(), now())"
            ),
            [
                {"id": tenant_a, "code": f"a-{tenant_a.hex}", "name": "Tenant A"},
                {"id": tenant_b, "code": f"b-{tenant_b.hex}", "name": "Tenant B"},
            ],
        )
    return tenant_a, tenant_b


@pytest.fixture
def pg_session_factory(runtime_engine):
    factory = sessionmaker(
        bind=runtime_engine,
        class_=TenantSession,
        autoflush=False,
        expire_on_commit=False,
    )

    @contextmanager
    def open_session(tenant_id):
        db = factory(tenant_id=tenant_id)
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    return open_session


def create_position(pg_session_factory, tenant_id, title):
    position_id = uuid.uuid4()
    with pg_session_factory(tenant_id) as db:
        db.execute(
            text(
                "INSERT INTO positions (id, tenant_id, title, description) "
                "VALUES (:id, :tenant_id, :title, :description)"
            ),
            {
                "id": position_id,
                "tenant_id": tenant_id,
                "title": title,
                "description": title,
            },
        )
        db.commit()
    return position_id


def create_position_orm(pg_session_factory, tenant_id, title):
    position_id = uuid.uuid4()
    with pg_session_factory(tenant_id) as db:
        position = Position(
            id=position_id,
            title=title,
            description=title,
        )
        db.add(position)
        db.commit()
        assert position.tenant_id == tenant_id
    return position_id


def test_rls_blocks_known_other_tenant_uuid_raw_sql(pg_session_factory, tenant_pair):
    tenant_a, tenant_b = tenant_pair
    position_b = create_position(pg_session_factory, tenant_b, "B")

    with pg_session_factory(tenant_a) as db:
        assert db.execute(
            text("SELECT id FROM positions WHERE id = :id"),
            {"id": position_b},
        ).first() is None


def test_rls_blocks_known_other_tenant_uuid_orm(pg_session_factory, tenant_pair):
    tenant_a, tenant_b = tenant_pair
    position_b = create_position(pg_session_factory, tenant_b, "B")

    with pg_session_factory(tenant_a) as db:
        assert db.query(Position).filter(Position.id == position_b).first() is None


def test_orm_crud_matrix_enforces_tenant_isolation(pg_session_factory, tenant_pair):
    tenant_a, tenant_b = tenant_pair
    own_id = create_position_orm(pg_session_factory, tenant_a, "own ORM row")
    foreign_update_id = create_position_orm(
        pg_session_factory, tenant_b, "foreign ORM update row"
    )
    foreign_delete_id = create_position_orm(
        pg_session_factory, tenant_b, "foreign ORM delete row"
    )

    with pg_session_factory(tenant_a) as db:
        own = db.query(Position).filter(Position.id == own_id).one()
        own.title = "own ORM row updated"
        db.commit()
        assert db.query(Position).filter(Position.id == own_id).one().title == (
            "own ORM row updated"
        )

        assert (
            db.query(Position)
            .filter(Position.id == foreign_update_id)
            .update({Position.title: "cross-tenant ORM hijack"}, synchronize_session=False)
        ) == 0
        assert (
            db.query(Position)
            .filter(Position.id == foreign_delete_id)
            .delete(synchronize_session=False)
        ) == 0
        db.commit()
        assert db.query(Position).filter(Position.id == foreign_update_id).first() is None
        assert db.query(Position).filter(Position.id == foreign_delete_id).first() is None

        with pytest.raises(ValueError, match="tenant_id does not match session tenant"):
            db.add(
                Position(
                    tenant_id=tenant_b,
                    title="cross-tenant ORM insert",
                    description="must fail",
                )
            )
        db.rollback()

        own = db.query(Position).filter(Position.id == own_id).one()
        db.delete(own)
        db.commit()
        assert db.query(Position).filter(Position.id == own_id).first() is None

    with pg_session_factory(tenant_b) as db:
        assert db.query(Position).filter(Position.id == foreign_update_id).one().title == (
            "foreign ORM update row"
        )
        foreign_delete = (
            db.query(Position).filter(Position.id == foreign_delete_id).one()
        )
        db.delete(foreign_delete)
        db.commit()
        assert db.query(Position).filter(Position.id == foreign_delete_id).first() is None


def test_rls_rejects_cross_tenant_insert(pg_session_factory, tenant_pair):
    tenant_a, tenant_b = tenant_pair

    with pytest.raises(DBAPIError):
        with pg_session_factory(tenant_a) as db:
            db.execute(
                text(
                    "INSERT INTO positions (id, tenant_id, title, description) "
                    "VALUES (:id, :tenant_b, 'X', 'X')"
                ),
                {"id": uuid.uuid4(), "tenant_b": tenant_b},
            )
            db.commit()


def test_rls_cross_tenant_update_and_delete_touch_zero_rows(
    pg_session_factory, tenant_pair
):
    tenant_a, tenant_b = tenant_pair
    update_target = create_position(pg_session_factory, tenant_b, "update target")
    delete_target = create_position(pg_session_factory, tenant_b, "delete target")

    with pg_session_factory(tenant_a) as db:
        updated = db.execute(
            text("UPDATE positions SET title = 'hijacked' WHERE id = :id"),
            {"id": update_target},
        )
        deleted = db.execute(
            text("DELETE FROM positions WHERE id = :id"),
            {"id": delete_target},
        )
        db.commit()
        assert updated.rowcount == 0
        assert deleted.rowcount == 0

    with pg_session_factory(tenant_b) as db:
        assert db.execute(
            text("SELECT title FROM positions WHERE id = :id"),
            {"id": update_target},
        ).scalar_one() == "update target"
        assert db.execute(
            text("SELECT count(*) FROM positions WHERE id = :id"),
            {"id": delete_target},
        ).scalar_one() == 1


def test_rls_fails_closed_for_missing_empty_and_invalid_tenant_guc(
    runtime_database_url, migrated_database, tenant_pair, pg_session_factory
):
    _tenant_a, tenant_b = tenant_pair
    position_b = create_position(pg_session_factory, tenant_b, "B")
    isolated_engine = create_engine(runtime_database_url, poolclass=NullPool)
    try:
        with isolated_engine.begin() as connection:
            assert connection.execute(
                text("SELECT id FROM positions WHERE id = :id"), {"id": position_b}
            ).first() is None

        with isolated_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.current_tenant_id', '', true)")
            )
            assert connection.execute(
                text("SELECT id FROM positions WHERE id = :id"), {"id": position_b}
            ).first() is None

        with pytest.raises(DBAPIError):
            with isolated_engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT set_config('app.current_tenant_id', "
                        "'definitely-not-a-uuid', true)"
                    )
                )
                connection.execute(text("SELECT id FROM positions LIMIT 1")).first()
    finally:
        isolated_engine.dispose()


def test_transaction_local_guc_does_not_leak_through_connection_pool(
    runtime_engine, pg_session_factory, tenant_pair
):
    tenant_a, tenant_b = tenant_pair
    position_a = create_position(pg_session_factory, tenant_a, "A")
    position_b = create_position(pg_session_factory, tenant_b, "B")

    with pg_session_factory(tenant_a) as first:
        first_pid = first.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        assert first.execute(
            text("SELECT id FROM positions WHERE id = :id"), {"id": position_a}
        ).scalar_one() == position_a

    with pg_session_factory(tenant_b) as second:
        second_pid = second.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        assert second_pid == first_pid
        assert second.execute(
            text("SELECT id FROM positions WHERE id = :id"), {"id": position_a}
        ).first() is None
        assert second.execute(
            text("SELECT id FROM positions WHERE id = :id"), {"id": position_b}
        ).scalar_one() == position_b


def test_every_tenant_table_has_forced_rls_policy_and_non_null_tenant_id(
    migration_engine,
):
    with migration_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "       a.attnotnull, p.polname "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' "
                "LEFT JOIN pg_policy p ON p.polrelid = c.oid "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(TENANT_TABLES)},
        ).mappings().all()

    assert {row["relname"] for row in rows} == TENANT_TABLES
    assert all(row["relrowsecurity"] for row in rows)
    assert all(row["relforcerowsecurity"] for row in rows)
    assert all(row["attnotnull"] for row in rows)
    assert {
        (row["relname"], row["polname"])
        for row in rows
    } == {
        (table, f"{table}_tenant_isolation") for table in TENANT_TABLES
    }


def test_platform_global_tables_are_not_subject_to_rls(migration_engine):
    with migration_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class JOIN pg_namespace ON pg_namespace.oid = relnamespace "
                "WHERE nspname = 'public' AND relname = ANY(:tables)"
            ),
            {"tables": list(GLOBAL_TABLES)},
        ).mappings().all()
    assert {row["relname"] for row in rows} == GLOBAL_TABLES
    assert not any(row["relrowsecurity"] for row in rows)
    assert not any(row["relforcerowsecurity"] for row in rows)


def test_composite_foreign_key_rejects_cross_tenant_reference(
    pg_session_factory, tenant_pair
):
    tenant_a, tenant_b = tenant_pair
    position_b = create_position(pg_session_factory, tenant_b, "B")

    with pytest.raises(DBAPIError):
        with pg_session_factory(tenant_a) as db:
            db.execute(
                text(
                    "INSERT INTO resumes (id, tenant_id, position_id) "
                    "VALUES (:id, :tenant_id, :position_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_a,
                    "position_id": position_b,
                },
            )
            db.commit()


def test_database_and_metadata_match_all_tenant_foreign_key_semantics(
    migration_engine,
):
    metadata_constraints = {
        (table.name, constraint.name): (
            tuple(foreign_key.parent.name for foreign_key in constraint.elements),
            constraint.elements[0].column.table.name,
            tuple(foreign_key.column.name for foreign_key in constraint.elements),
            constraint.ondelete,
            constraint.postgresql_set_null_columns,
        )
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, TenantForeignKeyConstraint)
    }
    with migration_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT child.relname AS child_table, c.conname, "
                "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum, pos) "
                "      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "      ORDER BY k.pos) AS child_columns, "
                "parent.relname AS parent_table, "
                "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum, pos) "
                "      JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum "
                "      ORDER BY k.pos) AS parent_columns, "
                "CASE c.confdeltype WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' "
                "     WHEN 'd' THEN 'SET DEFAULT' WHEN 'r' THEN 'RESTRICT' ELSE NULL END "
                "     AS ondelete, "
                "COALESCE(ARRAY(SELECT a.attname "
                "      FROM unnest(c.confdelsetcols) WITH ORDINALITY k(attnum, pos) "
                "      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "      ORDER BY k.pos), ARRAY[]::name[]) AS set_null_columns "
                "FROM pg_constraint c "
                "JOIN pg_class child ON child.oid = c.conrelid "
                "JOIN pg_class parent ON parent.oid = c.confrelid "
                "JOIN pg_namespace n ON n.oid = child.relnamespace "
                "WHERE c.contype = 'f' AND n.nspname = 'public' "
                "AND c.conname LIKE 'fk_%_tenant'"
            )
        ).mappings()
        database_constraints = {
            (row["child_table"], row["conname"]): (
                tuple(row["child_columns"]),
                row["parent_table"],
                tuple(row["parent_columns"]),
                row["ondelete"],
                tuple(row["set_null_columns"]),
            )
            for row in rows
        }

    assert len(metadata_constraints) == 29
    assert database_constraints == metadata_constraints


def test_deleting_rejector_clears_only_rejected_by_not_tenant_id(
    pg_session_factory, tenant_pair
):
    tenant_a, _tenant_b = tenant_pair
    rejector_id = uuid.uuid4()
    resume_id = uuid.uuid4()
    with pg_session_factory(tenant_a) as db:
        db.add(
            User(
                id=rejector_id,
                email=f"rejector-{rejector_id.hex}@example.com",
                hashed_password="not-used",
                full_name="Rejector",
                role=UserRole.HR,
            )
        )
        db.add(Resume(id=resume_id, rejected_by=rejector_id))
        db.commit()

        db.execute(text("DELETE FROM users WHERE id = :id"), {"id": rejector_id})
        db.commit()
        row = db.execute(
            text(
                "SELECT tenant_id, rejected_by FROM resumes WHERE id = :id"
            ),
            {"id": resume_id},
        ).one()

    assert row.tenant_id == tenant_a
    assert row.rejected_by is None


def test_runtime_role_has_only_runtime_privileges_and_cannot_bypass_rls(
    runtime_engine, migration_engine, tenant_pair, pg_session_factory
):
    _tenant_a, tenant_b = tenant_pair
    create_position(pg_session_factory, tenant_b, "B")
    with migration_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                "       rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = 'app_runtime'"
            )
        ).mappings().one()
        owners = connection.execute(
            text(
                "SELECT DISTINCT owner.rolname "
                "FROM pg_class c JOIN pg_roles owner ON owner.oid = c.relowner "
                "WHERE c.relname = ANY(:tables)"
            ),
            {"tables": list(TENANT_TABLES)},
        ).scalars().all()
        privileges = connection.execute(
            text(
                "SELECT "
                "has_database_privilege('app_runtime', current_database(), 'CONNECT'), "
                "has_database_privilege('app_runtime', current_database(), 'CREATE'), "
                "has_database_privilege('app_runtime', current_database(), 'TEMP'), "
                "has_schema_privilege('app_runtime', 'public', 'USAGE'), "
                "has_schema_privilege('app_runtime', 'public', 'CREATE'), "
                "has_table_privilege('app_runtime', 'positions', "
                "                    'SELECT,INSERT,UPDATE,DELETE'), "
                "has_table_privilege('app_runtime', 'positions', "
                "                    'TRUNCATE,REFERENCES,TRIGGER')"
            )
        ).one()
        table_privileges = {
            row.table_name: (row.has_dml, row.has_elevated)
            for row in connection.execute(
                text(
                    "SELECT table_name, "
                    "has_table_privilege('app_runtime', "
                    "                    quote_ident(table_schema) || '.' || "
                    "                    quote_ident(table_name), "
                    "                    'SELECT,INSERT,UPDATE,DELETE') AS has_dml, "
                    "has_table_privilege('app_runtime', "
                    "                    quote_ident(table_schema) || '.' || "
                    "                    quote_ident(table_name), "
                    "                    'TRUNCATE,REFERENCES,TRIGGER') AS has_elevated "
                    "FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
        }
        sequence_privileges = connection.execute(
            text(
                "SELECT sequence_name, "
                "has_sequence_privilege('app_runtime', "
                "                       quote_ident(sequence_schema) || '.' || "
                "                       quote_ident(sequence_name), 'USAGE'), "
                "has_sequence_privilege('app_runtime', "
                "                       quote_ident(sequence_schema) || '.' || "
                "                       quote_ident(sequence_name), 'SELECT') "
                "FROM information_schema.sequences WHERE sequence_schema = 'public'"
            )
        ).all()
        runtime_table_defaults = connection.execute(
            text(
                "SELECT count(*) FROM pg_default_acl d "
                "JOIN pg_namespace n ON n.oid = d.defaclnamespace, "
                "LATERAL aclexplode(COALESCE(d.defaclacl, acldefault(d.defaclobjtype, d.defaclrole))) acl "
                "JOIN pg_roles grantee ON grantee.oid = acl.grantee "
                "WHERE n.nspname = 'public' AND d.defaclobjtype = 'r' "
                "AND grantee.rolname = 'app_runtime'"
            )
        ).scalar_one()

    assert not any(role.values())
    assert "app_runtime" not in owners
    assert privileges == (True, False, False, True, False, True, False)
    assert set(table_privileges) == APPLICATION_TABLES | {"alembic_version"}
    assert all(
        table_privileges[table] == (True, False) for table in APPLICATION_TABLES
    )
    assert table_privileges["alembic_version"] == (False, False)
    assert all(
        not has_usage and not has_select
        for _, has_usage, has_select in sequence_privileges
    )
    assert runtime_table_defaults == 0

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            connection.execute(text("CREATE TABLE runtime_must_not_create (id int)"))

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            connection.execute(text("SET LOCAL row_security = off"))
            connection.execute(text("SELECT id FROM positions LIMIT 1")).first()


def test_migration_role_can_manage_schema_without_superuser_or_bypassrls(
    migration_engine,
):
    table_name = f"migration_probe_{uuid.uuid4().hex}"
    with migration_engine.begin() as connection:
        role = connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert role == (False, False)
        connection.execute(text(f'CREATE TABLE "{table_name}" (id integer)'))
        connection.execute(text(f'DROP TABLE "{table_name}"'))


def test_role_initialization_transfers_legacy_object_ownership_without_granting_runtime(
    migrated_database, admin_database_url, migration_database_url
):
    suffix = uuid.uuid4().hex
    names = {
        "table": f"legacy_table_{suffix}",
        "sequence": f"legacy_sequence_{suffix}",
        "enum": f"legacy_enum_{suffix}",
        "domain": f"legacy_domain_{suffix}",
    }
    admin_engine = create_engine(admin_database_url, poolclass=NullPool)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE "{names["table"]}" (id integer)'))
            connection.execute(text(f'CREATE SEQUENCE "{names["sequence"]}"'))
            connection.execute(text(f'CREATE TYPE "{names["enum"]}" AS ENUM (\'one\')'))
            connection.execute(text(f'CREATE DOMAIN "{names["domain"]}" AS text'))

        first = _run_role_script()
        second = _run_role_script()
        assert first.returncode == 0, first.stdout + first.stderr
        assert second.returncode == 0, second.stdout + second.stderr

        migration_engine = create_engine(migration_database_url, poolclass=NullPool)
        try:
            with migration_engine.begin() as connection:
                owners = dict(
                    connection.execute(
                        text(
                            "SELECT c.relname, owner.rolname FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "JOIN pg_roles owner ON owner.oid = c.relowner "
                            "WHERE n.nspname = 'public' AND c.relname = ANY(:names)"
                        ),
                        {"names": [names["table"], names["sequence"]]},
                    ).all()
                )
                type_owners = dict(
                    connection.execute(
                        text(
                            "SELECT t.typname, owner.rolname FROM pg_type t "
                            "JOIN pg_namespace n ON n.oid = t.typnamespace "
                            "JOIN pg_roles owner ON owner.oid = t.typowner "
                            "WHERE n.nspname = 'public' AND t.typname = ANY(:names)"
                        ),
                        {"names": [names["enum"], names["domain"]]},
                    ).all()
                )
                assert owners == {
                    names["table"]: "app_migration",
                    names["sequence"]: "app_migration",
                }
                assert type_owners == {
                    names["enum"]: "app_migration",
                    names["domain"]: "app_migration",
                }
                assert not connection.execute(
                    text(
                        "SELECT has_table_privilege('app_runtime', :table, "
                        "                           'SELECT,INSERT,UPDATE,DELETE')"
                    ),
                    {"table": f'public.{names["table"]}'},
                ).scalar_one()
                connection.execute(text(f'DROP TABLE "{names["table"]}"'))
                connection.execute(text(f'DROP SEQUENCE "{names["sequence"]}"'))
                connection.execute(text(f'DROP TYPE "{names["enum"]}"'))
                connection.execute(text(f'DROP DOMAIN "{names["domain"]}"'))
        finally:
            migration_engine.dispose()
    finally:
        admin_engine.dispose()


def test_role_initialization_revokes_only_application_role_memberships(
    migrated_database,
    admin_database_url,
    runtime_database_url,
    migration_database_url,
    pg_session_factory,
    tenant_pair,
):
    suffix = uuid.uuid4().hex
    probe_roles = {
        "owner": f"probe_owner_{suffix}",
        "super": f"probe_super_{suffix}",
        "bypass": f"probe_bypass_{suffix}",
        "other": f"probe_other_{suffix}",
    }
    unrelated_parent = f"unrelated_parent_{suffix}"
    unrelated_member = f"unrelated_member_{suffix}"
    owner_schema = f"probe_owner_schema_{suffix}"
    admin_engine = create_engine(admin_database_url, poolclass=NullPool)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{probe_roles["owner"]}" NOLOGIN'))
            connection.execute(
                text(f'CREATE ROLE "{probe_roles["super"]}" NOLOGIN SUPERUSER')
            )
            connection.execute(
                text(f'CREATE ROLE "{probe_roles["bypass"]}" NOLOGIN BYPASSRLS')
            )
            connection.execute(text(f'CREATE ROLE "{probe_roles["other"]}" NOLOGIN'))
            connection.execute(
                text(
                    f'CREATE SCHEMA "{owner_schema}" '
                    f'AUTHORIZATION "{probe_roles["owner"]}"'
                )
            )
            connection.execute(text(f'CREATE ROLE "{unrelated_parent}" NOLOGIN'))
            connection.execute(text(f'CREATE ROLE "{unrelated_member}" NOLOGIN'))
            for probe_role in probe_roles.values():
                connection.execute(text(f'GRANT "{probe_role}" TO app_runtime'))
                connection.execute(text(f'GRANT "{probe_role}" TO app_migration'))
            connection.execute(
                text(f'GRANT "{unrelated_parent}" TO "{unrelated_member}"')
            )

        role_result = _run_role_script()
        assert role_result.returncode == 0, role_result.stdout + role_result.stderr

        with admin_engine.connect() as connection:
            application_memberships = connection.execute(
                text(
                    "SELECT parent.rolname, member.rolname "
                    "FROM pg_auth_members membership "
                    "JOIN pg_roles parent ON parent.oid = membership.roleid "
                    "JOIN pg_roles member ON member.oid = membership.member "
                    "WHERE member.rolname IN ('app_runtime', 'app_migration')"
                )
            ).all()
            unrelated_membership = connection.execute(
                text(
                    "SELECT count(*) FROM pg_auth_members membership "
                    "JOIN pg_roles parent ON parent.oid = membership.roleid "
                    "JOIN pg_roles member ON member.oid = membership.member "
                    "WHERE parent.rolname = :parent AND member.rolname = :member"
                ),
                {"parent": unrelated_parent, "member": unrelated_member},
            ).scalar_one()
        assert application_memberships == []
        assert unrelated_membership == 1

        for database_url in (runtime_database_url, migration_database_url):
            engine = create_engine(database_url, poolclass=NullPool)
            try:
                for probe_role in probe_roles.values():
                    with pytest.raises(DBAPIError):
                        with engine.begin() as connection:
                            connection.execute(text(f'SET ROLE "{probe_role}"'))
            finally:
                engine.dispose()

        tenant_a, tenant_b = tenant_pair
        foreign_position_id = create_position_orm(
            pg_session_factory, tenant_b, "membership bypass probe"
        )
        with pg_session_factory(tenant_a) as db:
            assert db.query(Position).filter(
                Position.id == foreign_position_id
            ).first() is None
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{owner_schema}" CASCADE'))
            connection.execute(
                text(f'REVOKE "{unrelated_parent}" FROM "{unrelated_member}"')
            )
            for probe_role in probe_roles.values():
                connection.execute(
                    text(f'REVOKE "{probe_role}" FROM app_runtime')
                )
                connection.execute(
                    text(f'REVOKE "{probe_role}" FROM app_migration')
                )
            for role_name in [
                unrelated_member,
                unrelated_parent,
                *probe_roles.values(),
            ]:
                connection.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
        admin_engine.dispose()


def test_alembic_uses_migration_url_not_runtime_database_url(
    migration_database_url,
):
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://ignored:ignored@127.0.0.1:1/ignored"
    env["MIGRATION_DATABASE_URL"] = migration_database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "n3o4p5q6r7s8" in result.stdout


def test_alembic_autogenerate_has_no_head_metadata_drift(migration_database_url):
    result = _run_alembic(migration_database_url, "check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout


def test_alembic_comparator_detects_partial_set_null_catalog_drift(
    migration_engine, migration_database_url
):
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE resumes DROP CONSTRAINT fk_resumes_rejected_by_tenant"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE resumes ADD CONSTRAINT fk_resumes_rejected_by_tenant "
                "FOREIGN KEY (tenant_id, rejected_by) "
                "REFERENCES users (tenant_id, id) ON DELETE SET NULL"
            )
        )

    try:
        drift = _run_alembic(migration_database_url, "check")
        assert drift.returncode != 0
    finally:
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE resumes DROP CONSTRAINT fk_resumes_rejected_by_tenant"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE resumes ADD CONSTRAINT fk_resumes_rejected_by_tenant "
                    "FOREIGN KEY (tenant_id, rejected_by) "
                    "REFERENCES users (tenant_id, id) "
                    "ON DELETE SET NULL (rejected_by)"
                )
            )

    clean = _run_alembic(migration_database_url, "check")
    assert clean.returncode == 0, clean.stdout + clean.stderr


def test_runtime_application_starts_without_ddl_and_seeds_inside_tenant_context(
    runtime_database_url, migration_engine
):
    admin_email = f"runtime-startup-{uuid.uuid4().hex}@example.com"
    env = os.environ.copy()
    env["DATABASE_URL"] = runtime_database_url
    env.pop("MIGRATION_DATABASE_URL", None)
    env["APP_ENV"] = "production"
    env["INITIAL_ADMIN_EMAIL"] = admin_email
    env["INITIAL_ADMIN_PASSWORD"] = "runtime-startup-test-password"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    with migration_engine.begin() as connection:
        default_tenant_id = connection.execute(
            text("SELECT id FROM tenants WHERE code = 'careray'")
        ).scalar_one()
        connection.execute(
            text(
                "SELECT set_config('app.current_tenant_id', "
                "CAST(:tenant_id AS text), true)"
            ),
            {"tenant_id": default_tenant_id},
        )
        assert connection.execute(
            text("SELECT count(*) FROM users WHERE email = :email"),
            {"email": admin_email},
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT count(*) FROM workflows "
                "WHERE tenant_id = :tenant_id AND is_system IS TRUE "
                "AND status = 'published'"
            ),
            {"tenant_id": default_tenant_id},
        ).scalar_one() >= 1


def test_public_token_control_path_resolves_global_token_then_sets_tenant_guc(
    runtime_engine, pg_session_factory, tenant_pair
):
    _tenant_a, tenant_b = tenant_pair
    file_id = uuid.uuid4()
    with pg_session_factory(tenant_b) as tenant_db:
        tenant_db.add(
            StoredFile(
                id=file_id,
                object_key=f"{tenant_b}/public/{file_id}",
                original_filename="public.pdf",
                content_type="application/pdf",
                size=10,
                category="resume",
            )
        )
        tenant_db.commit()
        raw_token = issue_public_token(
            tenant_db,
            tenant_b,
            "stored_file",
            file_id,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )

    unscoped = TenantCapableSession(bind=runtime_engine)
    try:
        resolved = resolve_public_token(unscoped, raw_token, "stored_file")
        assert resolved.tenant_id == tenant_b
        assert resolved.resource.id == file_id
    finally:
        unscoped.rollback()
        unscoped.close()


def test_platform_onboarding_sets_new_tenant_guc_before_business_inserts(
    runtime_engine, migration_engine
):
    actor_id = uuid.uuid4()
    suffix = uuid.uuid4().hex
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO platform_users "
                "(id, email, hashed_password, is_active, created_at, updated_at) "
                "VALUES (:id, :email, 'not-used-in-this-test', true, now(), now())"
            ),
            {"id": actor_id, "email": f"platform-{suffix}@example.com"},
        )

    payload = TenantOnboardingRequest(
        code=f"onboard-{suffix}",
        name="PostgreSQL Onboarding",
        primary_domain=f"onboard-{suffix}.example.com",
        admin_email=f"admin-{suffix}@example.com",
        admin_password="TenantPassword123",
    )
    unscoped = TenantCapableSession(bind=runtime_engine)
    try:
        tenant = create_tenant_with_admin(unscoped, payload, actor_id=actor_id)
    finally:
        unscoped.close()

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "SELECT set_config('app.current_tenant_id', "
                "CAST(:tenant_id AS text), true)"
            ),
            {"tenant_id": tenant.id},
        )
        assert connection.execute(
            text("SELECT count(*) FROM users WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant.id},
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM system_configs WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant.id},
        ).scalar_one() == 1


def test_real_postgres_upgrade_downgrade_gates_and_data_preservation(
    migration_database_url, pg_session_factory, tenant_pair
):
    tenant_a, tenant_b = tenant_pair
    retained_position_id = create_position(
        pg_session_factory, tenant_a, "migration-retained-position"
    )
    cross_position_id = create_position(
        pg_session_factory, tenant_b, "migration-cross-position"
    )
    cross_resume_id = uuid.uuid4()

    result = _run_alembic(
        migration_database_url, "downgrade", "m2n3o4p5q6r7"
    )
    assert result.returncode == 0, result.stdout + result.stderr

    migration_engine = create_engine(migration_database_url, poolclass=NullPool)
    try:
        with migration_engine.begin() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "m2n3o4p5q6r7"
            assert connection.execute(
                text(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = ANY(:tables)"
                ),
                {"tables": list(TENANT_TABLES)},
            ).scalar_one() == 0
            assert connection.execute(
                text("SELECT count(*) FROM positions WHERE id = :id"),
                {"id": retained_position_id},
            ).scalar_one() == 1

            null_position_id = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO positions "
                    "(id, tenant_id, title, description) "
                    "VALUES (:id, NULL, 'null-gate', 'null-gate')"
                ),
                {"id": null_position_id},
            )

        failed_null_upgrade = _run_alembic(
            migration_database_url, "upgrade", "head"
        )
        assert failed_null_upgrade.returncode != 0
        assert (
            'Cannot enforce tenant isolation on "positions": 1 rows have NULL tenant_id'
            in failed_null_upgrade.stdout + failed_null_upgrade.stderr
        )

        with migration_engine.begin() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "m2n3o4p5q6r7"
            assert connection.execute(
                text("SELECT count(*) FROM positions WHERE id = :id"),
                {"id": null_position_id},
            ).scalar_one() == 1
            connection.execute(
                text("DELETE FROM positions WHERE id = :id"),
                {"id": null_position_id},
            )
            connection.execute(
                text(
                    "INSERT INTO resumes (id, tenant_id, position_id) "
                    "VALUES (:id, :tenant_id, :position_id)"
                ),
                {
                    "id": cross_resume_id,
                    "tenant_id": tenant_a,
                    "position_id": cross_position_id,
                },
            )

        failed_cross_upgrade = _run_alembic(
            migration_database_url, "upgrade", "head"
        )
        assert failed_cross_upgrade.returncode != 0
        assert (
            'Cannot enforce tenant reference "resumes.position_id": 1 rows reference another tenant'
            in failed_cross_upgrade.stdout + failed_cross_upgrade.stderr
        )

        with migration_engine.begin() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "m2n3o4p5q6r7"
            connection.execute(
                text("UPDATE resumes SET position_id = NULL WHERE id = :id"),
                {"id": cross_resume_id},
            )

        final_upgrade = _run_alembic(migration_database_url, "upgrade", "head")
        assert final_upgrade.returncode == 0, final_upgrade.stdout + final_upgrade.stderr

        with migration_engine.begin() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "n3o4p5q6r7s8"
            assert connection.execute(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:tables) "
                    "AND c.relrowsecurity AND c.relforcerowsecurity"
                ),
                {"tables": list(TENANT_TABLES)},
            ).scalar_one() == len(TENANT_TABLES)
            assert connection.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE contype = 'f' AND conname LIKE 'fk_%_tenant' "
                    "AND array_length(conkey, 1) = 2"
                )
            ).scalar_one() == 29
            connection.execute(
                text(
                    "SELECT set_config('app.current_tenant_id', "
                    "                  CAST(:tenant_id AS text), true)"
                ),
                {"tenant_id": tenant_a},
            )
            assert connection.execute(
                text("SELECT count(*) FROM positions WHERE id = :id"),
                {"id": retained_position_id},
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM resumes WHERE id = :id"),
                {"id": cross_resume_id},
            ).scalar_one() == 1
    finally:
        migration_engine.dispose()

    role_result = _run_role_script()
    assert role_result.returncode == 0, role_result.stdout + role_result.stderr
