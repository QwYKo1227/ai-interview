from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import (
    Position,
    PositionCategory,
    PositionEvent,
    PositionEventType,
    Resume,
    ResumeStatus,
    QuestionBank,
    User,
    UserRole,
)
from app.schemas.position import (
    PositionCreate,
    PositionUpdate,
    PositionStats,
    PositionWithStats,
    PositionEventResponse,
    QuestionBankBrief,
)
from app.models.models import PositionStatus
from uuid import UUID
from typing import List, Optional
from app.services.ai_service import generate_jd
from fastapi import HTTPException
from datetime import datetime, timezone
from app.services.recruitment_performance_service import sync_position_slots
from app.services.recruitment_access import can_manage_position, is_admin


STATUS_TRANSITIONS = {
    PositionStatus.OPEN: frozenset({PositionStatus.PUBLISHED, PositionStatus.CANCELLED}),
    PositionStatus.PUBLISHED: frozenset({PositionStatus.PAUSED, PositionStatus.CLOSED, PositionStatus.CANCELLED}),
    PositionStatus.PAUSED: frozenset({PositionStatus.PUBLISHED, PositionStatus.CLOSED, PositionStatus.CANCELLED}),
    PositionStatus.CLOSED: frozenset(),
    PositionStatus.CANCELLED: frozenset(),
}
ADMIN_REOPEN_TARGETS = frozenset({PositionStatus.OPEN, PositionStatus.PUBLISHED})


POSITION_PROGRESS_STATUS_GROUPS = {
    "pending_screening": frozenset({
        ResumeStatus.PENDING_SCREENING,
        ResumeStatus.PENDING_REVIEW,
        ResumeStatus.PENDING_DEPT_REVIEW,
        ResumeStatus.PENDING_HR_DECISION,
        ResumeStatus.AUTO_REJECTED_PENDING_REVIEW,
        ResumeStatus.WAITLIST,
    }),
    "pending_interview": frozenset({
        ResumeStatus.PENDING_INTERVIEW,
        ResumeStatus.INTERVIEW_SCHEDULED,
        ResumeStatus.INTERVIEW_IN_PROGRESS,
        ResumeStatus.PENDING_NEXT_INTERVIEW,
    }),
    "interview_completed": frozenset({ResumeStatus.PENDING_INTERVIEW_RESULT}),
    "interview_passed": frozenset({ResumeStatus.INTERVIEW_PASSED}),
    "offer_pending": frozenset({ResumeStatus.OFFER_PENDING}),
    "offer_accepted": frozenset({
        ResumeStatus.OFFER_ACCEPTED,
        ResumeStatus.ONBOARDING,
        ResumeStatus.COMPLETED,
    }),
    "rejected": frozenset({
        ResumeStatus.REJECTED,
        ResumeStatus.INTERVIEW_FAILED,
        ResumeStatus.OFFER_REJECTED,
    }),
}

