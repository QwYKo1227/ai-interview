from pathlib import Path


def test_departed_resume_status_migration_adds_enum_and_backfills_state_and_event():
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "k2l3m4n5o6p7_add_departed_resume_status.py"
    ).read_text(encoding="utf-8")

    assert "ALTER TYPE resumestatus ADD VALUE IF NOT EXISTS 'DEPARTED'" in migration
    assert "SET status = 'DEPARTED'::resumestatus" in migration
    assert "event.source = 'departure_registration'" in migration
    assert "SET new_status = 'departed'" in migration
    assert "INSERT INTO resume_status_events" in migration
    assert "NOT EXISTS" in migration
