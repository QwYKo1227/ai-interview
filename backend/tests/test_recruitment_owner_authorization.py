from datetime import datetime, timezone
from uuid import uuid4

from fastapi import status
from sqlalchemy import event

from app.core.security import get_password_hash
from app.models.models import (
    DepartmentReview,
    Interview,
    InterviewStatus,
    Offer,
    OfferStatus,
    Position,
    PositionCategory,
    PositionStatus,
    Resume,
    ResumeStatus,
    User,
    UserRole,
)
from app.services.dashboard_service import get_overview
from app.services.resume_service import get_resumes
from app.models.workflow_models import WorkflowExecution
from app.services.workflow_access import can_access_execution


def _other_hr(db, tenant_id):
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"other-{uuid4()}@example.com",
        hashed_password=get_password_hash("testpassword"),
        full_name="Other recruiter",
        role=UserRole.HR,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _recruitment_chain(db, tenant_id, owner):
    position = Position(
        tenant_id=tenant_id,
        title="Private position",
        description="Private position description",
        status=PositionStatus.OPEN,
        hiring_manager_id=owner.id,
    )
    db.add(position)
    db.flush()
    resume = Resume(
        tenant_id=tenant_id,
        position_id=position.id,
        candidate_name="Private candidate",
        email="private@example.com",
        status=ResumeStatus.PENDING_INTERVIEW,
    )
    db.add(resume)
    db.flush()
    interview = Interview(
        tenant_id=tenant_id,
        resume_id=resume.id,
        position_id=position.id,
        interview_time=datetime.now(timezone.utc),
        status=InterviewStatus.SCHEDULED,
    )
    offer = Offer(
        tenant_id=tenant_id,
        resume_id=resume.id,
        position_id=position.id,
        candidate_name=resume.candidate_name,
        candidate_email=resume.email,
        position_title=position.title,
        status=OfferStatus.DRAFT,
        created_by=owner.id,
    )
    db.add_all([interview, offer])
    db.commit()
    return position, resume, interview, offer


def test_hr_cannot_list_or_address_another_recruiters_data(
    client, db, auth_headers, admin_auth_headers, test_user
):
    owner = _other_hr(db, test_user.tenant_id)
    position, resume, interview, offer = _recruitment_chain(db, test_user.tenant_id, owner)

    assert client.get("/api/positions", headers=auth_headers).json() == []
    assert client.get("/api/resumes", headers=auth_headers).json() == []
    assert client.get("/api/interviews", headers=auth_headers).json() == []
    assert client.get("/api/offers", headers=auth_headers).json()["items"] == []
    assert str(position.id) in {
        item["id"] for item in client.get("/api/positions", headers=admin_auth_headers).json()
    }
    assert client.get(
        f"/api/positions/{position.id}", headers=auth_headers
    ).status_code == status.HTTP_404_NOT_FOUND

    for path in (
        f"/api/resumes/{resume.id}",
        f"/api/interviews/{interview.id}",
        f"/api/offers/{offer.id}",
    ):
        assert client.get(path, headers=auth_headers).status_code == status.HTTP_404_NOT_FOUND
        assert client.get(path, headers=admin_auth_headers).status_code == status.HTTP_200_OK

    assert client.put(
        f"/api/resumes/{resume.id}",
        headers=auth_headers,
        json={"candidate_name": "Leaked update"},
    ).status_code == status.HTTP_404_NOT_FOUND
    assert client.put(
        f"/api/offers/{offer.id}",
        headers=auth_headers,
        json={"notes": "Leaked update"},
    ).status_code == status.HTTP_404_NOT_FOUND


