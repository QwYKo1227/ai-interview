import ast
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from app.config.database import get_unscoped_db
from app.config.tenant_session import TenantSession
from app.core.security import AccessTokenClaims, create_access_token, get_password_hash
from app.core.tenant_dependencies import get_current_user_dep
from app.models.models import (
    CodingTest,
    CodingTestStatus,
    DepartmentReview,
    Interview,
    InterviewPanel,
    Offer,
    OfferStatus,
    OfferTemplate,
    Position,
    PositionStatus,
    QuestionBank,
    QuestionCategory,
    QuestionDifficulty,
    Resume,
    RejectReasonCategory,
    ResumeStatus,
    SystemConfig,
    User,
    UserRole,
)
from app.models.file_models import StoredFile
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
    interviews,
    offer_templates,
    offers,
    resumes,
    settings,
    workflows,
)
from app.schemas.offer_template import OfferTemplateCreate
from app.schemas.coding_test import CodingTestCreate, CodingTestUpdate
from app.schemas.interview import InterviewCreate
from app.schemas.offer import OfferCreate
from app.schemas.position import JDChatMessage, PositionCreate, PositionUpdate
from app.schemas.resume import DepartmentReviewUpdate, HRDecisionCreate
from app.services import (
    ai_service,
    coding_test_service,
    interview_service,
    offer_service,
    position_service,
    question_bank_service,
    resume_service,
)
from app.services.offer_template_service import create_template
from app.services.workflow_service import NodeExecutor


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
    "positions.py": {
        "get_public_positions_route",
        "get_domain_public_positions",
        "get_domain_public_position",
        "get_tenant_public_positions",
        "get_tenant_public_position",
    },
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
def tenant_b_question_bank(
    db: Session,
    tenant_b: Tenant,
    tenant_b_position: Position,
    question_bank_table,
) -> QuestionBank:
    bank = QuestionBank(
        tenant_id=tenant_b.id,
        name="Tenant B bank",
        category=QuestionCategory.TECHNICAL,
        difficulty=QuestionDifficulty.INTERMEDIATE,
        tags=None,
        questions=[],
        source_file="tenant-b.txt",
        position_id=tenant_b_position.id,
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


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
def tenant_b_resume(
    db: Session, tenant_b: Tenant, tenant_b_position: Position
) -> Resume:
    resume = Resume(
        tenant_id=tenant_b.id,
        candidate_name="Tenant B Candidate",
        position_id=tenant_b_position.id,
        status=ResumeStatus.PENDING_INTERVIEW,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@pytest.fixture
def tenant_a_db(db: Session, tenant_a: Tenant):
    with TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id) as tenant_db:
        yield tenant_db


@pytest.fixture
def tenant_b_db(db: Session, tenant_b: Tenant):
    with TenantSession(bind=db.get_bind(), tenant_id=tenant_b.id) as tenant_db:
        yield tenant_db


@pytest.fixture
def tenant_b_headers(tenant_b_user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=tenant_b_user.id,
        tenant_id=tenant_b_user.tenant_id,
        role=tenant_b_user.role.value,
        credential_version=tenant_b_user.credential_version,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tenant_b_admin(db: Session, tenant_b: Tenant) -> User:
    user = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email="tenant-b-admin@example.com",
        hashed_password=get_password_hash("Password123"),
        full_name="Tenant B Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def tenant_b_admin_headers(tenant_b_admin: User) -> dict[str, str]:
    token = create_access_token(
        user_id=tenant_b_admin.id,
        tenant_id=tenant_b_admin.tenant_id,
        role=tenant_b_admin.role.value,
        credential_version=tenant_b_admin.credential_version,
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
    app.include_router(interviews.router, prefix="/api")
    app.include_router(offer_templates.router, prefix="/api")
    app.include_router(offers.router, prefix="/api")
    app.include_router(resumes.router, prefix="/api")
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
        asr_provider="openai_compatible",
        asr_base_url="http://tenant-a-asr:9000/v1",
        asr_model="tenant-a-asr-model",
    )
    config_b = SystemConfig(
        tenant_id=tenant_b.id,
        llm_base_url="https://tenant-b.example.com/v1",
        llm_model="tenant-b-model",
        llm_api_key="tenant-b-secret",
        asr_provider="openai_compatible",
        asr_base_url="http://tenant-b-asr:9000/v1",
        asr_model="tenant-b-asr-model",
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
            "asr_provider": "openai_compatible",
            "asr_base_url": "http://tenant-a-asr-updated:9000/v1",
            "asr_model": "tenant-a-asr-updated-model",
        },
    )

    assert read_response.status_code == 200
    assert read_response.json()["llm_model"] == "tenant-a-model"
    assert read_response.json()["asr_model"] == "tenant-a-asr-model"
    assert update_response.status_code == 200
    db.expire_all()
    assert db.get(SystemConfig, config_a.id).llm_model == "tenant-a-updated-model"
    assert db.get(SystemConfig, config_a.id).asr_model == "tenant-a-asr-updated-model"
    assert db.get(SystemConfig, config_b.id).llm_model == "tenant-b-model"
    assert db.get(SystemConfig, config_b.id).asr_model == "tenant-b-asr-model"


def test_prompt_settings_get_put_and_reload_are_tenant_scoped(
    business_client: TestClient,
    db: Session,
    admin_auth_headers: dict[str, str],
    tenant_b_admin_headers: dict[str, str],
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    config_a = SystemConfig(
        tenant_id=tenant_a.id,
        prompt_configs={"tenant_prompt": {"system": "A system", "user": "A user"}},
    )
    config_b = SystemConfig(
        tenant_id=tenant_b.id,
        prompt_configs={"tenant_prompt": {"system": "B system", "user": "B user"}},
    )
    db.add_all([config_a, config_b])
    db.commit()

    response_a = business_client.get(
        "/api/settings/prompts", headers=admin_auth_headers
    )
    response_b = business_client.get(
        "/api/settings/prompts", headers=tenant_b_admin_headers
    )
    update_a = business_client.put(
        "/api/settings/prompts/tenant_prompt",
        headers=admin_auth_headers,
        json={"system": "A updated"},
    )
    reload_b = business_client.post(
        "/api/settings/prompts/reload", headers=tenant_b_admin_headers
    )
    response_b_after = business_client.get(
        "/api/settings/prompts", headers=tenant_b_admin_headers
    )

    assert response_a.status_code == 200
    assert response_a.json()["prompts"]["tenant_prompt"]["system"] == "A system"
    assert response_b.status_code == 200
    assert response_b.json()["prompts"]["tenant_prompt"]["system"] == "B system"
    assert update_a.status_code == 200
    assert reload_b.status_code == 200
    assert response_b_after.json()["prompts"]["tenant_prompt"]["system"] == "B system"
    db.expire_all()
    assert db.get(SystemConfig, config_a.id).prompt_configs["tenant_prompt"]["system"] == "A updated"
    assert db.get(SystemConfig, config_b.id).prompt_configs["tenant_prompt"]["system"] == "B system"


def test_prompt_settings_first_update_initializes_new_tenant(
    business_client: TestClient,
    db: Session,
    admin_auth_headers: dict[str, str],
    tenant_a: Tenant,
):
    response = business_client.put(
        "/api/settings/prompts/custom_prompt",
        headers=admin_auth_headers,
        json={"system": "custom system", "user": "custom user"},
    )

    assert response.status_code == 200
    config = db.query(SystemConfig).filter(SystemConfig.tenant_id == tenant_a.id).one()
    assert config.prompt_configs["custom_prompt"] == {
        "system": "custom system",
        "user": "custom user",
    }


@pytest.mark.parametrize("reference_field", ["question_bank_id", "resume_id", "position_id"])
def test_coding_test_create_rejects_cross_tenant_references(
    tenant_a_db: Session,
    test_user: User,
    tenant_b_question_bank: QuestionBank,
    tenant_b_resume: Resume,
    tenant_b_position: Position,
    reference_field: str,
):
    foreign_ids = {
        "question_bank_id": tenant_b_question_bank.id,
        "resume_id": tenant_b_resume.id,
        "position_id": tenant_b_position.id,
    }
    before = tenant_a_db.query(CodingTest).count()

    with pytest.raises(HTTPException) as exc_info:
        coding_test_service.create_coding_test(
            tenant_a_db,
            CodingTestCreate(title="Cross-tenant test", **{reference_field: foreign_ids[reference_field]}),
            test_user.id,
        )

    assert exc_info.value.status_code == 404
    assert tenant_a_db.query(CodingTest).count() == before


@pytest.mark.parametrize("reference_field", ["question_bank_id", "resume_id", "position_id"])
def test_coding_test_update_rejects_cross_tenant_references(
    tenant_a_db: Session,
    test_user: User,
    tenant_b_question_bank: QuestionBank,
    tenant_b_resume: Resume,
    tenant_b_position: Position,
    reference_field: str,
):
    db_test = coding_test_service.create_coding_test(
        tenant_a_db, CodingTestCreate(title="Tenant A test"), test_user.id
    )
    foreign_ids = {
        "question_bank_id": tenant_b_question_bank.id,
        "resume_id": tenant_b_resume.id,
        "position_id": tenant_b_position.id,
    }

    with pytest.raises(HTTPException) as exc_info:
        coding_test_service.update_coding_test(
            tenant_a_db,
            db_test.id,
            CodingTestUpdate(**{reference_field: foreign_ids[reference_field]}),
        )

    assert exc_info.value.status_code == 404
    tenant_a_db.refresh(db_test)
    assert getattr(db_test, reference_field) is None


def test_question_bank_create_rejects_cross_tenant_position_before_file_write(
    tenant_a_db: Session,
    tenant_b_position: Position,
    question_bank_table,
    monkeypatch: pytest.MonkeyPatch,
):
    writes: list[str] = []
    monkeypatch.setattr(
        question_bank_service,
        "save_upload_file",
        lambda *_args, **_kwargs: writes.append("written") or "should-not-exist.txt",
    )

    with pytest.raises(HTTPException) as exc_info:
        question_bank_service.create_question_bank(
            tenant_a_db,
            "Cross-tenant bank",
            QuestionCategory.TECHNICAL,
            QuestionDifficulty.INTERMEDIATE,
            [],
            UploadFile(filename="bank.txt", file=BytesIO(b"questions")),
            tenant_b_position.id,
        )

    assert exc_info.value.status_code == 404
    assert writes == []
    assert tenant_a_db.query(QuestionBank).count() == 0


def test_resume_batch_upload_rejects_cross_tenant_position_before_file_write(
    tenant_a_db: Session,
    tenant_b_position: Position,
    monkeypatch: pytest.MonkeyPatch,
):
    writes: list[str] = []
    monkeypatch.setattr(
        resume_service,
        "save_upload_file",
        lambda *_args, **_kwargs: writes.append("written") or "should-not-exist.pdf",
    )

    with pytest.raises(HTTPException) as exc_info:
        resume_service.batch_upload_resumes(
            tenant_a_db,
            [UploadFile(filename="resume.pdf", file=BytesIO(b"resume"))],
            tenant_b_position.id,
            BackgroundTasks(),
        )

    assert exc_info.value.status_code == 404
    assert writes == []
    assert tenant_a_db.query(Resume).count() == 0


def test_resume_upload_rejects_files_larger_than_10_mb(
    tenant_a_db: Session,
    test_position: Position,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, int] = {}

    def reject_oversized_file(*_args, **kwargs):
        captured["max_size"] = kwargs["max_size"]
        raise ValueError("uploaded file is too large")

    monkeypatch.setattr(
        resume_service,
        "save_upload_file",
        reject_oversized_file,
    )

    with pytest.raises(HTTPException) as exc_info:
        resume_service.upload_resume(
            tenant_a_db,
            UploadFile(filename="resume.pdf", file=BytesIO(b"resume")),
            test_position.id,
            BackgroundTasks(),
        )

    assert captured["max_size"] == 10 * 1024 * 1024
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "单个简历文件不能超过 10 MB"


@pytest.mark.parametrize("reference_field", ["panel_members", "question_bank_ids"])
def test_interview_create_rejects_cross_tenant_participants_and_question_banks(
    tenant_a_db: Session,
    test_resume: Resume,
    test_position: Position,
    tenant_b_user: User,
    tenant_b_question_bank: QuestionBank,
    reference_field: str,
):
    data = {
        "resume_id": test_resume.id,
        "position_id": test_position.id,
        "interview_time": "2026-08-01T10:00:00+08:00",
        "interview_location": "上海办公室",
        "meeting_link": "https://meeting.example.com/interview",
        "panel_members": [],
        "question_bank_ids": [],
        "skip_ai_questions": True,
        "skip_email": True,
    }
    if reference_field == "panel_members":
        data[reference_field] = [str(tenant_b_user.id)]
    else:
        data[reference_field] = [tenant_b_question_bank.id]

    with pytest.raises(HTTPException) as exc_info:
        interview_service.create_interview(
            tenant_a_db, InterviewCreate(**data), BackgroundTasks()
        )

    assert exc_info.value.status_code == 404
    assert tenant_a_db.query(Interview).count() == 0


def test_interview_create_rejects_malformed_panel_member_id(
    tenant_a_db: Session,
    test_resume: Resume,
    test_position: Position,
):
    with pytest.raises(HTTPException) as exc_info:
        interview_service.create_interview(
            tenant_a_db,
            InterviewCreate(
                resume_id=test_resume.id,
                position_id=test_position.id,
                interview_time="2026-08-01T10:00:00+08:00",
                interview_location="上海办公室",
                meeting_link="https://meeting.example.com/interview",
                panel_members=["not-a-uuid"],
                skip_ai_questions=True,
                skip_email=True,
            ),
            BackgroundTasks(),
        )

    assert exc_info.value.status_code == 400
    assert tenant_a_db.query(Interview).count() == 0


def test_position_create_and_update_reject_cross_tenant_hiring_manager(
    tenant_a_db: Session,
    test_position: Position,
    tenant_b_user: User,
):
    before = tenant_a_db.query(Position).count()
    with pytest.raises(HTTPException) as create_exc:
        position_service.create_position(
            tenant_a_db,
            PositionCreate(
                title="Blocked position",
                description="Must not be created",
                hiring_manager_id=tenant_b_user.id,
            ),
        )

    with pytest.raises(HTTPException) as update_exc:
        position_service.update_position(
            tenant_a_db,
            test_position.id,
            PositionUpdate(hiring_manager_id=tenant_b_user.id),
        )

    assert create_exc.value.status_code == 404
    assert update_exc.value.status_code == 404
    assert tenant_a_db.query(Position).count() == before
    stored_position = tenant_a_db.query(Position).filter(Position.id == test_position.id).one()
    assert stored_position.hiring_manager_id is None


@pytest.mark.parametrize("foreign_reference", ["resume", "position"])
def test_offer_create_rejects_cross_tenant_resume_or_position(
    tenant_a_db: Session,
    test_resume: Resume,
    test_position: Position,
    tenant_b_resume: Resume,
    tenant_b_position: Position,
    test_user: User,
    special_resource_tables,
    foreign_reference: str,
):
    resume_id = tenant_b_resume.id if foreign_reference == "resume" else test_resume.id
    position_id = tenant_b_position.id if foreign_reference == "position" else test_position.id

    with pytest.raises(HTTPException) as exc_info:
        offer_service.create_offer(
            tenant_a_db,
            OfferCreate(
                resume_id=resume_id,
                position_id=position_id,
                candidate_name="Blocked candidate",
                candidate_email="blocked@example.com",
                position_title="Blocked position",
            ),
            test_user.id,
        )

    assert exc_info.value.status_code == 404
    assert tenant_a_db.query(Offer).count() == 0


def test_department_review_summary_rejects_cross_tenant_resume(
    tenant_a_db: Session,
    tenant_b_resume: Resume,
):
    with pytest.raises(HTTPException) as exc_info:
        resume_service.aggregate_department_reviews(tenant_a_db, tenant_b_resume.id)

    assert exc_info.value.status_code == 404


def test_department_review_completion_requires_matching_parent_resume(
    tenant_a_db: Session,
    db: Session,
    tenant_a: Tenant,
    test_position: Position,
    test_resume: Resume,
    test_user: User,
):
    other_resume = Resume(
        tenant_id=tenant_a.id,
        candidate_name="Other Tenant A candidate",
        position_id=test_position.id,
        status=ResumeStatus.PENDING_DEPT_REVIEW,
    )
    db.add(other_resume)
    db.commit()
    review = DepartmentReview(
        tenant_id=tenant_a.id,
        resume_id=other_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        resume_service.complete_department_review(
            tenant_a_db,
            test_resume.id,
            review.id,
            test_user.id,
            DepartmentReviewUpdate(overall_score=9),
        )

    assert exc_info.value.status_code == 404
    db.refresh(review)
    assert review.is_completed is False
    assert review.overall_score is None


def test_active_user_dependency_rejects_disabled_user(
    tenant_a_db: Session,
    db: Session,
    test_user: User,
):
    test_user.is_active = False
    db.commit()
    claims = AccessTokenClaims(
        user_id=test_user.id,
        tenant_id=test_user.tenant_id,
        role=test_user.role.value,
        credential_version=test_user.credential_version,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_dep(claims=claims, db=tenant_a_db)

    assert exc_info.value.status_code == 403


def test_active_user_dependency_rejects_deleted_user(
    tenant_a_db: Session,
    db: Session,
    test_user: User,
):
    claims = AccessTokenClaims(
        user_id=test_user.id,
        tenant_id=test_user.tenant_id,
        role=test_user.role.value,
        credential_version=test_user.credential_version,
    )
    db.delete(test_user)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_dep(claims=claims, db=tenant_a_db)

    assert exc_info.value.status_code == 401


def test_resume_delete_preserves_cross_tenant_children_with_same_parent_id(
    tenant_a_db: Session,
    db: Session,
    tenant_b: Tenant,
    tenant_b_user: User,
    test_resume: Resume,
    special_resource_tables,
):
    foreign_review = DepartmentReview(
        tenant_id=tenant_b.id,
        resume_id=test_resume.id,
        reviewer_id=tenant_b_user.id,
        is_completed=False,
    )
    db.add(foreign_review)
    db.commit()
    foreign_review_id = foreign_review.id

    deleted = resume_service.delete_resume(tenant_a_db, test_resume.id)

    assert deleted is not None
    db.expire_all()
    assert db.get(DepartmentReview, foreign_review_id) is not None


def test_resume_transfer_preserves_cross_tenant_reviews_with_same_parent_id(
    tenant_a_db: Session,
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
    tenant_b_user: User,
    test_resume: Resume,
):
    new_position = Position(
        tenant_id=tenant_a.id,
        title="Tenant A transfer target",
        description="Transfer target",
        status=PositionStatus.OPEN,
    )
    foreign_review = DepartmentReview(
        tenant_id=tenant_b.id,
        resume_id=test_resume.id,
        reviewer_id=tenant_b_user.id,
        is_completed=False,
    )
    db.add_all([new_position, foreign_review])
    db.commit()
    foreign_review_id = foreign_review.id

    transferred = resume_service.transfer_resume_position(
        tenant_a_db, test_resume.id, new_position.id, BackgroundTasks()
    )

    assert transferred.position_id == new_position.id
    db.expire_all()
    assert db.get(DepartmentReview, foreign_review_id) is not None


def test_synchronous_ai_uses_only_callers_tenant_config_and_prompt(
    db: Session,
    tenant_a_db: Session,
    tenant_b_db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    config_a = SystemConfig(
        tenant_id=tenant_a.id,
        llm_provider="openai_compatible",
        llm_base_url="https://tenant-a-ai.example/v1",
        llm_model="tenant-a-model",
        llm_api_key="tenant-a-key",
        prompt_configs={
            "generate_jd": {
                "system": "TENANT-A-SYSTEM",
                "user": "TENANT-A-USER {title}",
            }
        },
    )
    config_b = SystemConfig(
        tenant_id=tenant_b.id,
        llm_provider="openai_compatible",
        llm_base_url="https://tenant-b-ai.example/v1",
        llm_model="tenant-b-model",
        llm_api_key="tenant-b-key",
        prompt_configs={
            "generate_jd": {
                "system": "TENANT-B-SYSTEM",
                "user": "TENANT-B-USER {title}",
            }
        },
    )
    db.add_all([config_a, config_b])
    db.commit()

    calls: list[dict] = []

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.api_key = api_key
            self.base_url = base_url
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(
                {
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                    **kwargs,
                }
            )
            content = '{"description":"ok","requirements":"ok"}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    monkeypatch.setattr(ai_service, "OpenAI", FakeOpenAI)

    ai_service.generate_jd("A role", db=tenant_a_db)
    ai_service.generate_jd("B role", db=tenant_b_db)

    assert len(calls) == 2
    assert calls[0]["api_key"] == "tenant-a-key"
    assert calls[0]["base_url"] == "https://tenant-a-ai.example/v1"
    assert calls[0]["model"] == "tenant-a-model"
    assert calls[0]["messages"][0]["content"] == "TENANT-A-SYSTEM"
    assert calls[0]["messages"][1]["content"] == "TENANT-A-USER A role"
    assert "TENANT-B" not in str(calls[0])
    assert calls[1]["api_key"] == "tenant-b-key"
    assert calls[1]["base_url"] == "https://tenant-b-ai.example/v1"
    assert calls[1]["model"] == "tenant-b-model"
    assert calls[1]["messages"][0]["content"] == "TENANT-B-SYSTEM"
    assert calls[1]["messages"][1]["content"] == "TENANT-B-USER B role"
    assert "TENANT-A" not in str(calls[1])


def test_ai_config_without_db_uses_safe_defaults_without_database_read(
    monkeypatch: pytest.MonkeyPatch,
):
    database_reads: list[object] = []
    monkeypatch.setattr(
        ai_service,
        "get_system_config",
        lambda db: database_reads.append(db) or None,
    )

    config = ai_service._get_llm_config()

    assert database_reads == []
    assert config["llm_base_url"]
    assert config["llm_model"]


def test_concurrent_tenant_configs_never_return_another_tenants_client(
    monkeypatch: pytest.MonkeyPatch,
):
    config_a = {
        "llm_base_url": "https://tenant-a-ai.example/v1",
        "llm_api_key": "tenant-a-key",
    }
    config_b = {
        "llm_base_url": "https://tenant-b-ai.example/v1",
        "llm_api_key": "tenant-b-key",
    }
    first_b_started = Event()
    release_first_b = Event()
    construction_lock = Lock()
    b_constructions = 0

    class ControlledOpenAI:
        def __init__(self, api_key, base_url):
            nonlocal b_constructions
            if base_url == config_b["llm_base_url"]:
                with construction_lock:
                    b_constructions += 1
                    construction_number = b_constructions
                if construction_number == 1:
                    first_b_started.set()
                    assert release_first_b.wait(timeout=5)
            self.api_key = api_key
            self.base_url = base_url

    monkeypatch.setattr(ai_service, "OpenAI", ControlledOpenAI)

    client_a = ai_service._get_client(config=config_a)
    first_b_result = {}
    first_b_thread = Thread(
        target=lambda: first_b_result.setdefault(
            "client", ai_service._get_client(config=config_b)
        )
    )
    first_b_thread.start()
    assert first_b_started.wait(timeout=5)

    second_b_client = ai_service._get_client(config=config_b)
    release_first_b.set()
    first_b_thread.join(timeout=5)

    assert not first_b_thread.is_alive()
    assert client_a.base_url == config_a["llm_base_url"]
    assert client_a.api_key == config_a["llm_api_key"]
    assert second_b_client.base_url == config_b["llm_base_url"]
    assert second_b_client.api_key == config_b["llm_api_key"]
    assert first_b_result["client"].base_url == config_b["llm_base_url"]
    assert first_b_result["client"].api_key == config_b["llm_api_key"]


@pytest.mark.parametrize("stream_factory", ["generate_jd_stream", "chat_jd_stream"])
def test_jd_stream_factory_snapshots_tenant_ai_before_dependency_closes(
    stream_factory: str,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = []
    db = SimpleNamespace(closed=False)
    config = {
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://tenant-ai.example/v1",
        "llm_model": "tenant-model",
        "llm_temperature": 0.2,
        "llm_max_tokens": None,
        "llm_api_key": "tenant-key",
    }

    def assert_open(stage):
        assert db.closed is False, f"{stage} accessed the closed tenant session"
        calls.append(stage)

    def fake_get_prompt(*_args, db=None, **_kwargs):
        assert_open("prompt")
        return {"system": "tenant system", "user": "tenant user"}

    def fake_get_config(received_db=None):
        assert received_db is db
        assert_open("config")
        return config

    class FakeCompletions:
        def create(self, **_kwargs):
            calls.append("network")
            return [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]
                )
            ]

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    def fake_get_client(*, config=None, **_kwargs):
        assert config is not None
        assert_open("client")
        return fake_client

    monkeypatch.setattr(ai_service.prompt_manager, "get_prompt", fake_get_prompt)
    monkeypatch.setattr(ai_service, "_get_llm_config", fake_get_config)
    monkeypatch.setattr(ai_service, "_get_client", fake_get_client)

    if stream_factory == "generate_jd_stream":
        stream = ai_service.generate_jd_stream("Engineer", db=db)
        assert calls == ["prompt", "config", "client"]
    else:
        stream = ai_service.chat_jd_stream(
            [JDChatMessage(role="user", content="Improve it")], db=db
        )
        assert calls == ["config", "client"]

    db.closed = True
    events = list(stream)

    assert calls[-1] == "network"
    assert events[-1].startswith("data: ")
    assert '"done": true' in events[-1]


def test_create_department_review_rejects_cross_tenant_reviewer(
    tenant_a_db: Session,
    test_resume: Resume,
    tenant_b_user: User,
):
    with pytest.raises(HTTPException) as exc_info:
        resume_service.create_department_review(
            tenant_a_db, test_resume.id, tenant_b_user.id
        )

    assert exc_info.value.status_code == 404
    assert tenant_a_db.query(DepartmentReview).count() == 0


def test_hr_decision_uses_authenticated_user_instead_of_body_hr_id(
    tenant_a_db: Session,
    test_resume: Resume,
    test_user: User,
    tenant_b_user: User,
):
    scoped_resume = tenant_a_db.query(Resume).filter(Resume.id == test_resume.id).one()
    scoped_resume.status = ResumeStatus.PENDING_HR_DECISION
    tenant_a_db.commit()
    decision = HRDecisionCreate(
        hr_id=tenant_b_user.id,
        decision=ResumeStatus.REJECTED,
        reject_reason_category=RejectReasonCategory.OTHER,
        reject_reason_detail="Not selected",
    )

    result = resumes.submit_hr_decision_route(
        test_resume.id,
        decision,
        db=tenant_a_db,
        current_user=test_user,
    )

    assert result.rejected_by == test_user.id
    assert result.rejected_by != tenant_b_user.id


def test_hr_decision_body_hr_id_is_marked_deprecated():
    field = HRDecisionCreate.model_fields["hr_id"]

    assert field.deprecated is True
    assert "authenticated user" in (field.description or "").lower()


def test_workflow_review_tool_rejects_cross_tenant_reviewer(
    tenant_a_db: Session,
    test_resume: Resume,
    tenant_b_user: User,
):
    executor = NodeExecutor(tenant_a_db, None, {})

    with pytest.raises(HTTPException) as exc_info:
        executor._tool_create_department_review(
            {"resume_id": test_resume.id, "reviewer_id": tenant_b_user.id}, {}
        )

    assert exc_info.value.status_code == 404
    assert tenant_a_db.query(DepartmentReview).count() == 0


def test_duplicate_check_rejects_cross_tenant_position(
    tenant_a_db: Session,
    tenant_b_position: Position,
):
    with pytest.raises(HTTPException) as exc_info:
        resume_service.check_duplicate_resume(
            tenant_a_db,
            email="candidate@example.com",
            contact=None,
            position_id=tenant_b_position.id,
        )

    assert exc_info.value.status_code == 404


def test_interview_create_rejects_duplicate_panel_members(
    tenant_a_db: Session,
    test_resume: Resume,
    test_position: Position,
    test_user: User,
):
    with pytest.raises(HTTPException) as exc_info:
        interview_service.create_interview(
            tenant_a_db,
            InterviewCreate(
                resume_id=test_resume.id,
                position_id=test_position.id,
                interview_time="2026-08-01T10:00:00+08:00",
                interview_location="上海办公室",
                meeting_link="https://meeting.example.com/interview",
                panel_members=[str(test_user.id), str(test_user.id)],
                skip_ai_questions=True,
                skip_email=True,
            ),
            BackgroundTasks(),
        )

    assert exc_info.value.status_code == 400
    assert tenant_a_db.query(Interview).count() == 0


def test_prompt_manager_does_not_open_an_unscoped_session():
    prompt_manager_path = Path(__file__).parents[1] / "app" / "utils" / "prompt_manager.py"
    source = prompt_manager_path.read_text(encoding="utf-8")

    assert "SessionLocal" not in source


def test_ai_service_does_not_open_an_unscoped_session_and_threads_prompt_db():
    ai_service_path = Path(__file__).parents[1] / "app" / "services" / "ai_service.py"
    source = ai_service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "SessionLocal" not in source
    prompt_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get_prompt"
    ]
    assert len(prompt_calls) == 8
    for call in prompt_calls:
        db_keywords = [keyword for keyword in call.keywords if keyword.arg == "db"]
        assert len(db_keywords) == 1, f"line {call.lineno} must pass scoped db/default"


def test_sensitive_interview_endpoints_require_active_user_dependency():
    interviews_path = Path(__file__).parents[1] / "app" / "routes" / "interviews.py"
    tree = ast.parse(interviews_path.read_text(encoding="utf-8"))
    required_functions = {
        "confirm_interview_result_route",
        "export_interview_route",
        "update_questions_route",
        "get_interview_route",
        "update_interview_route",
    }
    found = set()

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in required_functions:
            continue
        found.add(node.name)
        dependencies = {
            call.args[0].id
            for call in ast.walk(node.args)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "Depends"
            and call.args
            and isinstance(call.args[0], ast.Name)
        }
        assert "get_current_user" in dependencies, node.name

    assert found == required_functions


def test_tenant_critical_services_do_not_use_query_bulk_writes():
    service_dir = Path(__file__).parents[1] / "app" / "services"
    filenames = {
        "ai_service.py",
        "coding_test_service.py",
        "interview_service.py",
        "offer_service.py",
        "offer_template_service.py",
        "position_service.py",
        "question_bank_service.py",
        "resume_service.py",
        "workflow_service.py",
    }

    for filename in filenames:
        tree = ast.parse((service_dir / filename).read_text(encoding="utf-8"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"update", "delete"}:
                continue
            uses_query = any(
                isinstance(candidate, ast.Call)
                and isinstance(candidate.func, ast.Attribute)
                and candidate.func.attr == "query"
                for candidate in ast.walk(call.func.value)
            )
            assert not uses_query, f"{filename}:{call.lineno} uses a query bulk write"


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


@pytest.mark.parametrize(
    ("endpoint", "form_data"),
    [
        ("audio/0", None),
        ("full-audio", None),
        (
            "direct-evaluation-with-audio",
            {"evaluation": "safe evaluation", "suggestion": "waitlist", "score": "5"},
        ),
    ],
)
def test_audio_transcription_exception_is_redacted_from_response_and_database(
    business_client,
    auth_headers,
    db,
    test_user,
    test_interview,
    monkeypatch,
    capsys,
    caplog,
    endpoint,
    form_data,
    tmp_path,
):
    from app.services import audio_service
    from app.routes import interviews as interview_routes

    secret = "Authorization: Bearer SECRET"

    class Sound:
        def set_frame_rate(self, _rate):
            return self

        def set_channels(self, _channels):
            return self

        def export(self, path, format):
            Path(path).write_bytes(b"wav")

    class BrokenRecognition:
        def __init__(self, **_kwargs):
            pass

        def call(self, _path):
            raise RuntimeError(secret)

    monkeypatch.setattr(audio_service.AudioSegment, "from_file", lambda _path: Sound())
    monkeypatch.setattr(audio_service, "Recognition", BrokenRecognition)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(
        interview_routes, "generate_evaluation_from_transcript", lambda *_args: None
    )
    monkeypatch.setattr(
        interview_routes, "generate_combined_evaluation", lambda *_args: None
    )
    if endpoint == "direct-evaluation-with-audio":
        test_interview.panel_members = [
            *(test_interview.panel_members or []),
            str(test_user.id),
        ]
        db.commit()

    with caplog.at_level("WARNING"):
        response = business_client.post(
            f"/api/interviews/{test_interview.id}/{endpoint}",
            headers=auth_headers,
            files={"file": ("interview.webm", b"audio", "audio/webm")},
            data=form_data or {},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Audio upload failed"
    db.expire_all()
    stored = db.get(Interview, test_interview.id)
    captured = capsys.readouterr()
    emitted = (
        response.text
        + str(stored.transcripts)
        + captured.out
        + captured.err
        + caplog.text
    )
    assert secret not in emitted
    assert stored.audio_records is None
    assert db.query(StoredFile).count() == 0
    assert not list(tmp_path.rglob("*.*"))