def get_positions(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: Optional[UUID] = None,
    department: Optional[str] = None,
    priority: Optional[int] = None,
    category: Optional[PositionCategory] = None,
    current_user: Optional[User] = None,
    include_deleted: bool = False,
    deleted_only: bool = False,
):
    query = db.query(Position)
    if deleted_only:
        query = query.filter(Position.deleted_at.isnot(None))
    elif not include_deleted:
        query = query.filter(Position.deleted_at.is_(None))
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
    if priority is not None:
        query = query.filter(Position.priority == priority)
    if category:
        query = query.filter(Position.category == category)
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
    query = db.query(Position.department).filter(Position.deleted_at.is_(None))
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
    priority: Optional[int] = None,
    category: Optional[PositionCategory] = None,
    current_user: Optional[User] = None,
    include_deleted: bool = False,
    deleted_only: bool = False,
) -> List[PositionWithStats]:
    query = db.query(Position)
    if deleted_only:
        query = query.filter(Position.deleted_at.isnot(None))
    elif not include_deleted:
        query = query.filter(Position.deleted_at.is_(None))
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
    if priority is not None:
        query = query.filter(Position.priority == priority)
    if category:
        query = query.filter(Position.category == category)
    
    positions = query.order_by(Position.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for pos in positions:
        stats = get_position_stats(db, pos.id)
        hiring_manager_name = None
        deleted_by_name = None
        if pos.hiring_manager_id:
            user = db.query(User).filter(User.id == pos.hiring_manager_id).first()
            if user:
                hiring_manager_name = user.full_name
        if pos.deleted_by:
            deleted_user = db.query(User).filter(User.id == pos.deleted_by).first()
            if deleted_user:
                deleted_by_name = deleted_user.full_name or deleted_user.email
        
        pos_dict = {
            **{c.name: getattr(pos, c.name) for c in pos.__table__.columns},
            'stats': stats.model_dump(),
            'hiring_manager_name': hiring_manager_name,
            'deleted_by_name': deleted_by_name,
        }
        result.append(PositionWithStats(**pos_dict))
    
    return result

def get_position(db: Session, position_id: UUID, *, include_deleted: bool = False):
    query = db.query(Position).filter(Position.id == position_id)
    if not include_deleted:
        query = query.filter(Position.deleted_at.is_(None))
    return query.first()


def get_position_events(db: Session, position_id: UUID) -> List[PositionEventResponse]:
    events = (
        db.query(PositionEvent)
        .filter(PositionEvent.position_id == position_id)
        .order_by(PositionEvent.occurred_at.desc(), PositionEvent.id.desc())
        .all()
    )
    owner_event_types = {
        PositionEventType.INITIAL_OWNER,
        PositionEventType.OWNER_CHANGED,
    }
    owner_ids: set[UUID] = set()
    for event in events:
        if event.event_type not in owner_event_types:
            continue
        for raw_owner_id in (event.old_value, event.new_value):
            if not raw_owner_id:
                continue
            try:
                owner_ids.add(UUID(raw_owner_id))
            except (TypeError, ValueError):
                continue

    owner_names = {
        str(owner.id): owner.full_name or owner.email
        for owner in db.query(User).filter(User.id.in_(owner_ids)).all()
    } if owner_ids else {}

    result: List[PositionEventResponse] = []
    for event in events:
        metadata = dict(event.event_metadata or {})
        if event.event_type in owner_event_types:
            if event.old_value and "old_owner_name" not in metadata:
                metadata["old_owner_name"] = owner_names.get(event.old_value)
            if event.new_value and "new_owner_name" not in metadata:
                metadata["new_owner_name"] = owner_names.get(event.new_value)
        result.append(
            PositionEventResponse.model_validate(event).model_copy(
                update={"event_metadata": metadata}
            )
        )
    return result

def get_position_stats(db: Session, position_id: UUID) -> PositionStats:
    resumes = db.query(Resume).filter(Resume.position_id == position_id).all()

    bucket_counts = {
        bucket: sum(resume.status in statuses for resume in resumes)
        for bucket, statuses in POSITION_PROGRESS_STATUS_GROUPS.items()
    }
    return PositionStats(total_resumes=len(resumes), **bucket_counts)

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


def _clean_reason(reason: Optional[str]) -> Optional[str]:
    cleaned = reason.strip() if reason else ""
    return cleaned or None


def _actor_name(actor: Optional[User]) -> Optional[str]:
    if actor is None:
        return None
    return actor.full_name or actor.email


def _add_position_event(
    db: Session,
    position: Position,
    event_type: PositionEventType,
    *,
    actor: Optional[User],
    occurred_at: datetime,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
    event_metadata: Optional[dict] = None,
) -> None:
    db.add(PositionEvent(
        tenant_id=position.tenant_id,
        position_id=position.id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
        actor_id=actor.id if actor else None,
        actor_name=_actor_name(actor),
        reason=_clean_reason(reason),
        occurred_at=occurred_at,
        event_metadata=event_metadata or {},
    ))


def _validate_status_change(
    current: PositionStatus,
    target: PositionStatus,
    actor: Optional[User],
    reason: Optional[str],
) -> None:
    if current == target:
        return
    if current in {PositionStatus.CLOSED, PositionStatus.CANCELLED}:
        if actor is None or not is_admin(actor) or target not in ADMIN_REOPEN_TARGETS:
            raise HTTPException(status_code=400, detail="当前岗位已终止，仅管理员可重开为待发布或招聘中")
    elif target not in STATUS_TRANSITIONS[current]:
        raise HTTPException(
            status_code=400,
            detail=f"不允许将岗位从 {current.value} 变更为 {target.value}",
        )
    requires_reason = (
        target in {PositionStatus.PAUSED, PositionStatus.CANCELLED}
        or current in {PositionStatus.CLOSED, PositionStatus.CANCELLED}
    )
    if requires_reason and _clean_reason(reason) is None:
        raise HTTPException(status_code=400, detail="本次岗位状态变更必须填写原因")


def create_position(db: Session, position: PositionCreate, *, actor: Optional[User] = None):
    if position.hiring_manager_id is None:
        raise HTTPException(status_code=400, detail="招聘负责人不能为空")
    owner = _validate_recruitment_owner(db, position.hiring_manager_id)
    if position.status not in {PositionStatus.OPEN, PositionStatus.PUBLISHED}:
        raise HTTPException(status_code=400, detail="新建岗位只能为待发布或招聘中")
    db_position = Position(**position.model_dump())
    db.add(db_position)
    db.flush()
    occurred_at = db_position.created_at or datetime.now(timezone.utc)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    _add_position_event(
        db,
        db_position,
        PositionEventType.INITIAL_STATUS,
        actor=actor,
        occurred_at=occurred_at,
        new_value=db_position.status.value,
    )
    _add_position_event(
        db,
        db_position,
        PositionEventType.INITIAL_OWNER,
        actor=actor,
        occurred_at=occurred_at,
        new_value=str(owner.id),
        event_metadata={"new_owner_name": owner.full_name or owner.email},
    )
    sync_position_slots(db, db_position, assigned_at=occurred_at)
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
    db_position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if db_position is None:
        return None
    update_data = position.model_dump(exclude_unset=True)
    status_reason = _clean_reason(update_data.pop("status_change_reason", None))
    body_owner_reason = _clean_reason(update_data.pop("owner_change_reason", None))
    effective_owner_reason = body_owner_reason or _clean_reason(owner_change_reason)

    if actor is not None and not can_manage_position(db_position, actor):
        raise HTTPException(status_code=404, detail="Position not found")

    now = datetime.now(timezone.utc)
    current_status = db_position.status
    target_status = update_data.get("status", current_status)
    classification_changed = any(
        field in update_data and update_data[field] != getattr(db_position, field)
        for field in ("priority", "category")
    )
    if (
        current_status == PositionStatus.PUBLISHED
        and actor is not None
        and not is_admin(actor)
        and classification_changed
    ):
        raise HTTPException(
            status_code=403,
            detail="岗位发布后，只有管理员可以修改优先度和岗位分类",
        )
    if target_status != current_status:
        _validate_status_change(current_status, target_status, actor, status_reason)
        _add_position_event(
            db,
            db_position,
            PositionEventType.STATUS_CHANGED,
            actor=actor,
            occurred_at=now,
            old_value=current_status.value,
            new_value=target_status.value,
            reason=status_reason,
        )

    if "hiring_manager_id" in update_data:
        owner_id = update_data["hiring_manager_id"]
        if owner_id is None:
            raise HTTPException(status_code=400, detail="招聘负责人不能为空")
        new_owner = _validate_recruitment_owner(db, owner_id)
        if owner_id != db_position.hiring_manager_id:
            if actor is None or not is_admin(actor):
                raise HTTPException(status_code=403, detail="只有管理员可以变更招聘负责人")
            if effective_owner_reason is None:
                raise HTTPException(status_code=400, detail="变更招聘负责人必须填写原因")
            old_owner = (
                db.query(User).filter(User.id == db_position.hiring_manager_id).first()
                if db_position.hiring_manager_id else None
            )
            history = list(db_position.hiring_manager_history or [])
            history.append({
                "old_owner_id": str(db_position.hiring_manager_id) if db_position.hiring_manager_id else None,
                "new_owner_id": str(owner_id),
                "actor_id": str(actor.id),
                "changed_at": now.isoformat(),
                "reason": effective_owner_reason,
            })
            db_position.hiring_manager_history = history
            _add_position_event(
                db,
                db_position,
                PositionEventType.OWNER_CHANGED,
                actor=actor,
                occurred_at=now,
                old_value=str(db_position.hiring_manager_id) if db_position.hiring_manager_id else None,
                new_value=str(owner_id),
                reason=effective_owner_reason,
                event_metadata={
                    "old_owner_name": (old_owner.full_name or old_owner.email) if old_owner else None,
                    "new_owner_name": new_owner.full_name or new_owner.email,
                },
            )
    for key, value in update_data.items():
        setattr(db_position, key, value)
    if "headcount" in update_data:
        sync_position_slots(db, db_position, assigned_at=now)
    db.commit()
    db.refresh(db_position)
    return db_position


def batch_update_position_status(
    db: Session,
    position_ids: List[UUID],
    target_status: PositionStatus,
    *,
    reason: Optional[str],
    actor: User,
) -> int:
    unique_ids = list(dict.fromkeys(position_ids))
    positions = (
        db.query(Position)
        .filter(Position.id.in_(unique_ids), Position.deleted_at.is_(None))
        .order_by(Position.id)
        .with_for_update()
        .all()
    )
    if len(positions) != len(unique_ids):
        raise HTTPException(status_code=404, detail="部分岗位不存在或已删除")
    for db_position in positions:
        if not can_manage_position(db_position, actor):
            raise HTTPException(status_code=404, detail="Position not found")
        _validate_status_change(db_position.status, target_status, actor, reason)

    now = datetime.now(timezone.utc)
    for db_position in positions:
        if db_position.status == target_status:
            continue
        old_status = db_position.status
        db_position.status = target_status
        _add_position_event(
            db,
            db_position,
            PositionEventType.STATUS_CHANGED,
            actor=actor,
            occurred_at=now,
            old_value=old_status.value,
            new_value=target_status.value,
            reason=reason,
            event_metadata={"batch": True},
        )
    db.commit()
    return len(positions)


def soft_delete_position(db: Session, position_id: UUID, *, actor: User, reason: str):
    if not is_admin(actor):
        raise HTTPException(status_code=403, detail="只有管理员可以删除岗位")
    cleaned_reason = _clean_reason(reason)
    if cleaned_reason is None:
        raise HTTPException(status_code=400, detail="删除岗位必须填写原因")
    db_position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if db_position is None:
        return None
    now = datetime.now(timezone.utc)
    db_position.deleted_at = now
    db_position.deleted_by = actor.id
    db_position.delete_reason = cleaned_reason
    _add_position_event(
        db,
        db_position,
        PositionEventType.SOFT_DELETED,
        actor=actor,
        occurred_at=now,
        old_value=db_position.status.value,
        new_value="deleted",
        reason=cleaned_reason,
    )
    db.commit()
    db.refresh(db_position)
    return db_position


def restore_position(db: Session, position_id: UUID, *, actor: User, reason: str):
    if not is_admin(actor):
        raise HTTPException(status_code=403, detail="只有管理员可以恢复岗位")
    cleaned_reason = _clean_reason(reason)
    if cleaned_reason is None:
        raise HTTPException(status_code=400, detail="恢复岗位必须填写原因")
    db_position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.deleted_at.isnot(None))
        .with_for_update()
        .first()
    )
    if db_position is None:
        return None
    now = datetime.now(timezone.utc)
    previous_status = db_position.status
    db_position.deleted_at = None
    db_position.deleted_by = None
    db_position.delete_reason = None
    db_position.status = PositionStatus.OPEN
    _add_position_event(
        db,
        db_position,
        PositionEventType.RESTORED,
        actor=actor,
        occurred_at=now,
        old_value="deleted",
        new_value=PositionStatus.OPEN.value,
        reason=cleaned_reason,
        event_metadata={"status_before_delete": previous_status.value},
    )
    db.commit()
    db.refresh(db_position)
    return db_position
