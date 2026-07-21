import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from app.config.database import get_unscoped_db
from app.config.tenant_session import TenantSession
from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    CodingTest,
    CodingTestStatus,
    Offer,
    OfferStatus,
    OfferTemplate,
    Position,
    PositionStatus,
    QuestionBank,
    Resume,
    ResumeStatus,
    SystemConfig,
    User,
    UserRole,
)
from app.models.tenant_models import Tenant
from app.models.workflow_models import (
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowNodeExecution,
    WorkflowStatus,
)
from app.routes import (
    coding_tests,
    dashboard,
    offer_templates,
    offers,
    settings,
    workflows,
)
from app.schemas.offer_template import OfferTemplateCreate
from app.services.offer_template_service import create_template


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


PROTECTED_ROUTE_FILES = [
    "positions.py",
    "resumes.py",
    "interviews.py",
    "question_banks.py",
    "offers.py",
    "offer_templates.py",
    "coding_tests.py",
    "dashboard.py",
    "settings.py",
    "workflows.py",
]

PUBLIC_ROUTE_FUNCTIONS = {
    "positions.py": {"get_public_positions_route"},
    "resumes.py": {"create_resume_route"},
    "coding_tests.py": {
        "get_public_coding_test_route",
        "run_public_code_route",
        "submit_public_code_route",
        "submit_choice_route",
        "submit_essay_route",
        "get_public_submission_route",
    },
    "offers.py": {"get_offer_by_token", "confirm_offer_by_token"},
}


@pytest.fixture
def question_bank_table(db: Session):
    QuestionBank.__table__.create(bind=db.get_bind(), checkfirst=True)
    try:
        yield
    finally:
        QuestionBank.__table__.drop(bind=db.get_bind(), checkfirst=True)


@pytest.fixture
def offer_template_table(db: Session):
    OfferTemplate.__table__.create(bind=db.get_bind(), checkfirst=True)
    try:
        yield
    finally:
        OfferTemplate.__table__.drop(bind=db.get_bind(), checkfirst=True)


@pytest.fixture
def special_resource_tables(db: Session):
    tables = [
        Offer.__table__,
        Workflow.__table__,
        WorkflowNode.__table__,
        WorkflowEdge.__table__,
        WorkflowExecution.__table__,
        WorkflowNodeExecution.__table__,
    ]
    for table in tables:
        table.create(bind=db.get_bind(), checkfirst=True)
    try:
        yield
    finally:
        for table in reversed(tables):
            table.drop(bind=db.get_bind(), checkfirst=True)