def test_assigned_department_reviewer_can_read_only_the_assigned_resume(
    client, db, auth_headers, test_user
):
    owner = _other_hr(db, test_user.tenant_id)
    position, resume, _, _ = _recruitment_chain(db, test_user.tenant_id, owner)
    review = DepartmentReview(
        tenant_id=test_user.tenant_id,
        resume_id=resume.id,
        reviewer_id=test_user.id,
    )
    db.add(review)
    db.commit()

    response = client.get(f"/api/resumes/{resume.id}", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert client.get(f"/api/positions/{position.id}", headers=auth_headers).status_code == 404
    assert client.put(
        f"/api/resumes/{resume.id}",
        headers=auth_headers,
        json={"candidate_name": "Forbidden"},
    ).status_code == 404


def test_resume_list_uses_duplicate_free_access_filters_without_full_row_distinct(
    db, test_user
):
    _, owned_resume, _, _ = _recruitment_chain(db, test_user.tenant_id, test_user)
    other_owner = _other_hr(db, test_user.tenant_id)
    _, assigned_resume, _, _ = _recruitment_chain(db, test_user.tenant_id, other_owner)
    db.add(
        DepartmentReview(
            tenant_id=test_user.tenant_id,
            resume_id=assigned_resume.id,
            reviewer_id=test_user.id,
        )
    )
    db.commit()

    statements = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        resumes = get_resumes(db, current_user=test_user)
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert {resume.id for resume in resumes} == {owned_resume.id, assigned_resume.id}
    assert not any(
        "SELECT DISTINCT" in statement.upper() and "FROM RESUMES" in statement.upper()
        for statement in statements
    )


def test_hr_creation_forces_self_and_admin_must_choose_valid_owner(
    client, auth_headers, admin_auth_headers, test_user, test_interviewer
):
    payload = {"title": "Owned role", "description": "Description"}
    created = client.post("/api/positions", headers=auth_headers, json=payload)
    assert created.status_code == status.HTTP_200_OK
    assert created.json()["hiring_manager_id"] == str(test_user.id)

    missing = client.post("/api/positions", headers=admin_auth_headers, json=payload)
    assert missing.status_code == status.HTTP_400_BAD_REQUEST

    invalid = client.post(
        "/api/positions",
        headers=admin_auth_headers,
        json={**payload, "hiring_manager_id": str(test_interviewer.id)},
    )
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_reassignment_is_audited_and_revokes_old_owner(
    client, db, auth_headers, admin_auth_headers, test_position, test_user
):
    new_owner = _other_hr(db, test_user.tenant_id)
    changed = client.put(
        f"/api/positions/{test_position.id}?owner_change_reason=handoff",
        headers=admin_auth_headers,
        json={"hiring_manager_id": str(new_owner.id)},
    )
    assert changed.status_code == status.HTTP_200_OK

    db.refresh(test_position)
    assert test_position.hiring_manager_id == new_owner.id
    assert test_position.hiring_manager_history[-1]["old_owner_id"] == str(test_user.id)
    assert test_position.hiring_manager_history[-1]["new_owner_id"] == str(new_owner.id)
    assert test_position.hiring_manager_history[-1]["reason"] == "handoff"
    assert client.get(
        f"/api/positions/{test_position.id}", headers=auth_headers
    ).status_code == status.HTTP_404_NOT_FOUND


def test_hr_cannot_change_published_position_priority_or_category(
    client, db, auth_headers, test_position
):
    test_position.status = PositionStatus.PUBLISHED
    original_priority = test_position.priority
    original_category = test_position.category
    db.commit()

    blocked = client.put(
        f"/api/positions/{test_position.id}",
        headers=auth_headers,
        json={"priority": 5, "category": "overseas"},
    )

    assert blocked.status_code == status.HTTP_403_FORBIDDEN
    db.refresh(test_position)
    assert test_position.priority == original_priority
    assert test_position.category == original_category

    allowed = client.put(
        f"/api/positions/{test_position.id}",
        headers=auth_headers,
        json={
            "title": "已发布岗位的新名称",
            "priority": original_priority,
            "category": original_category.value,
        },
    )
    assert allowed.status_code == status.HTTP_200_OK
    assert allowed.json()["title"] == "已发布岗位的新名称"


def test_admin_can_change_published_position_priority_and_category(
    client, db, admin_auth_headers, test_position
):
    test_position.status = PositionStatus.PUBLISHED
    db.commit()

    response = client.put(
        f"/api/positions/{test_position.id}",
        headers=admin_auth_headers,
        json={"priority": 5, "category": "overseas"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["priority"] == 5
    assert response.json()["category"] == PositionCategory.OVERSEAS.value


def test_owner_of_open_position_must_handoff_before_deactivation(
    client, db, admin_auth_headers, test_position, test_user
):
    blocked = client.put(
        f"/api/auth/users/{test_user.id}/status", headers=admin_auth_headers
    )
    assert blocked.status_code == status.HTTP_409_CONFLICT

    test_position.status = PositionStatus.CLOSED
    db.commit()
    allowed = client.put(
        f"/api/auth/users/{test_user.id}/status", headers=admin_auth_headers
    )
    assert allowed.status_code == status.HTTP_200_OK
    assert allowed.json()["is_active"] is False


def test_hr_cannot_transfer_across_owner_and_active_process_blocks_transfer(
    client, db, auth_headers, test_user, test_position, test_resume
):
    other_owner = _other_hr(db, test_user.tenant_id)
    foreign_position = Position(
        tenant_id=test_user.tenant_id,
        title="Foreign target",
        description="Description",
        hiring_manager_id=other_owner.id,
    )
    own_target = Position(
        tenant_id=test_user.tenant_id,
        title="Own target",
        description="Description",
        hiring_manager_id=test_user.id,
    )
    db.add_all([foreign_position, own_target])
    db.commit()

    denied = client.post(
        f"/api/resumes/{test_resume.id}/transfer",
        headers=auth_headers,
        data={"new_position_id": str(foreign_position.id)},
    )
    assert denied.status_code == status.HTTP_404_NOT_FOUND

    active = Interview(
        tenant_id=test_user.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        interview_time=datetime.now(timezone.utc),
        status=InterviewStatus.SCHEDULED,
    )
    db.add(active)
    db.commit()
    blocked = client.post(
        f"/api/resumes/{test_resume.id}/transfer",
        headers=auth_headers,
        data={"new_position_id": str(own_target.id)},
    )
    assert blocked.status_code == status.HTTP_409_CONFLICT


def test_dashboard_aggregates_are_scoped_to_recruitment_owner(db, test_user, test_admin):
    _recruitment_chain(db, test_user.tenant_id, test_user)
    other_owner = _other_hr(db, test_user.tenant_id)
    _recruitment_chain(db, test_user.tenant_id, other_owner)

    hr_overview = get_overview(db, test_user)
    admin_overview = get_overview(db, test_admin)

    assert hr_overview["metrics"]["total_positions"] == 1
    assert hr_overview["metrics"]["total_resumes"] == 1
    assert hr_overview["metrics"]["total_interviews"] == 1
    assert admin_overview["metrics"]["total_positions"] == 2
    assert admin_overview["metrics"]["total_resumes"] == 2
    assert admin_overview["metrics"]["total_interviews"] == 2


def test_workflow_execution_checks_every_linked_resource(db, test_user):
    own_position, own_resume, _, _ = _recruitment_chain(
        db, test_user.tenant_id, test_user
    )
    other_owner = _other_hr(db, test_user.tenant_id)
    foreign_position, foreign_resume, _, _ = _recruitment_chain(
        db, test_user.tenant_id, other_owner
    )
    db.add(
        DepartmentReview(
            tenant_id=test_user.tenant_id,
            resume_id=foreign_resume.id,
            reviewer_id=test_user.id,
        )
    )
    db.commit()
    valid = WorkflowExecution(
        tenant_id=test_user.tenant_id,
        workflow_id=uuid4(),
        triggered_by=test_user.id,
        input_data={
            "resume_id": str(own_resume.id),
            "position_id": str(own_position.id),
        },
    )
    mixed = WorkflowExecution(
        tenant_id=test_user.tenant_id,
        workflow_id=valid.workflow_id,
        triggered_by=test_user.id,
        input_data={
            "resume_id": str(own_resume.id),
            "position_id": str(foreign_position.id),
        },
    )
    review_only = WorkflowExecution(
        tenant_id=test_user.tenant_id,
        workflow_id=valid.workflow_id,
        triggered_by=test_user.id,
        input_data={"resume_id": str(foreign_resume.id)},
    )
    assert can_access_execution(db, valid, test_user) is True
    assert can_access_execution(db, mixed, test_user) is False
    assert can_access_execution(db, review_only, test_user) is False
