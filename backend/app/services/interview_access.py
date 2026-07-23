"""One authorization contract for interview recordings and their files."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import Interview, InterviewPanel, User, UserRole


def is_interviewer_assigned(
    db: Session,
    interview: Interview,
    interviewer_id,
) -> bool:
    """Return whether one interviewer was explicitly assigned before scoring."""

    if interview.interviewer_id == interviewer_id:
        return True
    member_ids = {str(member_id) for member_id in (interview.panel_members or [])}
    if str(interviewer_id) in member_ids:
        return True
    return (
        db.query(InterviewPanel.id)
        .filter(
            InterviewPanel.interview_id == interview.id,
            InterviewPanel.interviewer_id == interviewer_id,
        )
        .first()
        is not None
    )


def can_access_interview(db: Session, interview: Interview, user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    if role in {UserRole.ADMIN.value, UserRole.HR.value}:
        return True
    return is_interviewer_assigned(db, interview, user.id)


def require_interview_access(db: Session, interview_id, user: User) -> Interview:
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if not can_access_interview(db, interview, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Interview access denied")
    return interview


def require_interview_assignment(
    db: Session,
    interview_id,
    user: User,
) -> Interview:
    """Require an explicit assignment; privileged roles do not self-assign."""

    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )
    if not is_interviewer_assigned(db, interview, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Interview assignment required",
        )
    return interview
