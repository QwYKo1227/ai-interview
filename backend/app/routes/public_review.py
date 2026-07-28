from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.models.models import DepartmentReview, User
from app.routes.auth import get_current_user
from app.routes.files import _response as stored_file_response
from app.services.public_token_service import enforce_public_request_tenant, resolve_public_token
from app.services.resume_service import (
    get_public_review_file,
    get_public_review_payload,
    submit_public_department_review,
)
from app.schemas.resume import PublicDepartmentReviewSubmit
from app.core.proxy import resolve_request_host


router = APIRouter(prefix="/public/review", tags=["public-review"])


def _resolve_review(
    db: Session,
    token: str,
    request: Request,
    current_user: User,
) -> DepartmentReview:
    resolved = resolve_public_token(db, token, "department_review")
    enforce_public_request_tenant(
        db, request_host=resolve_request_host(request), tenant_id=resolved.tenant_id
    )
    review = resolved.resource
    if review.reviewer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该评审链接不属于当前登录账号",
        )
    return review


@router.get("/{token}/resume-file")
def get_resume_file_for_review(
    token: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request, current_user)
    record = get_public_review_file(db, review)
    return stored_file_response(record)


@router.get("/{token}")
def get_resume_for_review(
    token: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request, current_user)
    return get_public_review_payload(db, review)


@router.post("/{token}/submit")
def submit_review(
    token: str,
    request: Request,
    payload: PublicDepartmentReviewSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request, current_user)
    return submit_public_department_review(
        db,
        review,
        technical_score=payload.technical_score,
        experience_score=payload.experience_score,
        overall_score=payload.overall_score,
        recommendation=payload.recommendation.value,
        comment=payload.comment,
    )
