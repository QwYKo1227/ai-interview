import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

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

    assert ("uq_users_tenant_email", ("tenant_id", "email")) in constraints
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
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and len(constraint.elements) == 2
    }


@pytest.mark.parametrize(
    ("model", "local_column", "target_table"),
    [
        (Position, "hiring_manager_id", "users"),
        (QuestionBank, "source_file_id", "stored_files"),
        (QuestionBank, "position_id", "positions"),
        (Resume, "position_id", "positions"),
        (Resume, "file_id", "stored_files"),
        (Resume, "rejected_by", "users"),
        (DepartmentReview, "resume_id", "resumes"),
        (DepartmentReview, "reviewer_id", "users"),
        (Interview, "resume_id", "resumes"),
        (Interview, "position_id", "positions"),
        (Interview, "interviewer_id", "users"),
        (InterviewPanel, "interview_id", "interviews"),
        (InterviewPanel, "interviewer_id", "users"),
        (Offer, "resume_id", "resumes"),
        (Offer, "position_id", "positions"),
        (Offer, "created_by", "users"),
        (OfferTemplate, "position_id", "positions"),
        (OfferTemplate, "created_by", "users"),
        (CodingTest, "question_bank_id", "question_banks"),
        (CodingTest, "created_by", "users"),
        (CodingTest, "resume_id", "resumes"),
        (CodingTest, "position_id", "positions"),
        (CodingSubmission, "coding_test_id", "coding_tests"),
        (Workflow, "created_by", "users"),
        (WorkflowNode, "workflow_id", "workflows"),
        (WorkflowEdge, "workflow_id", "workflows"),
        (WorkflowExecution, "workflow_id", "workflows"),
        (WorkflowExecution, "triggered_by", "users"),
        (WorkflowNodeExecution, "execution_id", "workflow_executions"),
    ],
)
def test_tenant_local_references_use_composite_foreign_keys(
    model, local_column, target_table
):
    assert (
        ("tenant_id", local_column),
        (f"{target_table}.tenant_id", f"{target_table}.id"),
    ) in _composite_foreign_keys(model)


def test_migration_does_not_enable_row_level_security_early():
    migration = _load_migration()
    source = inspect.getsource(migration).upper()

    assert "ROW LEVEL SECURITY" not in source
    assert "CREATE POLICY" not in source
