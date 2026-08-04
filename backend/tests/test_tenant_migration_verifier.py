import io
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.file_models import StoredFile
from app.models.base import Base
from app.models.tenant_catalog import COMPOSITE_TENANT_REFERENCES, TENANT_TABLES
from app.models.tenant_models import TenantScopedMixin
from scripts.backfill_legacy_uploads import (
    LegacyFileCandidate,
    LegacyFileError,
    backfill_candidate,
    candidate_fingerprint,
)
from scripts.create_platform_admin import (
    PlatformAdminInputError,
    create_platform_admin,
)
from scripts.reset_platform_admin_password import (
    PlatformAdminNotFoundError,
    _prompt_for_password,
    _resolve_platform_admin_email,
    reset_platform_admin_password,
)
from scripts.verify_tenant_migration import run_cli, verify_tenant_integrity


def _portable_tool(name: str) -> str | None:
    candidates = [shutil.which(name)]
    if os.name == "nt":
        candidates.append(str(Path("C:/Program Files/Git/usr/bin") / f"{name}.exe"))
        if name == "bash":
            candidates.insert(0, "C:/Program Files/Git/bin/bash.exe")
    return next(
        (candidate for candidate in candidates if candidate and Path(candidate).is_file()),
        None,
    )


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
        ("reset_platform_admin_password.py", [], 1),
        ("backfill_legacy_uploads.py", ["--help"], 0),
        ("snapshot_tenant_counts.py", ["--help"], 0),
        ("legacy_backfill_gate.py", ["--help"], 0),
        ("verify_database_permissions.py", [], 1),
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
            elif table in {"interviews", "interview_panels"}:
                extra_columns.add("audio_records")
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


def test_catalog_is_the_authoritative_19_table_31_relation_contract():
    assert len(TENANT_TABLES) == 19
    assert len(COMPOSITE_TENANT_REFERENCES) == 31
    assert len(set(TENANT_TABLES)) == 19
    assert len(set(COMPOSITE_TENANT_REFERENCES)) == 31

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
    assert tuple(module.TENANT_TABLES) == tuple(
        table for table in TENANT_TABLES if table != "offer_decision_audits"
    )
    assert tuple(
        (child, column, parent)
        for child, column, parent, _ondelete, _legacy_name
        in module.COMPOSITE_FOREIGN_KEYS
    ) == tuple(
        relation for relation in COMPOSITE_TENANT_REFERENCES
        if relation[0] != "offer_decision_audits"
    )


