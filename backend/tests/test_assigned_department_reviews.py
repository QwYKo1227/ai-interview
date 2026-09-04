from datetime import datetime, timedelta

from fastapi import BackgroundTasks, status
from fastapi.testclient import TestClient

from app.models.models import (
    DepartmentReview,
    Position,
    PositionStatus,
    RejectReasonCategory,
    Resume,
    ResumeStatus,
    ReviewRecommendation,
)
from app.services.resume_service import transfer_resume_position
from app.services.resume_service import create_department_review


def test_my_reviews_returns_only_current_users_pending_assignments(
    client: TestClient,
    db,
    test_resume,
    test_interviewer,
    test_user,
    interviewer_auth_headers: dict,
):
    assigned = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=False,
    )
    completed = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=True,
        overall_score=8,
        recommendation=ReviewRecommendation.RECOMMEND,
        completed_at=datetime.utcnow(),
    )
    someone_elses = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add_all([assigned, completed, someone_elses])
    db.commit()

    response = client.get(
        "/api/resumes/my-reviews",
        headers=interviewer_auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["total"] == 1
    assert payload["pending_total"] == 1
    assert payload["completed_total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["items"] == [{
            "review_id": str(assigned.id),
            "resume_id": str(test_resume.id),
            "candidate_name": test_resume.candidate_name,
            "position_title": test_resume.position.title,
            "match_score": test_resume.match_score,
            "status": test_resume.status.value,
            "is_completed": False,
            "overall_score": None,
            "recommendation": None,
            "created_at": assigned.created_at.isoformat(),
            "completed_at": None,
        }]

    completed_response = client.get(
        "/api/resumes/my-reviews?completed=true&search=高级Python",
        headers=interviewer_auth_headers,
    )
    assert completed_response.status_code == status.HTTP_200_OK
    assert completed_response.json()["items"] == [{
        "review_id": str(completed.id),
        "resume_id": str(test_resume.id),
        "candidate_name": test_resume.candidate_name,
        "position_title": test_resume.position.title,
        "match_score": test_resume.match_score,
        "status": test_resume.status.value,
        "is_completed": True,
        "overall_score": 8,
        "recommendation": "recommend",
        "created_at": completed.created_at.isoformat(),
        "completed_at": completed.completed_at.isoformat(),
    }]


def test_pending_review_count_is_scoped_to_the_current_reviewer(
    client: TestClient,
    db,
    test_resume,
    test_admin,
    test_interviewer,
    admin_auth_headers: dict,
):
    db.add_all([
        DepartmentReview(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            reviewer_id=test_admin.id,
            is_completed=False,
        ),
        DepartmentReview(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            reviewer_id=test_interviewer.id,
            is_completed=False,
        ),
    ])
    db.commit()

    response = client.get(
        "/api/resumes/my-pending-review-count",
        headers=admin_auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"count": 1}


def test_pending_hr_decision_count_only_includes_exact_status(
    client: TestClient,
    db,
    test_resume,
    test_position,
    auth_headers: dict,
):
    test_resume.status = ResumeStatus.PENDING_HR_DECISION
    db.add(Resume(
        tenant_id=test_resume.tenant_id,
        candidate_name="仍在部门评审",
        position_id=test_position.id,
        status=ResumeStatus.PENDING_DEPT_REVIEW,
    ))
    db.commit()

    response = client.get(
        "/api/resumes/pending-hr-decision-count",
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"count": 1}


def test_interviewer_resume_detail_exposes_only_own_review_and_coarse_status(
    client: TestClient,
    db,
    test_resume,
    test_interviewer,
    test_user,
    interviewer_auth_headers: dict,
):
    own_review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=True,
        overall_score=9,
        comment="我的评语",
    )
    other_review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=True,
        overall_score=2,
        comment="不应泄露的评语",
    )
    test_resume.hr_review = "不应泄露的 HR 评语"
    test_resume.reject_reason_category = RejectReasonCategory.OTHER
    test_resume.reject_reason_detail = "不应泄露的淘汰原因"
    db.add_all([own_review, other_review, test_resume])
    db.commit()

    response = client.get(
        f"/api/resumes/{test_resume.id}",
        headers=interviewer_auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["status"] == test_resume.status.value
    assert payload["hr_review"] is None
    assert payload["reject_reason_category"] is None
    assert payload["reject_reason_detail"] is None
    assert [item["id"] for item in payload["department_reviews"]] == [str(own_review.id)]
    assert payload["department_reviews"][0]["comment"] == "我的评语"

    other_review_response = client.get(
        f"/api/resumes/{test_resume.id}?review_id={other_review.id}",
        headers=interviewer_auth_headers,
    )
    assert other_review_response.status_code == status.HTTP_404_NOT_FOUND

    summary_response = client.get(
        f"/api/resumes/{test_resume.id}/department-reviews",
        headers=interviewer_auth_headers,
    )
    assert summary_response.status_code == status.HTTP_404_NOT_FOUND


def test_admin_personal_review_entry_returns_only_the_selected_own_review(
    client: TestClient,
    db,
    test_resume,
    test_admin,
    test_interviewer,
    admin_auth_headers: dict,
):
    selected = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_admin.id,
        is_completed=False,
    )
    other = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=False,
    )
    db.add_all([selected, other])
    db.commit()

    response = client.get(
        f"/api/resumes/{test_resume.id}?review_id={selected.id}",
        headers=admin_auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert [review["id"] for review in response.json()["department_reviews"]] == [
        str(selected.id),
    ]

    forbidden = client.get(
        f"/api/resumes/{test_resume.id}?review_id={other.id}",
        headers=admin_auth_headers,
    )
    assert forbidden.status_code == status.HTTP_404_NOT_FOUND


def test_transfer_preserves_completed_review_and_original_position_snapshot(
    db,
    test_resume,
    test_interviewer,
):
    original_position = test_resume.position
    completed = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=True,
        completed_at=datetime.utcnow() - timedelta(days=1),
    )
    pending = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_interviewer.id,
        is_completed=False,
    )
    new_position = Position(
        tenant_id=test_resume.tenant_id,
        title="数据平台工程师",
        description="建设数据平台",
        status=PositionStatus.OPEN,
    )
    db.add_all([completed, pending, new_position])
    db.commit()
    completed_id = completed.id
    pending_id = pending.id

    transfer_resume_position(
        db,
        test_resume.id,
        new_position.id,
        BackgroundTasks(),
    )

    db.expire_all()
    preserved = db.get(DepartmentReview, completed_id)
    assert preserved is not None
    assert preserved.reviewed_position_id == original_position.id
    assert preserved.reviewed_position_title == original_position.title
    assert db.get(DepartmentReview, pending_id) is None

    reassigned = create_department_review(db, test_resume.id, test_interviewer.id)
    assert reassigned.reviewed_position_id == new_position.id
    assert reassigned.reviewed_position_title == new_position.title


def test_department_review_submission_uses_authenticated_reviewer(
    client: TestClient,
    db,
    test_resume,
    test_user,
    test_interviewer,
    interviewer_auth_headers: dict,
):
    review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()

    response = client.put(
        f"/api/resumes/{test_resume.id}/department-reviews/{review.id}",
        data={
            "reviewer_id": str(test_user.id),
            "overall_score": "9",
            "recommendation": "recommend",
        },
        headers=interviewer_auth_headers,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    db.refresh(review)
    assert review.is_completed is False
    assert review.overall_score is None