@pytest.fixture
def tenant_b_user(db: Session, tenant_b: Tenant) -> User:
    user = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email="tenant-b-hr@example.com",
        hashed_password=get_password_hash("Password123"),
        full_name="Tenant B HR",
        role=UserRole.HR,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def tenant_b_position(db: Session, tenant_b: Tenant) -> Position:
    position = Position(
        id=uuid4(),
        tenant_id=tenant_b.id,
        title="Tenant B Position",
        description="Must not be visible to tenant A",
        status=PositionStatus.OPEN,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


@pytest.fixture
def tenant_b_headers(tenant_b_user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=tenant_b_user.id,
        tenant_id=tenant_b_user.tenant_id,
        role=tenant_b_user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def dashboard_client(db: Session):
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api")

    def override_unscoped_db():
        yield db

    app.dependency_overrides[get_unscoped_db] = override_unscoped_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def business_client(db: Session):
    app = FastAPI()
    app.include_router(coding_tests.router, prefix="/api")
    app.include_router(offer_templates.router, prefix="/api")
    app.include_router(offers.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")

    def override_unscoped_db():
        yield db

    app.dependency_overrides[get_unscoped_db] = override_unscoped_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.usefixtures("question_bank_table")
@pytest.mark.parametrize(
    ("method", "payload"),
    [
        ("get", None),
        ("put", {"title": "stolen"}),
        ("delete", None),
    ],
)
def test_tenant_cannot_read_update_or_delete_other_tenant_position(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_b_position: Position,
    method: str,
    payload: dict | None,
):
    response = client.request(
        method,
        f"/api/positions/{tenant_b_position.id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 404


@pytest.mark.usefixtures("question_bank_table")
def test_position_list_only_contains_current_tenant(
    client: TestClient,
    auth_headers: dict[str, str],
    test_position: Position,
    tenant_b_position: Position,
):
    response = client.get("/api/positions", headers=auth_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(test_position.id)]


@pytest.mark.usefixtures("question_bank_table")
def test_position_create_uses_jwt_tenant_and_ignores_malicious_tenant_id(
    client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    response = client.post(
        "/api/positions",
        headers=auth_headers,
        json={
            "title": "Scoped position",
            "description": "Created through a tenant session",
            "tenant_id": str(tenant_b.id),
        },
    )

    assert response.status_code == 200
    created = db.query(Position).filter(Position.id == UUID(response.json()["id"])).one()
    assert created.tenant_id == tenant_a.id


@pytest.mark.usefixtures("question_bank_table")
def test_dashboard_counts_only_current_tenant(
    dashboard_client: TestClient,
    auth_headers: dict[str, str],
    test_position: Position,
    tenant_b_position: Position,
):
    response = dashboard_client.get("/api/dashboard/stats", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["stats"]["active_positions"] == 1


@pytest.mark.usefixtures("offer_template_table")
def test_creating_default_offer_template_only_clears_current_tenant_defaults(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
    test_user: User,
):
    tenant_a_default = OfferTemplate(
        tenant_id=tenant_a.id,
        name="Tenant A default",
        is_default=True,
    )
    tenant_b_default = OfferTemplate(
        tenant_id=tenant_b.id,
        name="Tenant B default",
        is_default=True,
    )
    db.add_all([tenant_a_default, tenant_b_default])
    db.commit()

    factory = sessionmaker(bind=db.get_bind(), class_=TenantSession)
    with factory(tenant_id=tenant_a.id) as tenant_db:
        created = create_template(
            tenant_db,
            OfferTemplateCreate(name="New tenant A default", is_default=True),
            test_user.id,
        )
        assert created.tenant_id == tenant_a.id

    db.expire_all()
    assert db.get(OfferTemplate, tenant_a_default.id).is_default is False
    assert db.get(OfferTemplate, tenant_b_default.id).is_default is True


@pytest.mark.usefixtures("offer_template_table")
def test_cross_tenant_position_never_falls_back_to_global_offer_template(
    business_client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    test_user: User,
    tenant_b_position: Position,
):
    global_template = OfferTemplate(
        tenant_id=test_user.tenant_id,
        name="Tenant A global default",
        is_default=True,
        is_active=True,
        created_by=test_user.id,
    )
    db.add(global_template)
    db.commit()

    response = business_client.get(
        f"/api/offer-templates/default/{tenant_b_position.id}",
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_coding_test_list_and_uuid_lookup_are_tenant_scoped(
    business_client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    test_user: User,
    tenant_b_user: User,
):
    tenant_a_test = CodingTest(
        tenant_id=test_user.tenant_id,
        title="Tenant A coding test",
        public_token="tenant-a-coding-token",
        status=CodingTestStatus.DRAFT,
        created_by=test_user.id,
    )
    tenant_b_test = CodingTest(
        tenant_id=tenant_b_user.tenant_id,
        title="Tenant B coding test",
        public_token="tenant-b-coding-token",
        status=CodingTestStatus.DRAFT,
        created_by=tenant_b_user.id,
    )
    db.add_all([tenant_a_test, tenant_b_test])
    db.commit()

    list_response = business_client.get("/api/coding-tests", headers=auth_headers)
    cross_tenant_response = business_client.get(
        f"/api/coding-tests/{tenant_b_test.id}", headers=auth_headers
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [str(tenant_a_test.id)]
    assert cross_tenant_response.status_code == 404


@pytest.mark.usefixtures("special_resource_tables")
def test_offer_list_stats_and_uuid_lookup_are_tenant_scoped(
    business_client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    test_user: User,
    tenant_b_user: User,
    test_position: Position,
    test_resume: Resume,
    tenant_b_position: Position,
):
    tenant_b_resume = Resume(
        tenant_id=tenant_b_user.tenant_id,
        candidate_name="Tenant B candidate",
        position_id=tenant_b_position.id,
        status=ResumeStatus.PENDING_INTERVIEW,
    )
    db.add(tenant_b_resume)
    db.flush()
    tenant_a_offer = Offer(
        tenant_id=test_user.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name="Tenant A candidate",
        candidate_email="candidate-a@example.com",
        position_title=test_position.title,
        status=OfferStatus.DRAFT,
        created_by=test_user.id,
    )
    tenant_b_offer = Offer(
        tenant_id=tenant_b_user.tenant_id,
        resume_id=tenant_b_resume.id,
        position_id=tenant_b_position.id,
        candidate_name="Tenant B candidate",
        candidate_email="candidate-b@example.com",
        position_title=tenant_b_position.title,
        status=OfferStatus.DRAFT,
        created_by=tenant_b_user.id,
    )
    db.add_all([tenant_a_offer, tenant_b_offer])
    db.commit()

    list_response = business_client.get("/api/offers", headers=auth_headers)
    stats_response = business_client.get("/api/offers/stats", headers=auth_headers)
    cross_tenant_response = business_client.get(
        f"/api/offers/{tenant_b_offer.id}", headers=auth_headers
    )
    cross_tenant_mutation = business_client.post(
        f"/api/offers/{tenant_b_offer.id}/withdraw", headers=auth_headers
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [
        str(tenant_a_offer.id)
    ]
    assert stats_response.status_code == 200
    assert stats_response.json()["total_offers"] == 1
    assert cross_tenant_response.status_code == 404
    assert cross_tenant_mutation.status_code == 404


@pytest.mark.usefixtures("special_resource_tables")
def test_workflow_list_and_uuid_lookup_are_tenant_scoped(
    business_client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    test_user: User,
    tenant_b_user: User,
):
    tenant_a_workflow = Workflow(
        tenant_id=test_user.tenant_id,
        name="Tenant A workflow",
        status=WorkflowStatus.DRAFT,
        created_by=test_user.id,
    )
    tenant_b_workflow = Workflow(
        tenant_id=tenant_b_user.tenant_id,
        name="Tenant B workflow",
        status=WorkflowStatus.DRAFT,
        created_by=tenant_b_user.id,
    )
    db.add_all([tenant_a_workflow, tenant_b_workflow])
    db.commit()

    list_response = business_client.get("/api/workflows", headers=auth_headers)
    cross_tenant_response = business_client.get(
        f"/api/workflows/{tenant_b_workflow.id}", headers=auth_headers
    )
    cross_tenant_execute = business_client.post(
        f"/api/workflows/{tenant_b_workflow.id}/execute",
        headers=auth_headers,
        json={"input_data": {}},
    )
    cross_tenant_executions = business_client.get(
        f"/api/workflows/{tenant_b_workflow.id}/executions",
        headers=auth_headers,
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [
        str(tenant_a_workflow.id)
    ]
    assert cross_tenant_response.status_code == 404
    assert cross_tenant_execute.status_code == 404
    assert cross_tenant_executions.status_code == 404


def test_settings_read_and_update_only_current_tenant(
    business_client: TestClient,
    db: Session,
    admin_auth_headers: dict[str, str],
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    config_a = SystemConfig(
        tenant_id=tenant_a.id,
        llm_base_url="https://tenant-a.example.com/v1",
        llm_model="tenant-a-model",
        llm_api_key="tenant-a-secret",
    )
    config_b = SystemConfig(
        tenant_id=tenant_b.id,
        llm_base_url="https://tenant-b.example.com/v1",
        llm_model="tenant-b-model",
        llm_api_key="tenant-b-secret",
    )
    db.add_all([config_a, config_b])
    db.commit()

    read_response = business_client.get(
        "/api/settings/system", headers=admin_auth_headers
    )
    update_response = business_client.put(
        "/api/settings/system",
        headers=admin_auth_headers,
        json={
            "llm_base_url": "https://tenant-a-updated.example.com/v1",
            "llm_model": "tenant-a-updated-model",
            "llm_api_key": "tenant-a-updated-secret",
        },
    )

    assert read_response.status_code == 200
    assert read_response.json()["llm_model"] == "tenant-a-model"
    assert update_response.status_code == 200
    db.expire_all()
    assert db.get(SystemConfig, config_a.id).llm_model == "tenant-a-updated-model"
    assert db.get(SystemConfig, config_b.id).llm_model == "tenant-b-model"


def test_business_route_database_dependencies_are_explicitly_scoped():
    route_dir = Path(__file__).parents[1] / "app" / "routes"
    for filename in PROTECTED_ROUTE_FILES:
        source = (route_dir / filename).read_text(encoding="utf-8")
        assert "from app.config.database import get_db" not in source, filename
        assert "Depends(get_db)" not in source, filename

        public_functions = PUBLIC_ROUTE_FUNCTIONS.get(filename, set())
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                for decorator in node.decorator_list
            ):
                continue
            argument_names = [argument.arg for argument in node.args.args]
            if "db" not in argument_names:
                continue
            default_offset = len(argument_names) - len(node.args.defaults)
            db_default_index = argument_names.index("db") - default_offset
            assert db_default_index >= 0, f"{filename}:{node.name}:db has no default"
            db_default = node.args.defaults[db_default_index]
            dependencies = {
                call.args[0].id
                for call in ast.walk(db_default)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "Depends"
                and call.args
                and isinstance(call.args[0], ast.Name)
            }
            expected = (
                {"get_unscoped_db"}
                if node.name in public_functions
                else {"get_tenant_db"}
            )
            assert dependencies == expected, f"{filename}:{node.name}"
