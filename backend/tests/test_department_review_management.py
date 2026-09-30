from fastapi import HTTPException
from datetime import datetime
import pytest

from app.models.models import DepartmentReview, Resume, ResumeStatus, User, UserRole
from app.models.tenant_models import PublicAccessToken
from app.services.public_token_service import hash_token, resolve_public_token, revoke_public_tokens
from app.core.security import create_access_token
from app.services.resume_service import (
    complete_department_review,
    delete_department_reviewer,
    get_assigned_department_reviews,
    reassign_department_reviewer,
    reissue_department_review_link,
)
from app.schemas.resume import DepartmentReviewUpdate


def test_reassigns_pending_department_reviewer_and_rotates_link(
    db, test_resume, test_user, test_interviewer
):
    review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
        last_reminded_at=datetime.utcnow(),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    previous_token = reissue_department_review_link(db, test_resume.id, review.id)

    updated = reassign_department_reviewer(
        db, test_resume.id, review.id, test_interviewer.id
    )

    assert updated.reviewer_id == test_interviewer.id
    assert updated.public_token
    assert updated.public_token != previous_token
    assert updated.last_reminded_at is None
    token_record = db.query(PublicAccessToken).filter(
        PublicAccessToken.token_hash == hash_token(updated.public_token)
    ).one()
    assert token_record.resource_id == review.id


def test_completed_department_review_cannot_be_reassigned(
    db, test_resume, test_user, test_interviewer
):
    review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=True,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    with pytest.raises(HTTPException, match="已完成的评审不可修改评审人"):
        reassign_department_reviewer(
            db, test_resume.id, review.id, test_interviewer.id
        )


def test_reissues_department_review_link(db, test_resume, test_user):
    review = DepartmentReview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    token = reissue_department_review_link(db, test_resume.id, review.id)

    token_record = db.query(PublicAccessToken).filter(
        PublicAccessToken.token_hash == hash_token(token)
    ).one()
    assert token_record.resource_id == review.id

    repeated_token = reissue_department_review_link(db, test_resume.id, review.id)
    assert repeated_token == token


