from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import (
    Position,
    PositionUrgency,
    Resume,
    ResumeStatus,
    QuestionBank,
    User,
    UserRole,
)
from app.schemas.position import PositionCreate, PositionUpdate, PositionStats, PositionWithStats, QuestionBankBrief
from app.models.models import PositionStatus
from uuid import UUID
from typing import List, Optional
from app.services.ai_service import generate_jd
from fastapi import HTTPException
from datetime import datetime, timezone
from app.services.recruitment_access import is_admin

def get_positions(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: Optional[UUID] = None,
    department: Optional[str] = None,
    urgency: Optional[PositionUrgency] = None,
    current_user: Optional[User] = None,
):
    query = db.query(Position)
    if current_user is not None and not is_admin(current_user):
        query = query.filter(Position.hiring_manager_id == current_user.id)
    if status:
        query = query.filter(Position.status == status)
    if title:
        query = query.filter(Position.title.ilike(f"%{title}%"))
    if hiring_manager_id:
        query = query.filter(Position.hiring_manager_id == hiring_manager_id)
    if department:
        query = query.filter(Position.department == department)
    if urgency:
        query = query.filter(Position.urgency == urgency)
    return query.order_by(Position.created_at.desc()).offset(skip).limit(limit).all()


def get_hiring_managers(db: Session) -> List[User]:
    return (
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.role.in_([UserRole.ADMIN, UserRole.HR]),
        )
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )


def get_position_departments(db: Session, current_user: Optional[User] = None) -> List[str]:
    query = db.query(Position.department)
    if current_user is not None and not is_admin(current_user):
        query = query.filter(Position.hiring_manager_id == current_user.id)
    rows = (
        query
        .filter(Position.department.isnot(None), func.trim(Position.department) != "")
        .distinct()
        .order_by(Position.department.asc())
        .all()
    )
    return [department for (department,) in rows]

