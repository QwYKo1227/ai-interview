from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "d5e6f7a8b9c0_map_position_status_baselines_to_creation.py"
)


def _load_migration():
    spec = spec_from_file_location("position_status_baseline_time_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_status_baseline_time_repair_follows_current_head():
    migration = _load_migration()

    assert migration.revision == "d5e6f7a8b9c0"
    assert migration.down_revision == "c4d5e6f7a8b9"


def test_status_baseline_time_repair_uses_position_creation(monkeypatch):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    repair = next(
        statement for statement in statements if "UPDATE position_events" in statement
    )
    assert "occurred_at = position.created_at AT TIME ZONE 'UTC'" in repair
    assert "event.event_type = 'STATUS_BASELINE'" in repair
    assert "event.position_id = position.id" in repair


def test_status_baseline_time_repair_is_not_reversed(monkeypatch):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    assert statements == []
