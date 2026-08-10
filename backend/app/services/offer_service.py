from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, update, case
from app.models.models import (
    Offer, OfferStatus, Resume, ResumeStatus, Position, PositionStatus, User,
    UserRole, OfferDecisionAudit
)
from app.schemas.offer import OfferCreate, OfferUpdate, OfferStats
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID
from fastapi import HTTPException

from app.services.public_token_service import resolve_public_token, revoke_public_tokens
from app.config.tenant_session import get_tenant_id

DECISION_REASONS = {
    "salary",
    "other_offer",
    "position_mismatch",
    "location",
    "onboard_date",
    "personal",
    "unreachable",
    "other",
}


def can_decide_offer(offer: Offer, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    manager_id = offer.position.hiring_manager_id if offer.position else None
    return manager_id == user.id


def _offer_access_query(db: Session, user: User):
    query = db.query(Offer)
    if user.role != UserRole.ADMIN:
        query = query.join(Position, Offer.position_id == Position.id).filter(
            Position.hiring_manager_id == user.id
        )
    return query


def _decision_fields(offer: Offer, current_user: Optional[User]) -> Dict[str, Any]:
    manager = offer.position.hiring_manager if offer.position else None
    return {
        "hiring_manager_id": str(manager.id) if manager else None,
        "hiring_manager_name": (manager.full_name or manager.email) if manager else None,
        "can_decide": bool(current_user and can_decide_offer(offer, current_user)),
    }

def create_offer(db: Session, offer_data: OfferCreate, user_id: UUID) -> Offer:
    resume = db.query(Resume).filter(Resume.id == offer_data.resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    position = db.query(Position).filter(Position.id == offer_data.position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    
    existing_offer = db.query(Offer).filter(
        Offer.resume_id == offer_data.resume_id,
        Offer.status.in_([OfferStatus.DRAFT, OfferStatus.PENDING, OfferStatus.SENT])
    ).first()
    if existing_offer:
        raise ValueError("该候选人已有进行中的Offer")
    
    offer = Offer(
        resume_id=offer_data.resume_id,
        position_id=offer_data.position_id,
        candidate_name=offer_data.candidate_name,
        candidate_email=offer_data.candidate_email,
        salary_monthly=float(offer_data.salary_monthly) if offer_data.salary_monthly else None,
        salary_annual=float(offer_data.salary_annual) if offer_data.salary_annual else None,
        salary_structure=offer_data.salary_structure,
        position_title=offer_data.position_title,
        department=offer_data.department,
        report_to=offer_data.report_to,
        work_location=offer_data.work_location,
        work_hours=offer_data.work_hours,
        onboard_date=offer_data.onboard_date,
        probation_months=offer_data.probation_months or 3,
        benefits=offer_data.benefits,
        bonus=offer_data.bonus,
        special_terms=offer_data.special_terms,
        notes=offer_data.notes,
        valid_until=offer_data.valid_until,
        status=OfferStatus.DRAFT,
        created_by=user_id
    )
    
    db.add(offer)
    db.commit()
    db.refresh(offer)
    
    return offer

def get_offers(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    status: Optional[str] = None,
    position_id: Optional[UUID] = None,
    search: Optional[str] = None,
    current_user: Optional[User] = None,
) -> Dict[str, Any]:
    query = _offer_access_query(db, current_user) if current_user else db.query(Offer)
    
    if status:
        query = query.filter(Offer.status == status)
    
    if position_id:
        query = query.filter(Offer.position_id == position_id)
    
    if search:
        query = query.filter(
            or_(
                Offer.candidate_name.ilike(f"%{search}%"),
                Offer.candidate_email.ilike(f"%{search}%"),
                Offer.position_title.ilike(f"%{search}%")
            )
        )
    
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    
    if current_user:
        manager_first = case(
            (Position.hiring_manager_id == current_user.id, 0),
            else_=1,
        )
        if current_user.role == UserRole.ADMIN:
            query = query.outerjoin(Position, Offer.position_id == Position.id)
        query = query.order_by(
            case((Offer.status == OfferStatus.SENT, 0), else_=1),
            manager_first,
            desc(Offer.created_at),
        )
    else:
        query = query.order_by(desc(Offer.created_at))
    offers = query.offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for offer in offers:
        item = {
            "id": str(offer.id),
            "resume_id": str(offer.resume_id),
            "position_id": str(offer.position_id),
            "candidate_name": offer.candidate_name,
            "candidate_email": offer.candidate_email,
            "salary_monthly": offer.salary_monthly,
            "salary_annual": offer.salary_annual,
            "salary_structure": offer.salary_structure,
            "position_title": offer.position_title,
            "department": offer.department,
            "report_to": offer.report_to,
            "work_location": offer.work_location,
            "work_hours": offer.work_hours,
            "onboard_date": offer.onboard_date,
            "probation_months": offer.probation_months,
            "benefits": offer.benefits,
            "bonus": offer.bonus,
            "special_terms": offer.special_terms,
            "notes": offer.notes,
            "valid_until": offer.valid_until,
            "status": offer.status.value,
            "sent_at": offer.sent_at,
            "accepted_at": offer.accepted_at,
            "rejected_at": offer.rejected_at,
            "rejected_reason": offer.rejected_reason,
            "created_at": offer.created_at,
            "updated_at": offer.updated_at,
            "created_by": str(offer.created_by) if offer.created_by else None,
            "position_info": {
                "id": str(offer.position.id),
                "title": offer.position.title,
                "department": offer.position.department,
                "location": offer.position.location,
                "salary_range": offer.position.salary_range
            } if offer.position else None,
            "resume_info": {
                "id": str(offer.resume.id),
                "candidate_name": offer.resume.candidate_name,
                "email": offer.resume.email,
                "match_score": offer.resume.match_score
            } if offer.resume else None
        }
        item.update(_decision_fields(offer, current_user))
        items.append(item)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

def get_offer(
    db: Session, offer_id: UUID, current_user: Optional[User] = None
) -> Optional[Dict[str, Any]]:
    query = _offer_access_query(db, current_user) if current_user else db.query(Offer)
    offer = query.filter(Offer.id == offer_id).first()
    if not offer:
        return None
    
    result = {
        "id": str(offer.id),
        "resume_id": str(offer.resume_id),
        "position_id": str(offer.position_id),
        "candidate_name": offer.candidate_name,
        "candidate_email": offer.candidate_email,
        "salary_monthly": offer.salary_monthly,
        "salary_annual": offer.salary_annual,
        "salary_structure": offer.salary_structure,
        "position_title": offer.position_title,
        "department": offer.department,
        "report_to": offer.report_to,
        "work_location": offer.work_location,
        "work_hours": offer.work_hours,
        "onboard_date": offer.onboard_date,
        "probation_months": offer.probation_months,
        "benefits": offer.benefits,
        "bonus": offer.bonus,
        "special_terms": offer.special_terms,
        "notes": offer.notes,
        "valid_until": offer.valid_until,
        "status": offer.status.value,
        "sent_at": offer.sent_at,
        "accepted_at": offer.accepted_at,
        "rejected_at": offer.rejected_at,
        "rejected_reason": offer.rejected_reason,
        "created_at": offer.created_at,
        "updated_at": offer.updated_at,
        "created_by": str(offer.created_by) if offer.created_by else None,
        "position_info": {
            "id": str(offer.position.id),
            "title": offer.position.title,
            "department": offer.position.department,
            "location": offer.position.location,
            "salary_range": offer.position.salary_range
        } if offer.position else None,
        "resume_info": {
            "id": str(offer.resume.id),
            "candidate_name": offer.resume.candidate_name,
            "email": offer.resume.email,
            "match_score": offer.resume.match_score
        } if offer.resume else None
    }
    result.update(_decision_fields(offer, current_user))
    return result


def get_offer_record(
    db: Session, offer_id: UUID, current_user: User
) -> Optional[Offer]:
    """Return an ORM offer only when the caller may manage its position."""
    return _offer_access_query(db, current_user).filter(Offer.id == offer_id).first()

def update_offer(db: Session, offer_id: UUID, offer_data: OfferUpdate) -> Optional[Offer]:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        return None
    
    if offer.status not in [OfferStatus.DRAFT, OfferStatus.PENDING]:
        raise ValueError("当前状态不允许修改")
    
    update_fields = [
        'salary_monthly', 'salary_annual', 'salary_structure', 'position_title',
        'department', 'report_to', 'work_location', 'work_hours', 'onboard_date',
        'probation_months', 'benefits', 'bonus', 'special_terms', 'notes', 'valid_until'
    ]
    
    for field in update_fields:
        value = getattr(offer_data, field, None)
        if value is not None:
            if field in ['salary_monthly', 'salary_annual'] and value is not None:
                value = float(value)
            setattr(offer, field, value)
    
    db.commit()
    db.refresh(offer)
    
    return offer

def mark_offer_pending_confirmation(db: Session, offer_id: UUID) -> Dict[str, Any]:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise ValueError("Offer不存在")
    
    if offer.status not in [OfferStatus.DRAFT, OfferStatus.PENDING]:
        raise ValueError("当前状态不允许发送")
    
    resume = db.query(Resume).filter(Resume.id == offer.resume_id).first()
    revoke_public_tokens(db, offer.tenant_id, "offer", offer.id)
    offer.token = None
    offer.status = OfferStatus.SENT
    offer.sent_at = datetime.utcnow()
    if resume:
        resume.status = ResumeStatus.OFFER_PENDING
    db.commit()
    
    return {
        "success": True,
        "status": OfferStatus.SENT.value,
    }


def record_offer_decision(
    db: Session,
    offer_id: UUID,
    actor: User,
    decision: str,
    rejection_reason: Optional[str] = None,
    rejection_detail: Optional[str] = None,
    correction_reason: Optional[str] = None,
) -> Offer:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise ValueError("Offer不存在")
    if not can_decide_offer(offer, actor):
        raise PermissionError("只有该岗位的招聘负责人可以登记Offer结果")

    allowed_statuses = {
        OfferStatus.SENT,
        OfferStatus.EXPIRED,
        OfferStatus.ACCEPTED,
        OfferStatus.REJECTED,
    }
    if offer.status not in allowed_statuses:
        raise ValueError("当前状态不允许登记Offer结果")

    new_status = OfferStatus.ACCEPTED if decision == "accepted" else OfferStatus.REJECTED
    previous_status = offer.status
    is_correction = previous_status in {OfferStatus.ACCEPTED, OfferStatus.REJECTED}
    if is_correction:
        if previous_status == new_status:
            raise ValueError("更正结果必须与当前结果不同")
        if not correction_reason or not correction_reason.strip():
            raise ValueError("更正结果时必须填写更正原因")

    if new_status == OfferStatus.REJECTED:
        if rejection_reason not in DECISION_REASONS:
            raise ValueError("请选择有效的拒绝原因")
        if rejection_reason == "other" and not (rejection_detail or "").strip():
            raise ValueError("选择其他原因时必须填写说明")

    now = datetime.utcnow()
    offer.status = new_status
    if new_status == OfferStatus.ACCEPTED:
        offer.accepted_at = now
        offer.rejected_at = None
        offer.rejected_reason = None
    else:
        offer.rejected_at = now
        offer.accepted_at = None
        offer.rejected_reason = rejection_reason
        if rejection_detail:
            offer.rejected_reason = f"{rejection_reason}: {rejection_detail.strip()}"

    resume = db.query(Resume).filter(Resume.id == offer.resume_id).first()
    if resume:
        resume.status = (
            ResumeStatus.OFFER_ACCEPTED
            if new_status == OfferStatus.ACCEPTED
            else ResumeStatus.OFFER_REJECTED
        )

    db.add(OfferDecisionAudit(
        tenant_id=offer.tenant_id,
        offer_id=offer.id,
        actor_id=actor.id,
        previous_status=previous_status.value,
        new_status=new_status.value,
        rejection_reason=rejection_reason if new_status == OfferStatus.REJECTED else None,
        rejection_detail=(rejection_detail or "").strip() or None,
        correction_reason=(correction_reason or "").strip() or None,
    ))
    db.commit()
    db.refresh(offer)
    return offer


def get_offer_decision_audits(db: Session, offer_id: UUID) -> List[Dict[str, Any]]:
    rows = (
        db.query(OfferDecisionAudit)
        .filter(OfferDecisionAudit.offer_id == offer_id)
        .order_by(desc(OfferDecisionAudit.created_at))
        .all()
    )
    return [
        {
            "id": str(row.id),
            "previous_status": row.previous_status,
            "new_status": row.new_status,
            "rejection_reason": row.rejection_reason,
            "rejection_detail": row.rejection_detail,
            "correction_reason": row.correction_reason,
            "actor_id": str(row.actor_id),
            "actor_name": row.actor.full_name or row.actor.email,
            "created_at": row.created_at,
        }
        for row in rows
    ]

def withdraw_offer(db: Session, offer_id: UUID, reason: Optional[str] = None) -> Offer:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise ValueError("Offer不存在")
    
    if offer.status not in [OfferStatus.DRAFT, OfferStatus.PENDING, OfferStatus.SENT]:
        raise ValueError("当前状态不允许撤回")
    
    offer.status = OfferStatus.WITHDRAWN
    if reason:
        offer.notes = (offer.notes or "") + f"\n撤回原因: {reason}"
    
    db.commit()
    
    return offer

def reopen_offer(db: Session, offer_id: UUID) -> Offer:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise ValueError("Offer不存在")
    
    if offer.status != OfferStatus.WITHDRAWN:
        raise ValueError("当前状态不允许重新打开")
    
    old_status = offer.status.value
    # Reopening invalidates the old public link; an HR user must explicitly
    # send the offer again to issue and deliver a fresh credential.
    offer.status = OfferStatus.PENDING
    offer.token = None
    revoke_public_tokens(db, offer.tenant_id, "offer", offer.id)
    offer.notes = (offer.notes or "") + f"\n重新打开（原状态：{old_status}）"
    
    db.commit()
    
    resume = db.query(Resume).filter(Resume.id == offer.resume_id).first()
    if resume:
        resume.status = ResumeStatus.OFFER_PENDING
        db.commit()
    
    return offer

def get_offer_stats(db: Session, current_user: Optional[User] = None) -> Dict[str, Any]:
    query = _offer_access_query(db, current_user) if current_user else db.query(Offer)
    total_offers = query.count()
    pending_offers = query.filter(Offer.status == OfferStatus.PENDING).count()
    sent_offers = query.filter(Offer.status == OfferStatus.SENT).count()
    accepted_offers = query.filter(Offer.status == OfferStatus.ACCEPTED).count()
    rejected_offers = query.filter(Offer.status == OfferStatus.REJECTED).count()
    expired_offers = query.filter(Offer.status == OfferStatus.EXPIRED).count()
    
    total_decided = accepted_offers + rejected_offers
    acceptance_rate = round(accepted_offers / total_decided * 100, 1) if total_decided > 0 else 0
    
    accepted_offers_list = query.filter(
        Offer.status == OfferStatus.ACCEPTED,
        Offer.sent_at.isnot(None),
        Offer.accepted_at.isnot(None)
    ).all()
    
    response_days = []
    for offer in accepted_offers_list:
        if offer.sent_at and offer.accepted_at:
            days = (offer.accepted_at - offer.sent_at).days
            response_days.append(days)
    
    avg_response_days = round(sum(response_days) / len(response_days), 1) if response_days else None
    
    return {
        "total_offers": total_offers,
        "pending_offers": pending_offers,
        "sent_offers": sent_offers,
        "accepted_offers": accepted_offers,
        "rejected_offers": rejected_offers,
        "expired_offers": expired_offers,
        "acceptance_rate": acceptance_rate,
        "avg_response_days": avg_response_days
    }


def get_my_pending_offer_count(db: Session, current_user: User) -> int:
    query = db.query(Offer).join(Position, Offer.position_id == Position.id).filter(
        Offer.status == OfferStatus.SENT
    )
    if current_user.role == UserRole.ADMIN:
        query = query.filter(
            or_(
                Position.hiring_manager_id == current_user.id,
                Position.hiring_manager_id.is_(None),
            )
        )
    else:
        query = query.filter(Position.hiring_manager_id == current_user.id)
    return query.count()

def get_pending_offers_for_resume(db: Session, resume_id: UUID) -> List[Offer]:
    return db.query(Offer).filter(
        Offer.resume_id == resume_id,
        Offer.status.in_([OfferStatus.DRAFT, OfferStatus.PENDING, OfferStatus.SENT])
    ).all()

def mark_expired_offers(db: Session) -> int:
    expired_offers = db.query(Offer).filter(
        Offer.status == OfferStatus.SENT,
        Offer.valid_until < datetime.utcnow()
    ).all()
    for offer in expired_offers:
        offer.status = OfferStatus.EXPIRED
    
    db.commit()
    return len(expired_offers)

def get_offer_by_token(db: Session, token: str) -> Optional[Dict[str, Any]]:
    offer = resolve_public_token(db, token, "offer").resource
    
    return {
        "id": str(offer.id),
        "resume_id": str(offer.resume_id),
        "position_id": str(offer.position_id),
        "candidate_name": offer.candidate_name,
        "candidate_email": offer.candidate_email,
        "salary_monthly": offer.salary_monthly,
        "salary_annual": offer.salary_annual,
        "salary_structure": offer.salary_structure,
        "position_title": offer.position_title,
        "department": offer.department,
        "report_to": offer.report_to,
        "work_location": offer.work_location,
        "work_hours": offer.work_hours,
        "onboard_date": offer.onboard_date,
        "probation_months": offer.probation_months,
        "benefits": offer.benefits,
        "bonus": offer.bonus,
        "special_terms": offer.special_terms,
        "notes": offer.notes,
        "valid_until": offer.valid_until,
        "status": offer.status.value,
        "sent_at": offer.sent_at,
        "created_at": offer.created_at,
        "position_info": {
            "id": str(offer.position.id),
            "title": offer.position.title,
            "department": offer.position.department,
            "location": offer.position.location,
            "salary_range": offer.position.salary_range
        } if offer.position else None,
        "resume_info": {
            "id": str(offer.resume.id),
            "candidate_name": offer.resume.candidate_name,
            "email": offer.resume.email,
            "match_score": offer.resume.match_score
        } if offer.resume else None
    }

def confirm_offer_by_token(
    db: Session, token: str, action: str, reason: Optional[str] = None,
    accepted_salary: Optional[float] = None,
    accepted_onboard_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    offer = resolve_public_token(db, token, "offer").resource
    tenant_id = get_tenant_id(db)
    offer_id, resume_id = offer.id, offer.resume_id
    if offer.valid_until and datetime.utcnow() > offer.valid_until:
        db.execute(
            update(Offer).where(
                Offer.id == offer_id,
                Offer.tenant_id == tenant_id,
                Offer.status == OfferStatus.SENT,
            ).values(status=OfferStatus.EXPIRED)
        )
        revoke_public_tokens(db, tenant_id, "offer", offer_id)
        db.commit()
        return {"success": False, "error": "Offer expired"}

    if action == "accept":
        values = {"status": OfferStatus.ACCEPTED, "accepted_at": datetime.utcnow()}
        if accepted_salary is not None:
            values["salary_monthly"] = accepted_salary
        if accepted_onboard_date is not None:
            values["onboard_date"] = accepted_onboard_date
        resume_status, action_name = ResumeStatus.OFFER_ACCEPTED, "accepted"
    elif action == "reject":
        values = {
            "status": OfferStatus.REJECTED,
            "rejected_at": datetime.utcnow(),
            "rejected_reason": reason,
        }
        resume_status, action_name = ResumeStatus.OFFER_REJECTED, "rejected"
    else:
        return {"success": False, "error": "Invalid action"}

    transition = db.execute(
        update(Offer).where(
            Offer.id == offer_id,
            Offer.tenant_id == tenant_id,
            Offer.status == OfferStatus.SENT,
        ).values(**values)
    )
    if transition.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail="Public resource not found")
    db.execute(
        update(Resume).where(
            Resume.id == resume_id, Resume.tenant_id == tenant_id
        ).values(status=resume_status)
    )
    revoke_public_tokens(db, tenant_id, "offer", offer_id)
    db.commit()
    return {"success": True, "action": action_name, "message": "Offer response recorded"}


def _confirm_offer_by_token_legacy(db: Session, token: str, action: str, reason: Optional[str] = None,
                           accepted_salary: Optional[float] = None, accepted_onboard_date: Optional[datetime] = None) -> Dict[str, Any]:
    offer = resolve_public_token(db, token, "offer").resource
    if not offer:
        return {"success": False, "error": "无效的确认链接"}
    
    if offer.status != OfferStatus.SENT:
        status_text = {
            OfferStatus.ACCEPTED: "已接受",
            OfferStatus.REJECTED: "已拒绝",
            OfferStatus.EXPIRED: "已过期",
            OfferStatus.WITHDRAWN: "已撤回",
            OfferStatus.DRAFT: "未发送",
            OfferStatus.PENDING: "待发送"
        }.get(offer.status, "未知状态")
        return {"success": False, "error": f"Offer当前状态为：{status_text}"}
    
    if offer.valid_until and datetime.utcnow() > offer.valid_until:
        offer.status = OfferStatus.EXPIRED
        db.commit()
        return {"success": False, "error": "Offer已过期"}
    
    if action == "accept":
        offer.status = OfferStatus.ACCEPTED
        offer.accepted_at = datetime.utcnow()
        if accepted_salary:
            offer.salary_monthly = accepted_salary
        if accepted_onboard_date:
            offer.onboard_date = accepted_onboard_date
        
        resume = db.query(Resume).filter(Resume.id == offer.resume_id).first()
        if resume:
            resume.status = ResumeStatus.OFFER_ACCEPTED
        
        db.commit()
        return {"success": True, "action": "accepted", "message": "您已成功接受Offer！"}
    
    elif action == "reject":
        offer.status = OfferStatus.REJECTED
        offer.rejected_at = datetime.utcnow()
        if reason:
            offer.rejected_reason = reason
        
        resume = db.query(Resume).filter(Resume.id == offer.resume_id).first()
        if resume:
            resume.status = ResumeStatus.OFFER_REJECTED
        
        db.commit()
        return {"success": True, "action": "rejected", "message": "您已拒绝此Offer。"}
    
    else:
        return {"success": False, "error": "无效的操作"}
