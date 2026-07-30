from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "y4z5a6b7c8d9_backfill_interview_statuses_per_tenant.py"
)


def _load_migration():
    spec = spec_from_file_location(
        "interview_status_backfill_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class _ScalarRows:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return iter(self._values)


class _Connection:
    def __init__(self, tenant_ids):
        self.tenant_ids = tenant_ids
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "SELECT id FROM tenants" in sql:
            return _ScalarRows(self.tenant_ids)
        return _ScalarRows(())


def test_interview_status_backfill_follows_workflow_enum_repair():
    migration = _load_migration()

    assert migration.revision == "y4z5a6b7c8d9"
    assert migration.down_revision == "x3y4z5a6b7c8"


def test_interview_status_backfill_sets_rls_context_for_every_tenant(
    monkeypatch,
):
    migration = _load_migration()
    connection = _Connection(("tenant-a", "tenant-b"))
    repaired = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(
        migration,
        "_repair_tenant_statuses",
        lambda current: repaired.append(current.calls[-1][1]["tenant_id"]),
    )

    migration.upgrade()

    assert repaired == ["tenant-a", "tenant-b"]
    tenant_contexts = [
        parameters["tenant_id"]
        for sql, parameters in connection.calls
        if "set_config" in sql and parameters
    ]
    assert tenant_contexts == ["tenant-a", "tenant-b"]
    assert connection.calls[-1][1] is None
    assert "set_config('app.current_tenant_id', '', true)" in (
        connection.calls[-1][0]
    )


def test_interview_status_backfill_repairs_lifecycle_and_resume_statuses():
    migration = _load_migration()
    connection = _Connection(())

    migration._repair_tenant_statuses(connection)

    statements = "\n".join(sql for sql, _parameters in connection.calls)
    assert "WHERE lifecycle_state = 'scheduled'" in statements
    assert "status::text IN (" in statements
    assert "PENDING_INTERVIEW_RESULT" in statements
    assert "INTERVIEW_SCHEDULED" in statements
    assert "PENDING_NEXT_INTERVIEW" in statements
    assert "final_decision_at IS NULL" in statements
    assert "resumes.tenant_id = resolved.tenant_id" in statements