def test_production_caddy_defaults_to_both_internal_tenant_domains():
    root = Path(__file__).parents[2]
    caddyfile = (root / "Caddyfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    domains = "interview.careray.com, interview.photonthix.com"

    assert f"APP_DOMAINS:{domains}" in caddyfile
    assert "tls internal" in caddyfile
    assert 'Permissions-Policy "microphone=(self)"' in caddyfile
    assert "APP_DOMAINS" in compose
    assert domains in compose
    assert "UNIFIED_ENTRY_HOSTS=interview.careray.com" in env_example
    assert (
        "UNIFIED_ENTRY_HOSTS: ${UNIFIED_ENTRY_HOSTS:?Set UNIFIED_ENTRY_HOSTS "
        "to the shared company login hostname}" in compose
    )
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


def test_runbook_bash_blocks_are_syntax_valid_and_fail_stop(tmp_path):
    root = Path(__file__).parents[2]
    runbook = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")
    bash = _portable_tool("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    blocks = re.findall(r"```bash\n(.*?)\n```", runbook, flags=re.DOTALL)
    assert blocks
    for index, block in enumerate(blocks):
        script = tmp_path / f"runbook-{index}.sh"
        script.write_text("set -euo pipefail\n" + block + "\n", encoding="utf-8")
        completed = subprocess.run(
            [bash, "-n", str(script)],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert completed.returncode == 0, (
            f"bash block {index} is invalid:\n{completed.stderr}\n{block}"
        )

    assert "set -euo pipefail" in runbook
    assert not re.search(r"(?m)^\s*(?:source|\.)\s+[^\n]*\.env", runbook)
    assert not re.search(r"(?m)^\s*eval\s+", runbook)
    assert 'docker compose --env-file "$ENV_FILE"' in runbook
    for block in blocks:
        assert not re.search(
            r"docker\s+compose(?!\s+--env-file\s+\"\$ENV_FILE\")",
            block,
        )


def test_clone_runbook_finalizes_and_gates_permissions_before_backend_smoke():
    root = Path(__file__).parents[2]
    runbook = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")
    clone = runbook.split("### 2.3", 1)[1].split("## 3.", 1)[0]

    head = clone.index('"$BACKEND_IMAGE" alembic upgrade head')
    finalize = clone.index(
        "sh /docker-entrypoint-initdb.d/01-app-roles.sh",
        head,
    )
    permission_gate = clone.index(
        "python scripts/verify_database_permissions.py",
        finalize,
    )
    backend_smoke = clone.index("uvicorn app.main:app", permission_gate)

    assert head < finalize < permission_gate < backend_smoke
    assert runbook.count("python scripts/verify_database_permissions.py") >= 2


def test_runbook_branches_safely_for_zero_and_positive_legacy_candidates():
    root = Path(__file__).parents[2]
    runbook = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")

    assert runbook.count("python scripts/legacy_backfill_gate.py plan") == 2
    assert runbook.count("python scripts/legacy_backfill_gate.py finalize") == 4
    for prefix in ("DRILL", "PRODUCTION"):
        assert (
            f'if [[ "${prefix}_BACKFILL_ACTION" == "migrate" ]]; then'
            in runbook
        )
        assert f'{prefix}_BACKFILL_PENDING="$(jq -er' in runbook
        assert f'{prefix}_STORED_FILE_INCREASE="$(jq -er' in runbook
    assert runbook.count("legacy-upload-backfill") >= 4
    assert runbook.count("counts.pending") >= 4


def test_clone_cleanup_trap_removes_runtime_resources_and_preserves_evidence(
    tmp_path,
):
    bash = _portable_tool("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    root = Path(__file__).parents[2]
    runbook = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")
    cleanup = runbook.split("# BEGIN DRILL CLEANUP TRAP", 1)[1].split(
        "# END DRILL CLEANUP TRAP", 1
    )[0]
    script = tmp_path / "simulate-drill-cleanup.sh"
    script.write_text(
        "set -euo pipefail\n"
        'LOG="$1"\nEVIDENCE="$2"\nmkdir -p "$EVIDENCE"\n'
        'touch "$EVIDENCE/backup.dump"\n'
        'docker() { printf \'%s\\n\' "$*" >> "$LOG"; }\n'
        "set +e\n(\n"
        "export DRILL_BACKEND_CONTAINER=marker-backend\n"
        "export DRILL_DB_CONTAINER=marker-postgres\n"
        "export DRILL_NETWORK=marker-network\n"
        "export DRILL_DB_VOLUME=marker-db-volume\n"
        "export DRILL_UPLOAD_VOLUME=marker-upload-volume\n"
        "export DRILL_POSTGRES_PASSWORD=secret\n"
        + cleanup
        + "\nfalse\n)\nFAILURE_STATUS=$?\nset -e\n"
        "test \"$FAILURE_STATUS\" -ne 0\n"
        "export DRILL_BACKEND_CONTAINER=marker-backend\n"
        "export DRILL_DB_CONTAINER=marker-postgres\n"
        "export DRILL_NETWORK=marker-network\n"
        "export DRILL_POSTGRES_PASSWORD=secret\n"
        + cleanup
        + "\ncleanup_drill 0\ncleanup_drill 0\n"
        "test -z \"${DRILL_POSTGRES_PASSWORD+x}\"\n"
        'grep -q "rm -f marker-backend marker-postgres" "$LOG"\n'
        'grep -q "network rm marker-network" "$LOG"\n'
        'if grep -q "volume rm" "$LOG"; then exit 1; fi\n'
        'test -f "$EVIDENCE/backup.dump"\n',
        encoding="utf-8",
    )
    log = tmp_path / "docker.log"
    evidence = tmp_path / "evidence"

    completed = subprocess.run(
        [bash, str(script), log.as_posix(), evidence.as_posix()],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_compose_env_file_preserves_spaced_domains_without_executing_commands(
    tmp_path,
):
    if shutil.which("docker") is None:
        pytest.skip("docker is unavailable")
    marker = tmp_path / "dotenv-command-must-not-run"
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n"
        "  probe:\n"
        "    image: busybox:1.36\n"
        "    environment:\n"
        "      APP_DOMAINS: ${APP_DOMAINS}\n"
        "      MALICIOUS: ${MALICIOUS}\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "APP_DOMAINS=interview.careray.com, interview.photonthix.com\n"
        f"MALICIOUS=$(touch {marker.as_posix()})\n",
        encoding="utf-8",
    )
    environ = os.environ.copy()
    environ.pop("APP_DOMAINS", None)
    environ.pop("MALICIOUS", None)

    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(compose),
            "config",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        cwd=tmp_path,
        env=environ,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    environment = payload["services"]["probe"]["environment"]
    assert environment["APP_DOMAINS"] == (
        "interview.careray.com, interview.photonthix.com"
    )
    assert "touch" in environment["MALICIOUS"]
    assert not marker.exists()


def test_sha256_basename_manifest_verifies_after_copy_to_another_directory(
    tmp_path,
):
    bash = _portable_tool("bash")
    checksum = _portable_tool("sha256sum")
    if bash is None or checksum is None:
        pytest.skip("bash and sha256sum are required")
    source = tmp_path / "source"
    remote = tmp_path / "remote"
    source.mkdir()
    remote.mkdir()
    archive = source / "database-before.dump"
    archive.write_bytes(b"database backup")
    manifest = source / "database-before.dump.sha256"

    created = subprocess.run(
        [
            bash,
            "-c",
            'cd "$1" && sha256sum "$(basename "$2")" > "$(basename "$3")"',
            "checksum-test",
            str(source),
            str(archive),
            str(manifest),
        ],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    shutil.copy2(archive, remote / archive.name)
    shutil.copy2(manifest, remote / manifest.name)
    verified = subprocess.run(
        [bash, "-c", 'cd "$1" && sha256sum -c "$2"', "checksum-test", str(remote), manifest.name],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr


def test_authoritative_tenant_count_snapshot_and_comparison_contract(tmp_path):
    from scripts.snapshot_tenant_counts import (
        compare_tenant_count_snapshots,
        snapshot_tenant_counts,
        write_snapshot_files,
    )

    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        _seed_two_tenants(connection)
        before = snapshot_tenant_counts(connection)
        connection.execute(
            text("INSERT INTO stored_files (id, tenant_id) VALUES (:id, :tenant_id)"),
            {"id": str(uuid4()), "tenant_id": connection.execute(
                text("SELECT id FROM tenants ORDER BY code LIMIT 1")
            ).scalar_one()},
        )
        after = snapshot_tenant_counts(connection)

    assert list(before["tables"]) == list(TENANT_TABLES)
    assert before["schema"] == "ai-interview.tenant-table-counts"
    assert compare_tenant_count_snapshots(
        before, after, allowed_stored_files_increase=1
    )["ok"] is True
    unaccounted = compare_tenant_count_snapshots(before, after)
    assert unaccounted["ok"] is False
    assert unaccounted["differences"]["stored_files"]["status"] == (
        "unexpected_increase"
    )

    decreased = json.loads(json.dumps(after))
    decreased["tables"]["positions"]["rows"] -= 1
    comparison = compare_tenant_count_snapshots(
        before, decreased, allowed_stored_files_increase=1
    )
    assert comparison["ok"] is False
    assert comparison["differences"]["positions"]["status"] == "decreased"

    unexpected = json.loads(json.dumps(before))
    unexpected["tables"]["users"]["rows"] += 1
    comparison = compare_tenant_count_snapshots(
        before, unexpected, allowed_stored_files_increase=0
    )
    assert comparison["ok"] is False
    assert comparison["differences"]["users"]["status"] == "unexpected_increase"

    missing_before = json.loads(json.dumps(before))
    missing_after = json.loads(json.dumps(before))
    missing_before["tables"]["workflows"] = {"present": False, "rows": 0}
    missing_after["tables"]["workflows"] = {"present": False, "rows": 0}
    comparison = compare_tenant_count_snapshots(missing_before, missing_after)
    assert comparison["ok"] is False
    assert comparison["differences"]["workflows"]["status"] == (
        "table_missing_after"
    )

    json_path = tmp_path / "counts.json"
    csv_path = tmp_path / "counts.csv"
    write_snapshot_files(before, json_path=json_path, csv_path=csv_path)
    assert json.loads(json_path.read_text(encoding="utf-8")) == before
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == (
        "table,present,rows"
    )


def _legacy_gate_payload(*, mode, pending, statuses, dry_run=True):
    items = [
        {
            "table": "resumes",
            "row_id": str(UUID(int=index + 1)),
            "tenant_id": str(UUID(int=100 + index)),
            "fingerprint": f"{index + 1:064x}",
            "status": status,
            "file_id": None,
        }
        for index, status in enumerate(statuses)
    ]
    return {
        "schema": "ai-interview.legacy-upload-backfill",
        "version": 1,
        "ok": True,
        "mode": mode,
        "dry_run": dry_run,
        "counts": {
            "candidates": len(items),
            "pending": pending,
            "errors": 0,
        },
        "items": items,
    }


def test_legacy_backfill_gate_binds_exact_candidate_fingerprints():
    from scripts.legacy_backfill_gate import (
        LegacyBackfillGateError,
        finalize_legacy_backfill,
        plan_legacy_backfill,
    )

    inventory = _legacy_gate_payload(
        mode="inventory",
        pending=2,
        statuses=["would_migrate", "would_migrate"],
    )
    # Model two audio references in one row: row identity is deliberately equal,
    # while the non-secret fingerprints bind their distinct JSON paths/values.
    inventory["items"][1]["table"] = inventory["items"][0]["table"] = "interviews"
    inventory["items"][1]["tenant_id"] = inventory["items"][0]["tenant_id"]
    inventory["items"][1]["row_id"] = inventory["items"][0]["row_id"]
    dry_run = json.loads(json.dumps(inventory))
    dry_run["mode"] = "migrate"

    plan = plan_legacy_backfill(inventory, dry_run)
    assert plan["candidate_fingerprints"] == [
        inventory["items"][0]["fingerprint"],
        inventory["items"][1]["fingerprint"],
    ]

    migration = json.loads(json.dumps(dry_run))
    migration["dry_run"] = False
    migration["counts"]["pending"] = 0
    for item in migration["items"]:
        item["status"] = "migrated"
    assert finalize_legacy_backfill(plan, migration)["stored_files_increase"] == 2

    migration["items"][1]["fingerprint"] = "f" * 64
    with pytest.raises(LegacyBackfillGateError):
        finalize_legacy_backfill(plan, migration)


def test_legacy_backfill_gate_zero_pending_skips_real_migration():
    from scripts.legacy_backfill_gate import (
        finalize_legacy_backfill,
        plan_legacy_backfill,
    )

    inventory = _legacy_gate_payload(
        mode="inventory", pending=0, statuses=[]
    )
    dry_run = _legacy_gate_payload(mode="migrate", pending=0, statuses=[])

    plan = plan_legacy_backfill(inventory, dry_run)

    assert plan["ok"] is True
    assert plan["action"] == "skip"
    assert plan["pending"] == 0
    assert finalize_legacy_backfill(plan)["stored_files_increase"] == 0


def test_legacy_backfill_gate_positive_pending_requires_exact_migrated_count():
    from scripts.legacy_backfill_gate import (
        LegacyBackfillGateError,
        finalize_legacy_backfill,
        plan_legacy_backfill,
    )

    inventory = _legacy_gate_payload(
        mode="inventory",
        pending=2,
        statuses=["would_migrate", "would_migrate"],
    )
    dry_run = _legacy_gate_payload(
        mode="migrate",
        pending=2,
        statuses=["would_migrate", "would_migrate"],
    )
    plan = plan_legacy_backfill(inventory, dry_run)
    migration = _legacy_gate_payload(
        mode="migrate",
        pending=0,
        statuses=["migrated", "migrated"],
        dry_run=False,
    )

    assert plan["action"] == "migrate"
    assert finalize_legacy_backfill(plan, migration)[
        "stored_files_increase"
    ] == 2

    migration["items"][1]["status"] = "already_migrated"
    with pytest.raises(LegacyBackfillGateError):
        finalize_legacy_backfill(plan, migration)


def test_legacy_backfill_gate_cli_handles_zero_and_positive_paths(tmp_path):
    from scripts.legacy_backfill_gate import run_cli as run_legacy_gate_cli

    inventory_path = tmp_path / "inventory.json"
    dry_run_path = tmp_path / "dry-run.json"
    plan_path = tmp_path / "plan.json"
    migration_path = tmp_path / "migration.json"

    inventory_path.write_text(
        json.dumps(_legacy_gate_payload(mode="inventory", pending=0, statuses=[])),
        encoding="utf-8",
    )
    dry_run_path.write_text(
        json.dumps(_legacy_gate_payload(mode="migrate", pending=0, statuses=[])),
        encoding="utf-8",
    )
    output = io.StringIO()
    assert run_legacy_gate_cli(
        [
            "plan",
            "--inventory",
            str(inventory_path),
            "--dry-run",
            str(dry_run_path),
        ],
        stdout=output,
    ) == 0
    zero_plan = json.loads(output.getvalue())
    assert zero_plan["action"] == "skip"
    plan_path.write_text(json.dumps(zero_plan), encoding="utf-8")
    output = io.StringIO()
    assert run_legacy_gate_cli(
        ["finalize", "--plan", str(plan_path)], stdout=output
    ) == 0
    assert json.loads(output.getvalue())["stored_files_increase"] == 0

    inventory_path.write_text(
        json.dumps(
            _legacy_gate_payload(
                mode="inventory",
                pending=2,
                statuses=["would_migrate", "would_migrate"],
            )
        ),
        encoding="utf-8",
    )
    dry_run_path.write_text(
        json.dumps(
            _legacy_gate_payload(
                mode="migrate",
                pending=2,
                statuses=["would_migrate", "would_migrate"],
            )
        ),
        encoding="utf-8",
    )
    output = io.StringIO()
    assert run_legacy_gate_cli(
        [
            "plan",
            "--inventory",
            str(inventory_path),
            "--dry-run",
            str(dry_run_path),
        ],
        stdout=output,
    ) == 0
    positive_plan = json.loads(output.getvalue())
    assert positive_plan["action"] == "migrate"
    plan_path.write_text(json.dumps(positive_plan), encoding="utf-8")
    migration_path.write_text(
        json.dumps(
            _legacy_gate_payload(
                mode="migrate",
                pending=0,
                statuses=["migrated", "migrated"],
                dry_run=False,
            )
        ),
        encoding="utf-8",
    )
    output = io.StringIO()
    assert run_legacy_gate_cli(
        [
            "finalize",
            "--plan",
            str(plan_path),
            "--migration",
            str(migration_path),
        ],
        stdout=output,
    ) == 0
    assert json.loads(output.getvalue())["stored_files_increase"] == 2


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


def test_verifier_counts_every_nested_non_managed_audio_reference(tmp_path):
    engine = _controlled_database(tmp_path)
    with engine.begin() as connection:
        tenant_a, _tenant_b = _seed_two_tenants(connection)
        connection.execute(
            text(
                "INSERT INTO interviews (id, tenant_id, audio_records) "
                "VALUES (:id, :tenant_id, :audio_records)"
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_a,
                "audio_records": json.dumps(
                    {
                        "questions": [
                            "/api/files/11111111-1111-1111-1111-111111111111",
                            "uploads/audio/question.wav",
                            "./uploads/audio/second.wav",
                        ],
                        "full": {"path": "/uploads/full_audio/full.wav"},
                    }
                ),
            },
        )
        connection.execute(
            text(
                "INSERT INTO interview_panels (id, tenant_id, audio_records) "
                "VALUES (:id, :tenant_id, :audio_records)"
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_a,
                "audio_records": json.dumps(
                    {"nested": [{"answer": "audio/panel.wav"}]}
                ),
            },
        )
        result = verify_tenant_integrity(connection)

    assert result.counts["legacy_files_pending"]["interview_audio"] == 4
    audio_violations = [
        item for item in result.violations
        if item["code"] == "legacy_file_pending"
        and item["resource"] == "interview_audio"
    ]
    assert audio_violations == [
        {"code": "legacy_file_pending", "resource": "interview_audio", "count": 4}
    ]


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


def test_platform_admin_password_reset_normalizes_email_and_replaces_hash(db):
    original_password = "StrongPlatformPassword123"
    new_password = "DifferentPlatformPassword456"
    created = create_platform_admin(db, "platform@example.com", original_password)
    original_hash = created.user.hashed_password

    reset = reset_platform_admin_password(
        db,
        "  PLATFORM@Example.COM ",
        new_password,
    )

    assert reset.id == created.user.id
    assert reset.hashed_password != original_hash
    assert verify_password(new_password, reset.hashed_password)
    assert not verify_password(original_password, reset.hashed_password)


def test_platform_admin_password_reset_requires_existing_account(db):
    with pytest.raises(PlatformAdminNotFoundError):
        reset_platform_admin_password(
            db,
            "missing@example.com",
            "StrongPlatformPassword123",
        )
    assert db.execute(text("SELECT count(*) FROM platform_users")).scalar_one() == 0


@pytest.mark.parametrize(
    "password",
    ["short1", "NoDigitsInThisPassword", "123456789012345", "密" * 30 + "1a"],
)
def test_platform_admin_password_reset_rejects_invalid_password(db, password):
    created = create_platform_admin(
        db,
        "platform@example.com",
        "StrongPlatformPassword123",
    )
    original_hash = created.user.hashed_password

    with pytest.raises(PlatformAdminInputError):
        reset_platform_admin_password(db, "platform@example.com", password)

    db.refresh(created.user)
    assert created.user.hashed_password == original_hash


def test_platform_admin_password_reset_infers_the_only_account(db):
    created = create_platform_admin(
        db,
        "platform@example.com",
        "StrongPlatformPassword123",
    )

    assert _resolve_platform_admin_email(db, None) == created.user.email


def test_platform_admin_password_reset_requires_email_for_multiple_accounts(db):
    create_platform_admin(
        db,
        "first@example.com",
        "StrongPlatformPassword123",
    )
    create_platform_admin(
        db,
        "second@example.com",
        "StrongPlatformPassword456",
    )

    with pytest.raises(PlatformAdminInputError):
        _resolve_platform_admin_email(db, None)


def test_platform_admin_password_prompt_requires_matching_values():
    answers = iter(("StrongPlatformPassword123", "DifferentPassword456"))

    with pytest.raises(PlatformAdminInputError):
        _prompt_for_password(lambda _prompt: next(answers))


def test_platform_admin_password_prompt_returns_confirmed_value():
    password = "StrongPlatformPassword123"
    answers = iter((password, password))

    assert _prompt_for_password(lambda _prompt: next(answers)) == password


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


def test_candidate_fingerprint_binds_json_path_and_reference_without_disclosure():
    tenant_id = uuid4()
    row_id = uuid4()
    secret_path = "uploads/audio/private-candidate-name.webm"
    first = LegacyFileCandidate(
        "interviews", row_id, tenant_id, secret_path, "audio_records", None,
        "interview_audio", "interview", ("questions", 0, "audio_url")
    )
    second = LegacyFileCandidate(
        "interviews", row_id, tenant_id, secret_path, "audio_records", None,
        "interview_audio", "interview", ("questions", 1, "audio_url")
    )
    changed = LegacyFileCandidate(
        "interviews", row_id, tenant_id, "uploads/audio/replaced.webm",
        "audio_records", None, "interview_audio", "interview",
        ("questions", 0, "audio_url")
    )

    fingerprints = {
        candidate_fingerprint(first),
        candidate_fingerprint(second),
        candidate_fingerprint(changed),
    }
    assert len(fingerprints) == 3
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in fingerprints)
    assert all("private-candidate-name" not in value for value in fingerprints)


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


@pytest.mark.parametrize(
    "database_value",
    [
        "uploads/resumes/resume.pdf",
        "/uploads/resumes/resume.pdf",
        "./uploads/resumes/resume.pdf",
        "resumes/resume.pdf",
    ],
)
def test_legacy_backfill_normalizes_upload_root_prefix_once(
    db, tmp_path, database_value
):
    legacy_root = tmp_path / "uploads"
    source = legacy_root / "resumes" / "resume.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"resume")
    tenant_id, row_id = uuid4(), uuid4()
    _seed_resume_for_backfill(db, tenant_id, row_id, database_value)

    result = backfill_candidate(
        db,
        _candidate(tenant_id, row_id, database_value),
        legacy_root=legacy_root,
        upload_root=tmp_path / "new",
        dry_run=True,
    )

    assert result.status == "would_migrate"
    assert source.exists()


@pytest.mark.parametrize(
    "database_value",
    [
        "https://attacker.invalid/resume.pdf",
        "file:///app/uploads/resumes/resume.pdf",
        r"C:\uploads\resumes\resume.pdf",
        r"\\server\share\resume.pdf",
        r"uploads\resumes\resume.pdf",
        "uploads/resumes/../secret.pdf",
    ],
)
def test_legacy_backfill_rejects_url_drive_unc_backslash_and_parent_segments(
    db, tmp_path, database_value
):
    legacy_root = tmp_path / "uploads"
    legacy_root.mkdir()
    tenant_id, row_id = uuid4(), uuid4()
    _seed_resume_for_backfill(db, tenant_id, row_id, database_value)

    with pytest.raises(LegacyFileError):
        backfill_candidate(
            db,
            _candidate(tenant_id, row_id, database_value),
            legacy_root=legacy_root,
            upload_root=tmp_path / "new",
            dry_run=True,
        )

    assert db.query(StoredFile).count() == 0


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
