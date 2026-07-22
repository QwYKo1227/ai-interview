import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models.file_models import StoredFile
from app.models.base import Base
from app.models.tenant_catalog import COMPOSITE_TENANT_REFERENCES, TENANT_TABLES
from app.models.tenant_models import TenantScopedMixin
from scripts.backfill_legacy_uploads import (
    LegacyFileCandidate,
    LegacyFileError,
    backfill_candidate,
)
from scripts.create_platform_admin import (
    PlatformAdminInputError,
    create_platform_admin,
)
from scripts.verify_tenant_migration import run_cli, verify_tenant_integrity


def test_rollout_scripts_are_directly_executable_from_backend_root():
    backend_root = Path(__file__).parents[1]
    environ = os.environ.copy()
    for key in (
        "PYTHONPATH",
        "MIGRATION_DATABASE_URL",
        "PLATFORM_ADMIN_EMAIL",
        "PLATFORM_ADMIN_PASSWORD",
    ):
        environ.pop(key, None)

    commands = (
        ("verify_tenant_migration.py", [], 1),
        ("create_platform_admin.py", [], 1),
        ("backfill_legacy_uploads.py", ["--help"], 0),
    )
    for script, arguments, expected_status in commands:
        completed = subprocess.run(
            [sys.executable, str(backend_root / "scripts" / script), *arguments],
            cwd=backend_root,
            env=environ,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert completed.returncode == expected_status, completed.stderr
        assert "ModuleNotFoundError" not in completed.stderr


def _controlled_database(tmp_path: Path):
    """Build deliberately constraint-free audit tables for corrupt-data tests.

    PostgreSQL head correctly prevents these rows, so bad migration states are
    injected only into this explicitly controlled schema instead of disabling
    real production constraints.
    """

    engine = create_engine(f"sqlite:///{tmp_path / 'controlled.db'}")
    relationship_columns: dict[str, set[str]] = {}
    for child, column, _parent in COMPOSITE_TENANT_REFERENCES:
        relationship_columns.setdefault(child, set()).add(column)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tenants (id TEXT PRIMARY KEY, code TEXT)"))
        for table in TENANT_TABLES:
            extra_columns = set(relationship_columns.get(table, set()))
            if table == "users":
                extra_columns.add("email")
            elif table == "resumes":
                extra_columns.update(("file_path", "file_id"))
            elif table == "question_banks":
                extra_columns.update(("source_file", "source_file_id"))
            columns = ["id TEXT PRIMARY KEY", "tenant_id TEXT"]
            columns.extend(f'"{column}" TEXT' for column in sorted(extra_columns))
            connection.execute(text(f'CREATE TABLE "{table}" ({", ".join(columns)})'))
    return engine


def _seed_two_tenants(connection):
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    connection.execute(
        text("INSERT INTO tenants (id, code) VALUES (:id, :code)"),
        [
            {"id": tenant_a, "code": "careray"},
            {"id": tenant_b, "code": "photonthix"},
        ],
    )
    connection.execute(
        text("INSERT INTO system_configs (id, tenant_id) VALUES (:id, :tenant_id)"),
        [
            {"id": str(uuid4()), "tenant_id": tenant_a},
            {"id": str(uuid4()), "tenant_id": tenant_b},
        ],
    )
    for tenant_id in (tenant_a, tenant_b):
        position_id = str(uuid4())
        connection.execute(
            text("INSERT INTO positions (id, tenant_id) VALUES (:id, :tenant_id)"),
            {"id": position_id, "tenant_id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO resumes (id, tenant_id, position_id) "
                "VALUES (:id, :tenant_id, :position_id)"
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "position_id": position_id,
            },
        )
    return tenant_a, tenant_b


def test_catalog_is_the_authoritative_18_table_29_relation_contract():
    assert len(TENANT_TABLES) == 18
    assert len(COMPOSITE_TENANT_REFERENCES) == 29
    assert len(set(TENANT_TABLES)) == 18
    assert len(set(COMPOSITE_TENANT_REFERENCES)) == 29

    mapped_tables = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantScopedMixin)
    }
    assert mapped_tables == set(TENANT_TABLES)

    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "n3o4p5q6r7s8_enforce_tenant_rls.py"
    )
    spec = importlib.util.spec_from_file_location("tenant_rls_snapshot", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert tuple(module.TENANT_TABLES) == TENANT_TABLES
    assert tuple(
        (child, column, parent)
        for child, column, parent, _ondelete, _legacy_name
        in module.COMPOSITE_FOREIGN_KEYS
    ) == COMPOSITE_TENANT_REFERENCES


def test_production_caddy_defaults_to_both_internal_tenant_domains():
    root = Path(__file__).parents[2]
    caddyfile = (root / "Caddyfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    domains = "interview.careray.com, interview.photonthix.com"

    assert f"APP_DOMAINS:{domains}" in caddyfile
    assert "tls internal" in caddyfile
    assert 'Permissions-Policy "microphone=(self)"' in caddyfile
    assert "APP_DOMAINS" in compose
    assert domains in compose
    migrate_service = compose.split("  backend-migrate:", 1)[1].split(
        "  postgres-finalize:", 1
    )[0]
    assert "backend_uploads:/app/uploads" in migrate_service

    nginx = (root / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    backend_dockerfile = (root / "backend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "reverse_proxy frontend:80" in caddyfile
    assert "proxy_set_header Host $host;" in nginx
    assert "ffmpeg" in backend_dockerfile


def test_verifier_fails_when_tenant_id_is_null(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        _seed_two_tenants(connection)
        connection.execute(
            text("INSERT INTO offers (id, tenant_id) VALUES (:id, NULL)"),
            {"id": str(uuid4())},
        )
        result = verify_tenant_integrity(connection)

    assert result.ok is False
    assert result.counts["null_tenant_rows"]["offers"] == 1
    assert any(item["code"] == "null_tenant" for item in result.violations)


def test_verifier_fails_for_cross_tenant_parent_reference(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        tenant_a, tenant_b = _seed_two_tenants(connection)
        position_id = connection.execute(
            text("SELECT id FROM positions WHERE tenant_id = :tenant_id LIMIT 1"),
            {"tenant_id": tenant_a},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO resumes (id, tenant_id, position_id) "
                "VALUES (:id, :tenant_id, :position_id)"
            ),
            {"id": str(uuid4()), "tenant_id": tenant_b, "position_id": position_id},
        )
        result = verify_tenant_integrity(connection)

    assert result.ok is False
    assert result.counts["cross_tenant_references"]["resumes.position_id"] == 1


def test_verifier_fails_for_duplicate_email_within_one_tenant(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        tenant_a, _tenant_b = _seed_two_tenants(connection)
        connection.execute(
            text("INSERT INTO users (id, tenant_id, email) VALUES (:id, :tenant, :email)"),
            [
                {"id": str(uuid4()), "tenant": tenant_a, "email": "Admin@Example.com"},
                {"id": str(uuid4()), "tenant": tenant_a, "email": "admin@example.com"},
            ],
        )
        result = verify_tenant_integrity(connection)

    assert result.counts["duplicate_user_emails"] == 1
    assert result.ok is False


@pytest.mark.parametrize("config_count", [0, 2])
def test_verifier_requires_exactly_one_system_config_per_tenant(tmp_path, config_count):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        tenant_a, _tenant_b = _seed_two_tenants(connection)
        connection.execute(
            text("DELETE FROM system_configs WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_a},
        )
        for _ in range(config_count):
            connection.execute(
                text(
                    "INSERT INTO system_configs (id, tenant_id) "
                    "VALUES (:id, :tenant_id)"
                ),
                {"id": str(uuid4()), "tenant_id": tenant_a},
            )
        result = verify_tenant_integrity(connection)

    key = "missing_system_configs" if config_count == 0 else "duplicate_system_configs"
    assert result.counts[key] == 1
    assert result.ok is False


def test_verifier_requires_default_careray_tenant(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        _seed_two_tenants(connection)
        connection.execute(text("UPDATE tenants SET code = 'legacy' WHERE code = 'careray'"))
        result = verify_tenant_integrity(connection)

    assert result.counts["default_careray_tenants"] == 0
    assert result.ok is False


def test_verifier_reports_pending_legacy_files(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        tenant_a, _tenant_b = _seed_two_tenants(connection)
        connection.execute(
            text(
                "INSERT INTO question_banks "
                "(id, tenant_id, source_file, source_file_id) "
                "VALUES (:id, :tenant_id, 'uploads/legacy.pdf', NULL)"
            ),
            {"id": str(uuid4()), "tenant_id": tenant_a},
        )
        result = verify_tenant_integrity(connection)

    assert result.counts["legacy_files_pending"]["question_banks"] == 1
    assert result.ok is False


def test_verifier_passes_for_two_isolated_tenants_and_stable_json(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        _seed_two_tenants(connection)
        first = verify_tenant_integrity(connection)
        second = verify_tenant_integrity(connection)

    assert first.ok is True
    payload = first.to_dict()
    assert list(payload) == ["schema", "version", "ok", "counts", "violations"]
    assert payload["schema"] == "ai-interview.tenant-migration-verification"
    assert payload["version"] == 1
    assert json.dumps(payload, sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)


def test_verifier_cli_uses_only_migration_url_and_redacts_secrets():
    stdout = io.StringIO()
    status = run_cli(
        environ={
            "DATABASE_URL": "postgresql://runtime:runtime-secret@db/runtime",
        },
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert payload["ok"] is False
    assert "runtime-secret" not in stdout.getvalue()
    assert "postgresql://" not in stdout.getvalue()


def test_verifier_cli_redacts_migration_url_on_connection_failure():
    stdout = io.StringIO()
    status = run_cli(
        environ={
            "MIGRATION_DATABASE_URL": (
                "postgresql://app_migration:unique-secret@127.0.0.1:1/"
                "unreachable?connect_timeout=1"
            ),
        },
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert payload["violations"][0]["code"] == "verification_failed"
    assert "unique-secret" not in stdout.getvalue()
    assert "postgresql://" not in stdout.getvalue()


def test_platform_admin_normalizes_email_and_is_idempotent_without_password_reset(db):
    password = "StrongPlatformPassword123"
    created = create_platform_admin(db, "  PLATFORM@Example.COM ", password)
    original_hash = created.user.hashed_password
    repeated = create_platform_admin(db, "platform@example.com", "DifferentPassword456")

    assert created.created is True
    assert repeated.created is False
    assert repeated.user.id == created.user.id
    assert repeated.user.email == "platform@example.com"
    assert repeated.user.hashed_password == original_hash


@pytest.mark.parametrize(
    "password",
    ["short1", "NoDigitsInThisPassword", "123456789012345", "密" * 30 + "1a"],
)
def test_platform_admin_rejects_weak_or_bcrypt_oversized_password(db, password):
    with pytest.raises(PlatformAdminInputError):
        create_platform_admin(db, "platform@example.com", password)
    assert db.execute(text("SELECT count(*) FROM platform_users")).scalar_one() == 0


def _candidate(tenant_id: UUID, row_id: UUID, legacy_path: Path):
    return LegacyFileCandidate(
        table="resumes",
        row_id=row_id,
        tenant_id=tenant_id,
        legacy_path=str(legacy_path),
        path_field="file_path",
        file_id_field="file_id",
        category="resumes",
        resource_type="resume",
    )


def _seed_resume_for_backfill(db, tenant_id: UUID, row_id: UUID, legacy_path: Path):
    db.execute(
        text(
            "INSERT INTO tenants (id, code, name, status, created_at, updated_at) "
            "VALUES (:id, :code, 'Legacy', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": tenant_id.hex, "code": f"legacy-{tenant_id.hex}"},
    )
    db.execute(
        text(
            "INSERT INTO resumes (id, tenant_id, file_path, parse_status) "
            "VALUES (:id, :tenant_id, :path, 'processing')"
        ),
        {"id": row_id.hex, "tenant_id": tenant_id.hex, "path": str(legacy_path)},
    )
    db.commit()


def test_legacy_backfill_dry_run_does_not_write_database_or_files(db, tmp_path):
    legacy_root = tmp_path / "legacy"
    upload_root = tmp_path / "new"
    legacy_root.mkdir()
    source = legacy_root / "resume.pdf"
    source.write_bytes(b"resume")
    tenant_id, row_id = uuid4(), uuid4()
    _seed_resume_for_backfill(db, tenant_id, row_id, source)

    result = backfill_candidate(
        db,
        _candidate(tenant_id, row_id, source),
        legacy_root=legacy_root,
        upload_root=upload_root,
        dry_run=True,
    )

    assert result.status == "would_migrate"
    assert db.query(StoredFile).count() == 0
    assert not upload_root.exists()
    assert source.exists()


@pytest.mark.parametrize("unsafe", ["missing", "traversal", "symlink"])
def test_legacy_backfill_rejects_missing_traversal_and_symlink(db, tmp_path, unsafe):
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"secret")
    if unsafe == "missing":
        source = legacy_root / "missing.pdf"
    elif unsafe == "traversal":
        source = legacy_root / ".." / "outside.pdf"
    else:
        source = legacy_root / "link.pdf"
        try:
            source.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks are unavailable on this platform")
    tenant_id, row_id = uuid4(), uuid4()
    _seed_resume_for_backfill(db, tenant_id, row_id, source)

    with pytest.raises(LegacyFileError):
        backfill_candidate(
            db,
            _candidate(tenant_id, row_id, source),
            legacy_root=legacy_root,
            upload_root=tmp_path / "new",
        )

    assert db.query(StoredFile).count() == 0


def test_legacy_backfill_removes_new_copy_when_database_commit_fails(
    db, tmp_path, monkeypatch
):
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    source = legacy_root / "resume.pdf"
    source.write_bytes(b"resume")
    tenant_id, row_id = uuid4(), uuid4()
    _seed_resume_for_backfill(db, tenant_id, row_id, source)

    def fail_commit():
        raise RuntimeError("database rejected commit")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database rejected commit"):
        backfill_candidate(
            db,
            _candidate(tenant_id, row_id, source),
            legacy_root=legacy_root,
            upload_root=tmp_path / "new",
        )

    assert not list((tmp_path / "new").rglob("*.*"))
    assert source.exists()


def test_legacy_backfill_is_idempotent_and_two_tenants_do_not_collide(db, tmp_path):
    legacy_root = tmp_path / "legacy"
    upload_root = tmp_path / "new"
    legacy_root.mkdir()
    candidates = []
    for index in range(2):
        tenant_id, row_id = uuid4(), uuid4()
        source_dir = legacy_root / str(index)
        source_dir.mkdir()
        source = source_dir / "same.pdf"
        source.write_bytes(f"tenant-{index}".encode())
        _seed_resume_for_backfill(db, tenant_id, row_id, source)
        candidates.append(_candidate(tenant_id, row_id, source))

    first = [
        backfill_candidate(
            db,
            candidate,
            legacy_root=legacy_root,
            upload_root=upload_root,
        )
        for candidate in candidates
    ]
    repeated = backfill_candidate(
        db,
        candidates[0],
        legacy_root=legacy_root,
        upload_root=upload_root,
    )

    assert {item.status for item in first} == {"migrated"}
    assert repeated.status == "already_migrated"
    rows = db.query(StoredFile).order_by(StoredFile.tenant_id).all()
    assert len(rows) == 2
    assert rows[0].object_key != rows[1].object_key
    assert {Path(row.object_key).parts[0] for row in rows} == {
        str(candidate.tenant_id) for candidate in candidates
    }
    assert all(Path(row.object_key).name != "same.pdf" for row in rows)
    assert all(candidate.legacy_path and Path(candidate.legacy_path).exists() for candidate in candidates)
