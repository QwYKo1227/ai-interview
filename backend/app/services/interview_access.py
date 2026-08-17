"""One authorization contract for interview recordings and their files."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import Interview, User, UserRole
from app.services.recruitment_access import can_access_interview_as_owner


def is_interviewer_assigned(
    db: Session,
    interview: Interview,
    interviewer_id,
) -> bool:
    """Return an authoritative assignment, never inferred from response state."""

    if interview.interviewer_id == interviewer_id:
        return True
    member_ids = {str(member_id) for member_id in (interview.panel_members or [])}
    return str(interviewer_id) in member_ids


def can_access_interview(db: Session, interview: Interview, user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    if role == UserRole.ADMIN.value:
        return True
    if role == UserRole.HR.value:
        return can_access_interview_as_owner(interview, user) or is_interviewer_assigned(
            db,
            interview,
            user.id,
        )
    return is_interviewer_assigned(db, interview, user.id)


def can_score_interview(db: Session, interview: Interview, user: User) -> bool:
    """Apply the scoring matrix without mutating the interview assignment."""

    return can_access_interview(db, interview, user)


def require_interview_access(db: Session, interview_id, user: User) -> Interview:
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if not can_access_interview(db, interview, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    return interview


def require_interview_assignment(
    db: Session,
    interview_id,
    user: User,
) -> Interview:
    """Require scoring permission without turning response rows into assignments."""

    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )
    if not can_score_interview(db, interview, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Interview assignment required",
        )
    return interview


def require_assigned_interviewer(
    db: Session,
    interview_id,
    user: User,
) -> Interview:
    """Require actual panel membership, excluding role-based administrative access."""

    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if not is_interviewer_assigned(db, interview, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Interview assignment required")
    return interview
