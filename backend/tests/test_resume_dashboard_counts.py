"""Compare the actual resume-list and dashboard APIs for the same account."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import DepartmentReview, Position, Resume, ResumeStatus
from app.routes import dashboard


@pytest.fixture
def dashboard_client(client):
    client.app.include_router(dashboard.router, prefix="/api")
    return client


def assert_matching_totals(client, headers, expected):
    responses = {
        name: client.get(path, headers=headers)
        for name, path in {
            "resumes": "/api/resumes",
            "funnel": "/api/dashboard/funnel",
            "overview": "/api/dashboard/overview",
            "timeline": "/api/dashboard/timeline?days=7",
        }.items()
    }
    assert all(response.status_code == 200 for response in responses.values())
    resumes = responses["resumes"].json()
    assert len(resumes) == expected
    assert responses["funnel"].json()["total_resumes"] == len(resumes)
    assert responses["overview"].json()["metrics"]["total_resumes"] == len(resumes)
    assert responses["timeline"].json()["summary"]["total_resumes_received"] == len(resumes)
    return resumes


def test_admin_dashboard_and_resume_list_include_more_than_100_records(
    dashboard_client, admin_auth_headers, db, test_position,
):
    db.add_all([
        Resume(
            id=uuid4(), tenant_id=test_position.tenant_id,
            position_id=test_position.id, candidate_name=f"Candidate {index}",
            status=ResumeStatus.PENDING_SCREENING,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        for index in range(105)
    ])
    db.commit()
    assert_matching_totals(dashboard_client, admin_auth_headers, 105)
    limited = dashboard_client.get("/api/resumes?skip=5&limit=10", headers=admin_auth_headers)
    assert limited.status_code == 200
    assert len(limited.json()) == 10
    assert dashboard_client.get("/api/resumes?limit=0", headers=admin_auth_headers).status_code == 422


@pytest.mark.parametrize("review_completed", [False, True])
def test_hr_counts_include_review_assignments_without_duplicates_or_unassigned_resumes(
    dashboard_client, auth_headers, db, test_user, test_position,
    test_resume, test_interviewer, review_completed,
):
    other_position = Position(
        id=uuid4(), tenant_id=test_user.tenant_id, title="Other recruiter's position",
        description="Position owned by another recruiter",
    )
    db.add(other_position)
    db.flush()
    assigned = Resume(
        id=uuid4(), tenant_id=test_user.tenant_id, position_id=other_position.id,
        candidate_name="Assigned for review", status=ResumeStatus.PENDING_REVIEW,
    )
    unassigned = Resume(
        id=uuid4(), tenant_id=test_user.tenant_id, position_id=other_position.id,
        candidate_name="Other reviewer only", status=ResumeStatus.PENDING_REVIEW,
    )
    db.add_all([assigned, unassigned])
    db.flush()
    db.add_all([
        DepartmentReview(
            tenant_id=test_user.tenant_id, resume_id=assigned.id,
            reviewer_id=test_user.id, is_completed=review_completed,
        ),
        # Ownership and review assignment overlap; count the resume once.
        DepartmentReview(
            tenant_id=test_user.tenant_id, resume_id=test_resume.id,
            reviewer_id=test_user.id, is_completed=False,
        ),
        DepartmentReview(
            tenant_id=test_user.tenant_id, resume_id=assigned.id,
            reviewer_id=test_interviewer.id, is_completed=False,
        ),
        DepartmentReview(
            tenant_id=test_user.tenant_id, resume_id=unassigned.id,
            reviewer_id=test_interviewer.id, is_completed=False,
        ),
    ])
    db.commit()
    resumes = assert_matching_totals(dashboard_client, auth_headers, 2)
    assert {row["id"] for row in resumes} == {str(test_resume.id), str(assigned.id)}


def test_admin_totals_remain_scoped_to_the_current_company(
    dashboard_client, admin_auth_headers, db, test_position, test_resume, tenant_b,
):
    other_position = Position(
        id=uuid4(), tenant_id=tenant_b.id, title="Other company", description="Other tenant",
    )
    db.add(other_position)
    db.flush()
    db.add(Resume(
        id=uuid4(), tenant_id=tenant_b.id, position_id=other_position.id,
        candidate_name="Other company candidate", status=ResumeStatus.PENDING_SCREENING,
    ))
    db.commit()
    resumes = assert_matching_totals(dashboard_client, admin_auth_headers, 1)
    assert resumes[0]["id"] == str(test_resume.id)
