from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "a6b7c8d9e0f1_add_offer_decision_audits.py"
)
REPAIR_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "d9e0f1a2b3c4_grant_offer_decision_audit_runtime_access.py"
)


def _load_migration():
    spec = spec_from_file_location("offer_decision_audit_migration", MIGRATION_PATH)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _load_repair_migration():
    spec = spec_from_file_location(
        "offer_decision_audit_permission_repair", REPAIR_MIGRATION_PATH
    )
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_offer_decision_audit_migration_grants_runtime_table_access(monkeypatch):
    migration = _load_migration()
    statements = []

    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    normalized = [" ".join(statement.split()) for statement in statements]
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON TABLE offer_decision_audits TO app_runtime"
    ) in normalized


def test_repair_migration_grants_existing_installations_runtime_access(monkeypatch):
    migration = _load_repair_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert migration.down_revision == "b7c8d9e0f1a3"
    assert statements == [
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON TABLE offer_decision_audits TO app_runtime"
    ]
