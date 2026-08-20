from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "c4d5e6f7a8b9_map_legacy_hc_round_start_to_position_creation.py"
)


def _load_migration():
    spec = spec_from_file_location("recruitment_round_start_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_round_start_repair_follows_current_head():
    migration = _load_migration()

    assert migration.revision == "c4d5e6f7a8b9"
    assert migration.down_revision == "b3c4d5e6f7a8"


def test_round_start_repair_maps_only_historical_baseline_slots(monkeypatch):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    repair = next(
        statement
        for statement in statements
        if "UPDATE recruitment_hc_slots" in statement
    )
    assert "round_started_at = position.created_at AT TIME ZONE 'UTC'" in repair
    assert "event.event_type = 'STATUS_BASELINE'" in repair
    assert "event.occurred_at = slot.round_started_at" in repair
    assert "slot.round_started_at = slot.created_at" in repair


def test_round_start_repair_is_not_reversed(monkeypatch):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    assert statements == []
