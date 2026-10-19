from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles

from app.config.database import get_unscoped_db
from app.config.tenant_session import TenantCapableSession, TenantSession
from app.models.models import CodingSubmission, CodingTest, Position, PositionStatus, QuestionBank, Resume, ResumeStatus
from app.models.workflow_models import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.routes import positions, question_banks, workflows
from app.services.workflow_service import NodeExecutor, WorkflowEngine


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def list_client(client, db):
    tables = [QuestionBank.__table__, Workflow.__table__, WorkflowExecution.__table__, WorkflowNodeExecution.__table__]
    for table in tables:
        table.create(bind=db.get_bind(), checkfirst=True)
    client.app.include_router(question_banks.router, prefix="/api")
    client.app.include_router(workflows.router, prefix="/api")
    client.app.include_router(positions.public_router, prefix="/api")
    def unscoped_db():
        with TenantCapableSession(bind=db.get_bind()) as session:
            yield session
    client.app.dependency_overrides[get_unscoped_db] = unscoped_db
    try:
        yield client
    finally:
        for table in reversed(tables):
            table.drop(bind=db.get_bind(), checkfirst=True)


@pytest.mark.parametrize("resource", ["question-banks", "workflows"])
def test_lists_return_every_visible_record_and_honor_explicit_pagination(
    list_client, db, auth_headers, test_user, tenant_b, resource
):
    model = QuestionBank if resource == "question-banks" else Workflow
    records = [model(id=uuid4(), tenant_id=test_user.tenant_id, name=f"Record {index}") for index in range(105)]
    db.add_all(records + [model(tenant_id=tenant_b.id, name="Other tenant record")])
    db.commit()

    response = list_client.get(f"/api/{resource}", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {str(record.id) for record in records}

    page = list_client.get(f"/api/{resource}", params={"skip": 100, "limit": 10}, headers=auth_headers)
    assert page.status_code == 200
    assert page.json() == payload[100:110]
    remaining = list_client.get(f"/api/{resource}", params={"skip": 100}, headers=auth_headers)
    assert remaining.status_code == 200
    assert remaining.json() == payload[100:]


def test_workflow_executions_scan_all_batches_before_applying_visible_pagination(
    list_client, db, auth_headers, admin_auth_headers, test_user, test_interviewer
):
    workflow = Workflow(tenant_id=test_user.tenant_id, name="Workflow")
    db.add(workflow)
    db.flush()
    start = datetime(2026, 1, 1)
    visible = [WorkflowExecution(id=uuid4(), tenant_id=test_user.tenant_id, workflow_id=workflow.id,
        triggered_by=test_user.id, created_at=start + timedelta(minutes=index)) for index in range(105)]
    hidden = [WorkflowExecution(id=uuid4(), tenant_id=test_user.tenant_id, workflow_id=workflow.id,
        triggered_by=test_interviewer.id, created_at=start + timedelta(days=1, minutes=index)) for index in range(211)]
    db.add_all(visible + hidden)
    db.commit()
    path = f"/api/workflows/{workflow.id}/executions"
    expected = [str(item.id) for item in reversed(visible)]

    response = list_client.get(path, headers=auth_headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == expected
    page = list_client.get(path, params={"skip": 100, "limit": 10}, headers=auth_headers)
    assert page.status_code == 200
    assert [item["id"] for item in page.json()] == expected[100:110]
    remaining = list_client.get(path, params={"skip": 100}, headers=auth_headers)
    assert remaining.status_code == 200
    assert [item["id"] for item in remaining.json()] == expected[100:]
    admin_response = list_client.get(path, headers=admin_auth_headers)
    assert admin_response.status_code == 200
    assert len(admin_response.json()) == 316
    assert len(WorkflowEngine(db).get_executions(workflow_id=workflow.id)) == 316


@pytest.mark.parametrize("path", ["/api/positions/public?tenant_code=careray", "/api/public/careray/positions"])
def test_public_positions_are_not_truncated_and_remain_tenant_scoped(
    list_client, db, test_user, tenant_b, path
):
    records = [Position(id=uuid4(), tenant_id=test_user.tenant_id, title=f"Published {index}",
        description="Description", status=PositionStatus.PUBLISHED) for index in range(105)]
    db.add_all(records + [Position(tenant_id=tenant_b.id, title="Other tenant", description="Description", status=PositionStatus.PUBLISHED),
        Position(tenant_id=test_user.tenant_id, title="Unpublished", description="Description", status=PositionStatus.OPEN)])
    db.commit()
    response = list_client.get(path)
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {str(record.id) for record in records}
    separator = "&" if "?" in path else "?"
    page = list_client.get(f"{path}{separator}skip=100&limit=10")
    assert page.status_code == 200
    assert len(page.json()) == 5


def test_workflow_resume_query_does_not_implicitly_truncate_matching_candidates(db, test_position):
    records = [Resume(id=uuid4(), tenant_id=test_position.tenant_id, position_id=test_position.id,
        candidate_name=f"Candidate {index}", status=ResumeStatus.PENDING_REVIEW, match_score=80) for index in range(105)]
    db.add_all(records + [Resume(tenant_id=test_position.tenant_id, position_id=test_position.id,
        candidate_name="Below threshold", status=ResumeStatus.PENDING_REVIEW, match_score=20)])
    db.commit()
    config = {"status": "pending_review", "position_id": test_position.id, "min_match_score": 60}

    with TenantSession(tenant_id=test_position.tenant_id, bind=db.get_bind()) as scoped_db:
        executor = NodeExecutor(scoped_db, execution=None, variables={})
        result = executor.execute("tool", {"tool_name": "query_resumes", "config": config}, {})["output"]
        assert result["count"] == 105
        assert {item["id"] for item in result["resumes"]} == {str(record.id) for record in records}
        limited = executor.execute("tool", {"tool_name": "query_resumes", "config": {**config, "limit": 10}}, {})["output"]
        assert limited["count"] == 10


@pytest.mark.parametrize("limit", [0, -1])
@pytest.mark.parametrize("resource", [
    "positions", "resumes", "interviews", "auth/users", "question-banks", "workflows", "coding-tests",
    f"workflows/{uuid4()}/executions", f"coding-tests/{uuid4()}/submissions",
])
def test_list_routes_reject_nonpositive_explicit_limits(list_client, admin_auth_headers, resource, limit):
    response = list_client.get(f"/api/{resource}", params={"limit": limit}, headers=admin_auth_headers)
    assert response.status_code == 422


def test_coding_lists_have_no_implicit_limit_but_honor_explicit_limit(
    client,
    auth_headers,
    db,
    test_user,
    test_position,
):
    coding_tests = [
        CodingTest(
            id=uuid4(),
            tenant_id=test_user.tenant_id,
            title=f"Coding test {index}",
            public_token=f"coding-list-token-{index}-{uuid4()}",
            created_by=test_user.id,
            position_id=test_position.id,
        )
        for index in range(105)
    ]
    db.add_all(coding_tests)
    db.commit()

    full_tests = client.get("/api/coding-tests", headers=auth_headers)
    limited_tests = client.get(
        "/api/coding-tests", params={"limit": 10}, headers=auth_headers
    )

    assert full_tests.status_code == 200
    assert len(full_tests.json()) == 105
    assert limited_tests.status_code == 200
    assert len(limited_tests.json()) == 10

    submissions = [
        CodingSubmission(
            id=uuid4(),
            tenant_id=test_user.tenant_id,
            coding_test_id=coding_tests[0].id,
            candidate_name=f"Candidate {index}",
        )
        for index in range(105)
    ]
    db.add_all(submissions)
    db.commit()

    full_submissions = client.get(
        f"/api/coding-tests/{coding_tests[0].id}/submissions",
        headers=auth_headers,
    )
    limited_submissions = client.get(
        f"/api/coding-tests/{coding_tests[0].id}/submissions",
        params={"limit": 10},
        headers=auth_headers,
    )

    assert full_submissions.status_code == 200
    assert len(full_submissions.json()) == 105
    assert limited_submissions.status_code == 200
    assert len(limited_submissions.json()) == 10
