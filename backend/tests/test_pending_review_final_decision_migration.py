from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "b3c4d5e6f7a8_repair_pending_review_final_decisions.py"
)


def _load_migration():
    spec = spec_from_file_location(
        "pending_review_final_decision_migration",
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
    def __init__(self, tenant_ids=()):
        self.tenant_ids = tenant_ids
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "SELECT id FROM tenants" in sql:
            return _ScalarRows(self.tenant_ids)
        return _ScalarRows(())


def test_pending_review_repair_follows_current_head():
    migration = _load_migration()

    assert migration.revision == "b3c4d5e6f7a8"
    assert migration.down_revision == "a2b3c4d5e6f7"


def test_pending_review_repair_updates_final_decision_and_records_event():
    migration = _load_migration()
    connection = _Connection()

    migration._repair_tenant_final_decisions(connection)

    statement = connection.calls[0][0]
    assert "final_decision_at IS NOT NULL" in statement
    assert "resume.status = 'PENDING_REVIEW'" in statement
    assert "THEN 'INTERVIEW_PASSED'" in statement
    assert "THEN 'INTERVIEW_FAILED'" in statement
    assert "THEN 'PENDING_NEXT_INTERVIEW'" in statement
    assert "INSERT INTO resume_status_events" in statement
    assert "'interview_backfill'" in statement


def test_pending_review_repair_sets_rls_context_for_every_tenant(monkeypatch):
    migration = _load_migration()
    connection = _Connection(("tenant-a", "tenant-b"))
    repaired = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(
        migration,
        "_repair_tenant_final_decisions",
        lambda current: repaired.append(current.calls[-1][1]["tenant_id"]),
    )

    migration.upgrade()

    assert repaired == ["tenant-a", "tenant-b"]
    assert connection.calls[-1][1] is None
    assert "set_config('app.current_tenant_id', '', true)" in (
        connection.calls[-1][0]
    )
