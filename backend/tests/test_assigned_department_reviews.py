from fastapi import status
from fastapi.testclient import TestClient

from app.models.models import DepartmentReview


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
    assert response.json() == [
        {
            "review_id": str(assigned.id),
            "resume_id": str(test_resume.id),
            "candidate_name": test_resume.candidate_name,
            "position_title": test_resume.position.title,
            "match_score": test_resume.match_score,
            "status": test_resume.status.value,
            "created_at": assigned.created_at.isoformat(),
        }
    ]


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
