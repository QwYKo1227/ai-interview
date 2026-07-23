import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKeyConstraint, MetaData, String, Table, UniqueConstraint, create_engine, event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import default
from sqlalchemy.schema import AddConstraint, CreateTable

from app.models.base import Base
from app.models.models import (
    CodingSubmission,
    CodingTest,
    DepartmentReview,
    Interview,
    InterviewPanel,
    Offer,
    OfferTemplate,
    Position,
    QuestionBank,
    Resume,
    SystemConfig,
    User,
)
from app.models.file_models import StoredFile
from app.models.tenant_models import TenantScopedMixin, TenantStatus
from app.models.tenant_constraints import TenantForeignKeyConstraint
from app.models.tenant_autogenerate import render_tenant_constraint
from app.models.workflow_models import (
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowNodeExecution,
)


FOUNDATION_TENANT_MODELS = [
    User,
    Position,
    QuestionBank,
    Resume,
    DepartmentReview,
    Interview,
    InterviewPanel,
    Offer,
    OfferTemplate,
    CodingTest,
    CodingSubmission,
    SystemConfig,
    Workflow,
    WorkflowNode,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNodeExecution,
]
TENANT_MODELS = [*FOUNDATION_TENANT_MODELS, StoredFile]

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "l1m2n3o4p5q6_add_multi_tenant_foundation.py"
)
RLS_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "n3o4p5q6r7s8_enforce_tenant_rls.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("tenant_foundation_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_rls_migration():
    spec = importlib.util.spec_from_file_location("tenant_rls_migration", RLS_MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_every_business_model_has_non_nullable_uuid_tenant_id(model):
    assert issubclass(model, TenantScopedMixin)
    assert "tenant_id" in model.__table__.columns

    tenant_id = model.__table__.c.tenant_id
    assert isinstance(tenant_id.type, UUID)
    assert tenant_id.type.as_uuid is True
    assert tenant_id.nullable is False
    assert "tenants.id" in {
        foreign_key.target_fullname for foreign_key in tenant_id.foreign_keys
    }


def _unique_constraint_columns(model):
    return {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_user_uniqueness_is_scoped_to_tenant():
    constraints = _unique_constraint_columns(User)
    casefold_index = next(
        index
        for index in User.__table__.indexes
        if index.name == "uq_users_tenant_lower_email"
    )
    expressions = tuple(str(expression) for expression in casefold_index.expressions)

    assert casefold_index.unique is True
    assert expressions[0] == "users.tenant_id"
    assert expressions[1] == "lower(users.email)"
    assert not any(name == "uq_users_tenant_email" for name, _ in constraints)
    assert ("uq_users_tenant_id_id", ("tenant_id", "id")) in constraints
    assert User.__table__.c.email.unique is not True


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_every_business_model_has_stable_tenant_identity_constraint(model):
    constraints = _unique_constraint_columns(model)
    assert (
        f"uq_{model.__tablename__}_tenant_id_id",
        ("tenant_id", "id"),
    ) in constraints


def test_system_config_is_unique_per_tenant_not_global_singleton():
    constraints = _unique_constraint_columns(SystemConfig)

    assert ("uq_system_configs_tenant", ("tenant_id",)) in constraints
    assert not any(name == "uq_system_configs_singleton_key" for name, _ in constraints)
    assert not any(
        constraint.name == "ck_system_configs_singleton_key_true"
        for constraint in SystemConfig.__table__.constraints
    )


def test_migration_targets_current_head_and_uses_the_stored_tenant_status_value():
    migration = _load_migration()

    assert migration.revision == "l1m2n3o4p5q6"
    assert migration.down_revision == "k0l1m2n3o4p5"
    assert migration.DEFAULT_TENANT_CODE == "careray"
    assert migration.DEFAULT_TENANT_STATUS == TenantStatus.ACTIVE.value == "active"


def test_migration_covers_every_business_table():
    migration = _load_migration()

    assert set(migration.TENANT_TABLES) == {
        model.__tablename__ for model in FOUNDATION_TENANT_MODELS
    }


def test_final_rls_migration_covers_every_business_table_including_stored_files():
    migration = _load_rls_migration()

    assert set(migration.TENANT_TABLES) == {
        model.__tablename__ for model in TENANT_MODELS
    }


def test_final_rls_table_inventory_exactly_matches_all_mapped_scoped_models():
    migration = _load_rls_migration()
    mapped_scoped_tables = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantScopedMixin)
        and not mapper.local_table.name.startswith("test_")
    }

    assert set(migration.TENANT_TABLES) == mapped_scoped_tables
    assert set(migration.TENANT_TABLES).isdisjoint(migration.GLOBAL_TABLES)


def _composite_foreign_keys(model):
    return {
        tuple(element.parent.name for element in constraint.elements): constraint
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and len(constraint.elements) == 2
    }


