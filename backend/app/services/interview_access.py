"""One authorization contract for interview recordings and their files."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import Interview, InterviewPanel, User, UserRole


def can_access_interview(db: Session, interview: Interview, user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    if role in {UserRole.ADMIN.value, UserRole.HR.value}:
        return True
    if interview.interviewer_id == user.id:
        return True
    member_ids = {str(member_id) for member_id in (interview.panel_members or [])}
    if str(user.id) in member_ids:
        return True
    return (
        db.query(InterviewPanel.id)
        .filter(
            InterviewPanel.interview_id == interview.id,
            InterviewPanel.interviewer_id == user.id,
        )
        .first()
        is not None
    )


def require_interview_access(db: Session, interview_id, user: User) -> Interview:
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if not can_access_interview(db, interview, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Interview access denied")
    return interview
