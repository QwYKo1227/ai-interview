"""Audit tenant migration integrity and emit stable, secret-free JSON."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.tenant_catalog import (
    COMPOSITE_TENANT_REFERENCES,
    TENANT_TABLES,
)


SCHEMA = "ai-interview.tenant-migration-verification"
VERSION = 1


@dataclass(frozen=True)
class MigrationVerificationResult:
    ok: bool
    counts: dict[str, Any]
    violations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "ok": self.ok,
            "counts": self.counts,
            "violations": self.violations,
        }


def _executor_bind(db):
    return db.get_bind() if hasattr(db, "get_bind") else db


def _scalar(db, statement: str, parameters=None) -> int:
    return int(db.execute(text(statement), parameters or {}).scalar_one())


def _violation(code: str, resource: str, count: int = 1):
    return {"code": code, "resource": resource, "count": count}


def _failure(code: str) -> MigrationVerificationResult:
    return MigrationVerificationResult(
        ok=False,
        counts={},
        violations=[_violation(code, "database")],
    )


def verify_tenant_integrity(db) -> MigrationVerificationResult:
    """Verify all current tenant invariants visible to the supplied executor."""

    inspector = inspect(_executor_bind(db))
    existing_tables = set(inspector.get_table_names())
    existing_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in existing_tables
    }
    violations = []
    table_rows = {}
    null_tenant_rows = {}

    for table in TENANT_TABLES:
        if table not in existing_tables:
            table_rows[table] = 0
            null_tenant_rows[table] = 0
            violations.append(_violation("missing_table", table))
            continue
        table_rows[table] = _scalar(db, f'SELECT count(*) FROM "{table}"')
        if "tenant_id" not in existing_columns[table]:
            null_tenant_rows[table] = 0
            violations.append(_violation("missing_tenant_column", table))
            continue
        count = _scalar(
            db, f'SELECT count(*) FROM "{table}" WHERE tenant_id IS NULL'
        )
        null_tenant_rows[table] = count
        if count:
            violations.append(_violation("null_tenant", table, count))

    cross_tenant_references = {}
    missing_parent_references = {}
    for child, column, parent in COMPOSITE_TENANT_REFERENCES:
        resource = f"{child}.{column}"
        required_child = {"tenant_id", column}
        required_parent = {"id", "tenant_id"}
        if (
            child not in existing_tables
            or parent not in existing_tables
            or not required_child.issubset(existing_columns.get(child, set()))
            or not required_parent.issubset(existing_columns.get(parent, set()))
        ):
            cross_tenant_references[resource] = 0
            missing_parent_references[resource] = 0
            violations.append(_violation("missing_relation_schema", resource))
            continue
        cross_count = _scalar(
            db,
            f'SELECT count(*) FROM "{child}" child '
            f'JOIN "{parent}" parent ON parent.id = child."{column}" '
            f'WHERE child."{column}" IS NOT NULL '
            "AND child.tenant_id <> parent.tenant_id",
        )
        missing_count = _scalar(
            db,
            f'SELECT count(*) FROM "{child}" child '
            f'LEFT JOIN "{parent}" parent ON parent.id = child."{column}" '
            f'WHERE child."{column}" IS NOT NULL AND parent.id IS NULL',
        )
        cross_tenant_references[resource] = cross_count
        missing_parent_references[resource] = missing_count
        if cross_count:
            violations.append(
                _violation("cross_tenant_reference", resource, cross_count)
            )
        if missing_count:
            violations.append(
                _violation("missing_parent_reference", resource, missing_count)
            )

    duplicate_user_emails = 0
    if "users" in existing_tables and {"tenant_id", "email"}.issubset(
        existing_columns["users"]
    ):
        duplicate_user_emails = _scalar(
            db,
            "SELECT count(*) FROM ("
            "SELECT tenant_id, lower(email) FROM users "
            "WHERE email IS NOT NULL GROUP BY tenant_id, lower(email) "
            "HAVING count(*) > 1) duplicates",
        )
        if duplicate_user_emails:
            violations.append(
                _violation("duplicate_user_email", "users.email", duplicate_user_emails)
            )
    else:
        violations.append(_violation("missing_email_schema", "users.email"))

    missing_system_configs = 0
    duplicate_system_configs = 0
    default_careray_tenants = 0
    if "tenants" not in existing_tables:
        violations.append(_violation("missing_table", "tenants"))
    else:
        default_careray_tenants = _scalar(
            db, "SELECT count(*) FROM tenants WHERE code = 'careray'"
        )
        if default_careray_tenants != 1:
            violations.append(
                _violation(
                    "default_careray_count", "tenants.code=careray",
                    default_careray_tenants,
                )
            )
        if "system_configs" in existing_tables:
            missing_system_configs = _scalar(
                db,
                "SELECT count(*) FROM tenants tenant WHERE NOT EXISTS ("
                "SELECT 1 FROM system_configs config WHERE config.tenant_id = tenant.id)",
            )
            duplicate_system_configs = _scalar(
                db,
                "SELECT count(*) FROM (SELECT tenant_id FROM system_configs "
                "GROUP BY tenant_id HAVING count(*) > 1) duplicates",
            )
            if missing_system_configs:
                violations.append(
                    _violation(
                        "missing_system_config", "system_configs",
                        missing_system_configs,
                    )
                )
            if duplicate_system_configs:
                violations.append(
                    _violation(
                        "duplicate_system_config", "system_configs",
                        duplicate_system_configs,
                    )
                )

    legacy_files_pending = {
        "resumes": 0,
        "question_banks": 0,
        "interview_audio": 0,
    }
    for table, path_column, id_column in (
        ("resumes", "file_path", "file_id"),
        ("question_banks", "source_file", "source_file_id"),
    ):
        if table in existing_tables and {path_column, id_column}.issubset(
            existing_columns[table]
        ):
            count = _scalar(
                db,
                f'SELECT count(*) FROM "{table}" WHERE "{path_column}" IS NOT NULL '
                f'AND "{path_column}" <> \'\' AND "{id_column}" IS NULL '
                f'AND "{path_column}" NOT LIKE \'/api/files/%\'',
            )
            legacy_files_pending[table] = count
            if count:
                violations.append(_violation("legacy_file_pending", table, count))
    for table in ("interviews", "interview_panels"):
        if table in existing_tables and "audio_records" in existing_columns[table]:
            legacy_files_pending["interview_audio"] += _scalar(
                db,
                f'SELECT count(*) FROM "{table}" WHERE audio_records IS NOT NULL '
                "AND CAST(audio_records AS TEXT) LIKE '%uploads%'",
            )
    if legacy_files_pending["interview_audio"]:
        violations.append(
            _violation(
                "legacy_file_pending", "interview_audio",
                legacy_files_pending["interview_audio"],
            )
        )

    counts = {
        "table_rows": table_rows,
        "null_tenant_rows": null_tenant_rows,
        "cross_tenant_references": cross_tenant_references,
        "missing_parent_references": missing_parent_references,
        "duplicate_user_emails": duplicate_user_emails,
        "missing_system_configs": missing_system_configs,
        "duplicate_system_configs": duplicate_system_configs,
        "default_careray_tenants": default_careray_tenants,
        "legacy_files_pending": legacy_files_pending,
    }
    return MigrationVerificationResult(
        ok=not violations,
        counts=counts,
        violations=violations,
    )


def _verify_connection(connection) -> MigrationVerificationResult:
    if connection.dialect.name != "postgresql":
        return verify_tenant_integrity(connection)

    role = connection.execute(text("SELECT current_user")).scalar_one()
    if role != "app_migration":
        return _failure("insufficient_migration_privileges")
    owned = connection.execute(
        text(
            "SELECT count(*) FROM pg_class relation "
            "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
            "JOIN pg_roles owner ON owner.oid = relation.relowner "
            "WHERE namespace.nspname = 'public' "
            "AND relation.relname = ANY(:tables) AND owner.rolname = current_user"
        ),
        {"tables": list(TENANT_TABLES)},
    ).scalar_one()
    if int(owned) != len(TENANT_TABLES):
        return _failure("insufficient_migration_privileges")

    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '60s'"))
    for table in TENANT_TABLES:
        connection.execute(text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    return verify_tenant_integrity(connection)


def run_cli(*, environ=None, stdout=None) -> int:
    """Run the verifier using only MIGRATION_DATABASE_URL and return an exit code."""

    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    url = environ.get("MIGRATION_DATABASE_URL")
    if not url:
        result = _failure("migration_database_url_required")
        print(json.dumps(result.to_dict(), sort_keys=True), file=stdout)
        return 1

    engine = None
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                result = _verify_connection(connection)
            finally:
                transaction.rollback()
    except Exception:
        result = _failure("verification_failed")
    finally:
        if engine is not None:
            engine.dispose()

    print(json.dumps(result.to_dict(), sort_keys=True), file=stdout)
    return 0 if result.ok else 1


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
