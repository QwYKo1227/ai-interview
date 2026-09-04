from fastapi import HTTPException
from datetime import datetime
import pytest

from app.models.models import DepartmentReview
from app.models.tenant_models import PublicAccessToken
from app.services.public_token_service import hash_token
from app.services.resume_service import (
    reassign_department_reviewer,
    reissue_department_review_link,
)


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
