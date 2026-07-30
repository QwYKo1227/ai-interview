from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "x3y4z5a6b7c8_normalize_workflow_enum_values.py"
)


def _load_migration():
    spec = spec_from_file_location("workflow_enum_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_workflow_enum_migration_follows_current_head():
    migration = _load_migration()

    assert migration.revision == "x3y4z5a6b7c8"
    assert migration.down_revision == "w2x3y4z5a6b7"


def test_workflow_enum_migration_normalizes_every_model_value(monkeypatch):
    migration = _load_migration()
    renamed_values = []
    renamed_types = []
    monkeypatch.setattr(
        migration,
        "_rename_legacy_execution_type",
        lambda: renamed_types.append(("executionstatus", "workflowexecutionstatus")),
    )
    monkeypatch.setattr(
        migration,
        "_rename_enum_value",
        lambda enum_type, old, new: renamed_values.append((enum_type, old, new)),
    )

    migration.upgrade()

    assert renamed_types == [("executionstatus", "workflowexecutionstatus")]
    assert renamed_values == [
        (enum_type, old, new)
        for enum_type, renames in migration.ENUM_VALUE_RENAMES.items()
        for old, new in renames
    ]
    assert ("workflowstatus", "PUBLISHED", "published") in renamed_values
    assert ("workflowexecutionstatus", "RUNNING", "running") in renamed_values
    assert ("nodetype", "HUMAN_INPUT", "human_input") in renamed_values


def test_workflow_enum_value_rename_is_safe_for_already_normalized_schema(
    monkeypatch,
):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._rename_enum_value("workflowstatus", "PUBLISHED", "published")

    assert len(statements) == 1
    statement = statements[0]
    assert "pg_enum" in statement
    assert "enum.enumlabel = 'PUBLISHED'" in statement
    assert "enum.enumlabel = 'published'" in statement
    assert "RENAME VALUE 'PUBLISHED' TO 'published'" in statement
