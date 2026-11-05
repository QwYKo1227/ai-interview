import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_preserves_old_rows_without_inventing_operation_times():
    path = Path(__file__).parents[1] / "alembic/versions/rq20261104a2_add_onboarding_recorded_at.py"
    spec = importlib.util.spec_from_file_location("onboarding_timestamp_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE offers (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO offers (id) VALUES (1)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(sa.text("SELECT onboarding_recorded_at FROM offers")).scalar() is None
        connection.execute(sa.text("UPDATE offers SET onboarding_recorded_at = '2026-11-04 10:00:00'"))
        assert connection.execute(sa.text("SELECT onboarding_recorded_at FROM offers")).scalar()
        migration.downgrade()
        assert [c["name"] for c in sa.inspect(connection).get_columns("offers")] == ["id"]