def _pending_review(db, resume, reviewer):
    resume.status = ResumeStatus.PENDING_DEPT_REVIEW
    review = DepartmentReview(
        tenant_id=resume.tenant_id,
        resume_id=resume.id,
        reviewer_id=reviewer.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@pytest.mark.parametrize("remaining_completed, expected_status", [
    (None, ResumeStatus.PENDING_REVIEW),
    (False, ResumeStatus.PENDING_DEPT_REVIEW),
    (True, ResumeStatus.PENDING_HR_DECISION),
])
def test_delete_reviewer_reconciles_status_and_revokes_access(
    db, test_resume, test_user, test_interviewer, monkeypatch,
    remaining_completed, expected_status,
):
    review = _pending_review(db, test_resume, test_interviewer)
    review_id = review.id
    token = reissue_department_review_link(db, test_resume.id, review_id)
    remaining = None
    if remaining_completed is not None:
        remaining = DepartmentReview(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            reviewer_id=test_user.id,
            is_completed=remaining_completed,
            overall_score=8 if remaining_completed else None,
            comment="保留的评审结果" if remaining_completed else None,
        )
        db.add(remaining)
        db.commit()
    notifications = []
    monkeypatch.setattr(
        "app.services.resume_service._send_hr_review_notification",
        lambda *args: notifications.append(args),
    )

    result = delete_department_reviewer(db, test_resume.id, review_id)

    db.refresh(test_resume)
    assert result["status"] == expected_status.value
    assert test_resume.status == expected_status
    assert db.query(DepartmentReview).filter_by(id=review_id).first() is None
    token_record = db.query(PublicAccessToken).filter_by(token_hash=hash_token(token)).one()
    assert token_record.revoked_at is not None
    with pytest.raises(HTTPException) as invalid_link:
        resolve_public_token(db, token, "department_review")
    assert invalid_link.value.status_code == 404
    with pytest.raises(HTTPException) as removed_reviewer:
        complete_department_review(
            db, test_resume.id, review_id, test_interviewer.id,
            DepartmentReviewUpdate(overall_score=9),
        )
    assert removed_reviewer.value.status_code == 404
    assigned = get_assigned_department_reviews(db, test_interviewer.id)
    assert assigned["total"] == 0
    assert len(notifications) == (1 if remaining_completed is True else 0)
    if remaining is not None:
        db.refresh(remaining)
        assert remaining.is_completed == remaining_completed
        if remaining_completed:
            assert remaining.overall_score == 8
            assert remaining.comment == "保留的评审结果"


def test_cannot_delete_completed_review(db, test_resume, test_interviewer):
    review = _pending_review(db, test_resume, test_interviewer)
    review.is_completed = True
    db.commit()

    with pytest.raises(HTTPException) as error:
        delete_department_reviewer(db, test_resume.id, review.id)

    assert error.value.status_code == 400
    assert db.query(DepartmentReview).filter_by(id=review.id).one().is_completed
    assert test_resume.status == ResumeStatus.PENDING_DEPT_REVIEW


def test_cannot_delete_review_after_hr_decision(db, test_resume, test_interviewer):
    review = _pending_review(db, test_resume, test_interviewer)
    test_resume.status = ResumeStatus.PENDING_INTERVIEW
    db.commit()

    with pytest.raises(HTTPException) as error:
        delete_department_reviewer(db, test_resume.id, review.id)

    assert error.value.status_code == 400
    assert db.query(DepartmentReview).filter_by(id=review.id).one()
    assert test_resume.status == ResumeStatus.PENDING_INTERVIEW


def test_delete_failure_rolls_back_assignment_and_status(
    db, test_resume, test_interviewer, monkeypatch,
):
    review = _pending_review(db, test_resume, test_interviewer)
    review_id = review.id
    token = reissue_department_review_link(db, test_resume.id, review_id)

    def fail_revocation(*args):
        revoke_public_tokens(*args)
        raise RuntimeError("revocation failed")

    monkeypatch.setattr("app.services.resume_service.revoke_public_tokens", fail_revocation)
    with pytest.raises(RuntimeError, match="revocation failed"):
        delete_department_reviewer(db, test_resume.id, review_id)

    assert db.query(DepartmentReview).filter_by(id=review_id).one()
    db.refresh(test_resume)
    assert test_resume.status == ResumeStatus.PENDING_DEPT_REVIEW
    db.expunge_all()
    assert resolve_public_token(db, token, "department_review").resource_id == review_id


@pytest.mark.parametrize("actor, expected_code", [
    ("hr", 200), ("admin", 200), ("interviewer", 403),
    ("unrelated_hr", 404), ("foreign_admin", 404),
])
def test_delete_reviewer_route_requires_resume_management_access(
    client, db, test_resume, test_interviewer, test_user, test_admin,
    tenant_b, actor, expected_code,
):
    review = _pending_review(db, test_resume, test_interviewer)
    review_id = review.id
    if actor == "foreign_admin":
        user = User(
            tenant_id=tenant_b.id, email="other-admin@example.com",
            hashed_password=test_admin.hashed_password, role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif actor == "admin":
        user = test_admin
    elif actor == "interviewer":
        user = test_interviewer
    else:
        user = test_user
        if actor == "unrelated_hr":
            test_resume.position.hiring_manager_id = test_admin.id
            db.commit()
    access_token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role.value,
        credential_version=user.credential_version,
    )

    response = client.delete(
        f"/api/resumes/{test_resume.id}/department-reviews/{review_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == expected_code
    if expected_code == 200:
        assert response.json()["status"] == "pending_review"
        assert db.query(DepartmentReview).filter_by(id=review_id).first() is None
    elif actor != "foreign_admin":
        assert db.query(DepartmentReview).filter_by(id=review_id).one()


def test_cannot_delete_a_review_belonging_to_another_resume(
    client, db, test_resume, test_interviewer, auth_headers,
):
    review = _pending_review(db, test_resume, test_interviewer)
    other_resume = Resume(
        tenant_id=test_resume.tenant_id, position_id=test_resume.position_id,
        candidate_name="其他候选人", file_path="/uploads/other.pdf",
        status=ResumeStatus.PENDING_DEPT_REVIEW,
    )
    db.add(other_resume)
    db.commit()

    response = client.delete(
        f"/api/resumes/{other_resume.id}/department-reviews/{review.id}",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert db.query(DepartmentReview).filter_by(id=review.id).one()
    assert test_resume.status == ResumeStatus.PENDING_DEPT_REVIEW
    assert other_resume.status == ResumeStatus.PENDING_DEPT_REVIEW