def get_positions_with_stats(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: Optional[UUID] = None,
    department: Optional[str] = None,
    urgency: Optional[PositionUrgency] = None,
    current_user: Optional[User] = None,
) -> List[PositionWithStats]:
    query = db.query(Position)
    if current_user is not None and not is_admin(current_user):
        query = query.filter(Position.hiring_manager_id == current_user.id)
    if status:
        query = query.filter(Position.status == status)
    if title:
        query = query.filter(Position.title.ilike(f"%{title}%"))
    if hiring_manager_id:
        query = query.filter(Position.hiring_manager_id == hiring_manager_id)
    if department:
        query = query.filter(Position.department == department)
    if urgency:
        query = query.filter(Position.urgency == urgency)
    
    positions = query.order_by(Position.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for pos in positions:
        stats = get_position_stats(db, pos.id)
        hiring_manager_name = None
        if pos.hiring_manager_id:
            user = db.query(User).filter(User.id == pos.hiring_manager_id).first()
            if user:
                hiring_manager_name = user.full_name
        
        pos_dict = {
            **{c.name: getattr(pos, c.name) for c in pos.__table__.columns},
            'stats': stats.model_dump(),
            'hiring_manager_name': hiring_manager_name
        }
        result.append(PositionWithStats(**pos_dict))
    
    return result

def get_position(db: Session, position_id: UUID):
    return db.query(Position).filter(Position.id == position_id).first()

def get_position_stats(db: Session, position_id: UUID) -> PositionStats:
    resumes = db.query(Resume).filter(Resume.position_id == position_id).all()
    
    stats = PositionStats(
        total_resumes=len(resumes),
        pending_screening=sum(1 for r in resumes if r.status in [
            ResumeStatus.PENDING_SCREENING, 
            ResumeStatus.PENDING_REVIEW
        ]),
        pending_interview=sum(1 for r in resumes if r.status in [
            ResumeStatus.PENDING_INTERVIEW,
            ResumeStatus.INTERVIEW_SCHEDULED,
            ResumeStatus.INTERVIEW_IN_PROGRESS,
            ResumeStatus.PENDING_INTERVIEW_RESULT,
            ResumeStatus.PENDING_NEXT_INTERVIEW,
        ]),
        interview_completed=sum(1 for r in resumes if r.status in [
            ResumeStatus.INTERVIEW_PASSED, 
            ResumeStatus.INTERVIEW_FAILED,
            ResumeStatus.OFFER_PENDING,
            ResumeStatus.OFFER_ACCEPTED,
            ResumeStatus.OFFER_REJECTED,
            ResumeStatus.COMPLETED
        ]),
        offer_pending=sum(1 for r in resumes if r.status == ResumeStatus.OFFER_PENDING),
        offer_accepted=sum(1 for r in resumes if r.status in [
            ResumeStatus.OFFER_ACCEPTED,
            ResumeStatus.COMPLETED
        ]),
        rejected=sum(1 for r in resumes if r.status in [
            ResumeStatus.REJECTED,
            ResumeStatus.INTERVIEW_FAILED,
            ResumeStatus.OFFER_REJECTED
        ])
    )
    return stats

def get_linked_question_banks(db: Session, position_id: UUID) -> List[QuestionBankBrief]:
    banks = db.query(QuestionBank).filter(QuestionBank.position_id == position_id).all()
    result = []
    for bank in banks:
        question_count = len(bank.questions) if bank.questions else 0
        result.append(QuestionBankBrief(
            id=bank.id,
            name=bank.name,
            category=bank.category.value if bank.category else "other",
            question_count=question_count
        ))
    return result

def delete_position(db: Session, position_id: UUID):
    db_position = db.query(Position).filter(Position.id == position_id).first()
    if not db_position:
        return None

    # 检查是否有关联的简历
    related_resumes = db.query(Resume).filter(Resume.position_id == position_id).count()
    if related_resumes > 0:
        raise HTTPException(
            status_code=400,
            detail=f"无法删除该岗位，存在 {related_resumes} 份关联简历"
        )

    # 检查是否有关联的题库
    related_banks = db.query(QuestionBank).filter(QuestionBank.position_id == position_id).count()
    if related_banks > 0:
        raise HTTPException(
            status_code=400,
            detail=f"无法删除该岗位，存在 {related_banks} 个关联题库"
        )

    db.delete(db_position)
    db.commit()
    return db_position

def generate_position_jd(db: Session, title: str, department: str = None, location: str = None, salary_range: str = None, keywords: str = None) -> dict:
    return generate_jd(
        title=title,
        department=department,
        location=location,
        salary_range=salary_range,
        keywords=keywords,
        db=db,
    )


def _validate_recruitment_owner(db: Session, owner_id: UUID) -> User:
    owner = db.query(User).filter(User.id == owner_id).first()
    if owner is None or not owner.is_active or owner.role not in {UserRole.ADMIN, UserRole.HR}:
        raise HTTPException(status_code=400, detail="招聘负责人必须是有效的 HR 或管理员")
    return owner


def create_position(db: Session, position: PositionCreate):
    if position.hiring_manager_id is None:
        raise HTTPException(status_code=400, detail="招聘负责人不能为空")
    _validate_recruitment_owner(db, position.hiring_manager_id)
    db_position = Position(**position.model_dump())
    db.add(db_position)
    db.commit()
    db.refresh(db_position)
    return db_position


def update_position(
    db: Session,
    position_id: UUID,
    position: PositionUpdate,
    *,
    actor: Optional[User] = None,
    owner_change_reason: Optional[str] = None,
):
    db_position = db.query(Position).filter(Position.id == position_id).first()
    if db_position is None:
        return None
    update_data = position.model_dump(exclude_unset=True)
    if "hiring_manager_id" in update_data:
        owner_id = update_data["hiring_manager_id"]
        if owner_id is None:
            raise HTTPException(status_code=400, detail="招聘负责人不能为空")
        _validate_recruitment_owner(db, owner_id)
        if owner_id != db_position.hiring_manager_id:
            if actor is None or not is_admin(actor):
                raise HTTPException(status_code=403, detail="只有管理员可以变更招聘负责人")
            history = list(db_position.hiring_manager_history or [])
            history.append({
                "old_owner_id": str(db_position.hiring_manager_id) if db_position.hiring_manager_id else None,
                "new_owner_id": str(owner_id),
                "actor_id": str(actor.id),
                "changed_at": datetime.now(timezone.utc).isoformat(),
                "reason": owner_change_reason or None,
            })
            db_position.hiring_manager_history = history
    for key, value in update_data.items():
        setattr(db_position, key, value)
    db.commit()
    db.refresh(db_position)
    return db_position