@pytest.mark.parametrize(
    ("model", "local_column", "target_table", "ondelete", "set_null_columns"),
    [
        (Position, "hiring_manager_id", "users", None, ()),
        (QuestionBank, "source_file_id", "stored_files", None, ()),
        (QuestionBank, "position_id", "positions", None, ()),
        (Resume, "position_id", "positions", None, ()),
        (Resume, "file_id", "stored_files", None, ()),
        (Resume, "rejected_by", "users", "SET NULL", ("rejected_by",)),
        (DepartmentReview, "resume_id", "resumes", "CASCADE", ()),
        (DepartmentReview, "reviewer_id", "users", "CASCADE", ()),
        (Interview, "resume_id", "resumes", None, ()),
        (Interview, "position_id", "positions", None, ()),
        (Interview, "interviewer_id", "users", None, ()),
        (InterviewPanel, "interview_id", "interviews", None, ()),
        (InterviewPanel, "interviewer_id", "users", None, ()),
        (Offer, "resume_id", "resumes", None, ()),
        (Offer, "position_id", "positions", None, ()),
        (Offer, "created_by", "users", None, ()),
        (OfferTemplate, "position_id", "positions", None, ()),
        (OfferTemplate, "created_by", "users", None, ()),
        (CodingTest, "question_bank_id", "question_banks", None, ()),
        (CodingTest, "created_by", "users", None, ()),
        (CodingTest, "resume_id", "resumes", None, ()),
        (CodingTest, "position_id", "positions", None, ()),
        (CodingSubmission, "coding_test_id", "coding_tests", None, ()),
        (Workflow, "created_by", "users", None, ()),
        (WorkflowNode, "workflow_id", "workflows", None, ()),
        (WorkflowEdge, "workflow_id", "workflows", None, ()),
        (WorkflowExecution, "workflow_id", "workflows", None, ()),
        (WorkflowExecution, "triggered_by", "users", None, ()),
        (WorkflowNodeExecution, "execution_id", "workflow_executions", None, ()),
    ],
)
def test_tenant_local_references_match_migration_semantics(
    model, local_column, target_table, ondelete, set_null_columns
):
    migration = _load_rls_migration()
    constraint = _composite_foreign_keys(model)[("tenant_id", local_column)]

    assert isinstance(constraint, TenantForeignKeyConstraint)
    assert tuple(
        element.target_fullname for element in constraint.elements
    ) == (f"{target_table}.tenant_id", f"{target_table}.id")
    assert constraint.ondelete == ondelete
    assert tuple(
        constraint.postgresql_set_null_columns
    ) == set_null_columns
    assert (
        model.__tablename__,
        local_column,
        target_table,
        ondelete,
        next(
            legacy_name
            for child, column, parent, action, legacy_name
            in migration.COMPOSITE_FOREIGN_KEYS
            if (child, column, parent, action)
            == (model.__tablename__, local_column, target_table, ondelete)
        ),
    ) in migration.COMPOSITE_FOREIGN_KEYS
    assert migration.POSTGRESQL_SET_NULL_COLUMNS.get(
        (model.__tablename__, local_column), ()
    ) == set_null_columns


def test_partial_set_null_constraint_compiles_per_dialect():
    constraint = _composite_foreign_keys(Resume)[("tenant_id", "rejected_by")]
    postgres_ddl = str(
        CreateTable(Resume.__table__).compile(dialect=postgresql.dialect())
    )
    sqlite_ddl = str(CreateTable(Resume.__table__).compile(dialect=sqlite.dialect()))
    default_ddl = str(
        AddConstraint(constraint).compile(dialect=default.DefaultDialect())
    )

    assert (
        "FOREIGN KEY(tenant_id, rejected_by) REFERENCES users (tenant_id, id) "
        "ON DELETE SET NULL (rejected_by)"
    ) in postgres_ddl
    assert (
        "FOREIGN KEY(rejected_by) REFERENCES users (id) "
        "ON DELETE SET NULL"
    ) in sqlite_ddl
    assert "SET NULL (rejected_by)" not in sqlite_ddl
    assert "ON DELETE SET NULL" not in default_ddl


def test_sqlite_partial_set_null_fallback_preserves_tenant_id():
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("tenant_id", String, nullable=False),
        Column("id", String, primary_key=True),
        UniqueConstraint("tenant_id", "id"),
    )
    resumes = Table(
        "resumes",
        metadata,
        Column("tenant_id", String, nullable=False),
        Column("id", String, primary_key=True),
        Column("rejected_by", String),
        TenantForeignKeyConstraint(
            ["tenant_id", "rejected_by"],
            ["users.tenant_id", "users.id"],
            name="fk_resumes_rejected_by_tenant",
            ondelete="SET NULL",
            postgresql_set_null_columns=("rejected_by",),
        ),
    )
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(users.insert().values(tenant_id="tenant-a", id="user-a"))
        connection.execute(
            resumes.insert().values(
                tenant_id="tenant-a", id="resume-a", rejected_by="user-a"
            )
        )
        connection.execute(users.delete().where(users.c.id == "user-a"))
        row = connection.execute(
            select(resumes.c.tenant_id, resumes.c.rejected_by)
        ).one()

    assert row.tenant_id == "tenant-a"
    assert row.rejected_by is None


def test_alembic_renderer_preserves_partial_set_null_metadata():
    class AutogenContext:
        imports = set()

    constraint = _composite_foreign_keys(Resume)[("tenant_id", "rejected_by")]
    context = AutogenContext()
    rendered = render_tenant_constraint("foreign_key", constraint, context)

    assert "TenantForeignKeyConstraint" in rendered
    assert "ondelete='SET NULL'" in rendered
    assert "postgresql_set_null_columns=('rejected_by',)" in rendered
    assert context.imports == {
        "from app.models.tenant_constraints import TenantForeignKeyConstraint"
    }


def test_migration_does_not_enable_row_level_security_early():
    migration = _load_migration()
    source = inspect.getsource(migration).upper()

    assert "ROW LEVEL SECURITY" not in source
    assert "CREATE POLICY" not in source
