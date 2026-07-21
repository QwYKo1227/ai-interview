import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

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
from app.models.tenant_models import TenantScopedMixin, TenantStatus
from app.models.workflow_models import (
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowNodeExecution,
)


TENANT_MODELS = [
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

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "l1m2n3o4p5q6_add_multi_tenant_foundation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("tenant_foundation_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_every_business_model_has_nullable_uuid_tenant_id(model):
    assert issubclass(model, TenantScopedMixin)
    assert "tenant_id" in model.__table__.columns

    tenant_id = model.__table__.c.tenant_id
    assert isinstance(tenant_id.type, UUID)
    assert tenant_id.type.as_uuid is True
    assert tenant_id.nullable is True
    assert {foreign_key.target_fullname for foreign_key in tenant_id.foreign_keys} == {
        "tenants.id"
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
        model.__tablename__ for model in TENANT_MODELS
    }


def test_migration_does_not_enable_row_level_security_early():
    migration = _load_migration()
    source = inspect.getsource(migration).upper()

    assert "ROW LEVEL SECURITY" not in source
    assert "CREATE POLICY" not in source
