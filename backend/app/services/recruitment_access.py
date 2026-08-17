"""Shared authorization rules for position-owned recruitment data."""

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.models import (
    DepartmentReview,
    Interview,
    Position,
    PositionStatus,
    Resume,
    User,
    UserRole,
)


def role_value(user: User) -> str:
    return getattr(user.role, "value", user.role)


def is_admin(user: User) -> bool:
    return role_value(user) == UserRole.ADMIN.value


def is_recruiter(user: User) -> bool:
    return role_value(user) == UserRole.HR.value


def owns_position(position: Position | None, user: User) -> bool:
    return bool(
        is_recruiter(user)
        and position
        and position.hiring_manager_id == user.id
    )


def can_manage_position(position: Position | None, user: User) -> bool:
    return is_admin(user) or owns_position(position, user)


def has_nonclosed_owned_positions(db: Session, user_id) -> bool:
    return (
        db.query(Position.id)
        .filter(
            Position.hiring_manager_id == user_id,
            Position.deleted_at.is_(None),
            or_(
                Position.status.notin_([PositionStatus.CLOSED, PositionStatus.CANCELLED]),
                Position.status.is_(None),
            ),
        )
        .first()
        is not None
    )


def require_position_access(
    db: Session,
    position_id,
    user: User,
    *,
    include_deleted: bool = False,
) -> Position:
    query = db.query(Position).filter(Position.id == position_id)
    if not include_deleted:
        query = query.filter(Position.deleted_at.is_(None))
    if not is_admin(user):
        if not is_recruiter(user):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )
        query = query.filter(Position.hiring_manager_id == user.id)
    position = query.first()
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found",
        )
    return position


def is_department_reviewer(db: Session, resume_id, user: User) -> bool:
    return (
        db.query(DepartmentReview.id)
        .filter(
            DepartmentReview.resume_id == resume_id,
            DepartmentReview.reviewer_id == user.id,
        )
        .first()
        is not None
    )


def can_access_resume(db: Session, resume: Resume | None, user: User) -> bool:
    if resume is None:
        return False
    if is_admin(user):
        return True
    if resume.position and owns_position(resume.position, user):
        return True
    return is_department_reviewer(db, resume.id, user)


def can_manage_resume(resume: Resume | None, user: User) -> bool:
    if resume is None:
        return False
    return is_admin(user) or owns_position(resume.position, user)


def require_resume_access(
    db: Session,
    resume_id,
    user: User,
    *,
    manage: bool = False,
) -> Resume:
    resume = db.query(Resume).filter(Resume.id == resume_id).first()
    allowed = can_manage_resume(resume, user) if manage else can_access_resume(db, resume, user)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


def can_access_interview_as_owner(interview: Interview | None, user: User) -> bool:
    if interview is None:
        return False
    return is_admin(user) or owns_position(interview.position, user)
