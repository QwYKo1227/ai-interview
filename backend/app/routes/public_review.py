from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.models.models import DepartmentReview
from app.services.public_token_service import enforce_public_request_tenant, resolve_public_token
from app.services.resume_service import get_public_review_payload, submit_public_department_review
from app.schemas.resume import PublicDepartmentReviewSubmit


router = APIRouter(prefix="/public/review", tags=["public-review"])


def _resolve_review(db: Session, token: str, request: Request) -> DepartmentReview:
    resolved = resolve_public_token(db, token, "department_review")
    enforce_public_request_tenant(
        db, request_host=request.headers.get("host", ""), tenant_id=resolved.tenant_id
    )
    return resolved.resource


@router.get("/{token}")
def get_resume_for_review(
    token: str,
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request)
    return get_public_review_payload(db, review)


@router.post("/{token}/submit")
def submit_review(
    token: str,
    request: Request,
    payload: PublicDepartmentReviewSubmit,
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request)
    return submit_public_department_review(
        db,
        review,
        technical_score=payload.technical_score,
        experience_score=payload.experience_score,
        overall_score=payload.overall_score,
        recommendation=payload.recommendation.value,
        comment=payload.comment,
    )
