"""Verify the finalized PostgreSQL application-role permission contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.tenant_catalog import GLOBAL_TABLES, TENANT_TABLES


SCHEMA = "ai-interview.database-permissions"
VERSION = 1
APPLICATION_TABLES = tuple(TENANT_TABLES) + tuple(GLOBAL_TABLES)
EXPECTED_PUBLIC_TABLES = set(APPLICATION_TABLES) | {"alembic_version"}


def _result(violations: list[str], **counts) -> dict:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "ok": not violations,
        "counts": counts,
        "violations": sorted(violations),
    }


def verify_database_permissions(connection) -> dict:
    """Return a stable audit of the exact finalized role grants."""

    violations: list[str] = []
    if connection.dialect.name != "postgresql":
        return _result(["postgresql_required"])
    if connection.execute(text("SELECT current_user")).scalar_one() != "app_migration":
        return _result(["migration_role_required"])

    roles = {
        row.rolname: row
        for row in connection.execute(
            text(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                "rolreplication, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('app_runtime', 'app_migration')"
            )
        ).mappings()
    }
    for role_name in ("app_runtime", "app_migration"):
        role = roles.get(role_name)
        if role is None:
            violations.append(f"missing_role:{role_name}")
        elif any(
            role[field]
            for field in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolinherit",
                "rolreplication",
                "rolbypassrls",
            )
        ):
            violations.append(f"unsafe_role_attributes:{role_name}")

    public_tables = {
        row.table_name
        for row in connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        )
    }
    if public_tables != EXPECTED_PUBLIC_TABLES:
        violations.append("unexpected_public_table_catalog")

    table_owners = {
        row.relname: row.owner
        for row in connection.execute(
            text(
                "SELECT relation.relname, owner.rolname AS owner "
                "FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
                "JOIN pg_roles owner ON owner.oid=relation.relowner "
                "WHERE namespace.nspname='public' AND relation.relkind IN ('r','p')"
            )
        ).mappings()
    }
    if any(table_owners.get(table) != "app_migration" for table in public_tables):
        violations.append("migration_does_not_own_all_tables")

    schema_owner = connection.execute(
        text(
            "SELECT owner.rolname FROM pg_namespace namespace "
            "JOIN pg_roles owner ON owner.oid=namespace.nspowner "
            "WHERE namespace.nspname='public'"
        )
    ).scalar_one()
    if schema_owner != "app_migration":
        violations.append("migration_does_not_own_public_schema")

    sequence_owners = connection.execute(
        text(
            "SELECT sequence.relname, owner.rolname "
            "FROM pg_class sequence "
            "JOIN pg_namespace namespace ON namespace.oid=sequence.relnamespace "
            "JOIN pg_roles owner ON owner.oid=sequence.relowner "
            "WHERE namespace.nspname='public' AND sequence.relkind='S'"
        )
    ).all()
    if any(owner != "app_migration" for _name, owner in sequence_owners):
        violations.append("migration_does_not_own_all_sequences")

    type_owners = connection.execute(
        text(
            "SELECT type.typname, owner.rolname "
            "FROM pg_type type "
            "JOIN pg_namespace namespace ON namespace.oid=type.typnamespace "
            "JOIN pg_roles owner ON owner.oid=type.typowner "
            "WHERE namespace.nspname='public' AND type.typtype IN ('e','d')"
        )
    ).all()
    if any(owner != "app_migration" for _name, owner in type_owners):
        violations.append("migration_does_not_own_all_types")

    runtime_database = connection.execute(
        text(
            "SELECT "
            "has_database_privilege('app_runtime', current_database(), 'CONNECT'), "
            "has_database_privilege('app_runtime', current_database(), 'CREATE'), "
            "has_database_privilege('app_runtime', current_database(), 'TEMP')"
        )
    ).one()
    runtime_schema = connection.execute(
        text(
            "SELECT has_schema_privilege('app_runtime','public','USAGE'), "
            "has_schema_privilege('app_runtime','public','CREATE')"
        )
    ).one()
    if runtime_database != (True, False, False):
        violations.append("runtime_database_privileges_invalid")
    if runtime_schema != (True, False):
        violations.append("runtime_schema_privileges_invalid")

    runtime_table_privileges = {
        row.table_name: (
            row.has_select,
            row.has_insert,
            row.has_update,
            row.has_delete,
            row.has_truncate,
            row.has_references,
            row.has_trigger,
        )
        for row in connection.execute(
            text(
                "SELECT table_name, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'SELECT') AS has_select, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'INSERT') AS has_insert, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'UPDATE') AS has_update, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'DELETE') AS has_delete, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'TRUNCATE') AS has_truncate, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'REFERENCES') AS has_references, "
                "has_table_privilege('app_runtime', "
                " quote_ident(table_schema)||'.'||quote_ident(table_name), "
                " 'TRIGGER') AS has_trigger "
                "FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).mappings()
    }
    runtime_dml_tables = {
        table for table, privileges in runtime_table_privileges.items()
        if all(privileges[:4])
    }
    if runtime_dml_tables != set(APPLICATION_TABLES):
        violations.append("runtime_dml_table_catalog_invalid")
    if any(any(privileges[4:]) for privileges in runtime_table_privileges.values()):
        violations.append("runtime_elevated_table_privilege")
    if any(runtime_table_privileges.get("alembic_version", (False,) * 7)):
        violations.append("runtime_can_access_alembic_version")

    runtime_sequence_privileges = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.sequences "
            "WHERE sequence_schema='public' AND ("
            "has_sequence_privilege('app_runtime', "
            " quote_ident(sequence_schema)||'.'||quote_ident(sequence_name), 'USAGE') "
            "OR has_sequence_privilege('app_runtime', "
            " quote_ident(sequence_schema)||'.'||quote_ident(sequence_name), 'SELECT') "
            "OR has_sequence_privilege('app_runtime', "
            " quote_ident(sequence_schema)||'.'||quote_ident(sequence_name), 'UPDATE'))"
        )
    ).scalar_one()
    if int(runtime_sequence_privileges):
        violations.append("runtime_sequence_privilege")

    return _result(
        violations,
        application_tables_expected=len(APPLICATION_TABLES),
        application_tables_with_runtime_dml=len(runtime_dml_tables),
        public_tables=len(public_tables),
        public_sequences=len(sequence_owners),
    )


def run_cli(*, environ=None, stdout=None) -> int:
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    url = environ.get("MIGRATION_DATABASE_URL")
    if not url:
        payload = _result(["migration_database_url_required"])
        print(json.dumps(payload, sort_keys=True), file=stdout)
        return 1

    engine = None
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL statement_timeout='60s'"))
                payload = verify_database_permissions(connection)
            finally:
                transaction.rollback()
    except Exception:
        payload = _result(["permission_verification_failed"])
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(payload, sort_keys=True), file=stdout)
    return 0 if payload["ok"] else 1


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
