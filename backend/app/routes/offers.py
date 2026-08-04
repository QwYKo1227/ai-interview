from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.core.tenant_dependencies import get_tenant_db
from app.schemas.offer import (
    OfferCreate, OfferUpdate, OfferResponse, OfferListResponse,
    OfferStats,
    OfferDecisionRequest
)
from app.services import offer_service
from app.core.security import check_roles
from app.models.models import User, UserRole

router = APIRouter(
    prefix="/offers",
    tags=["offers"],
    responses={404: {"description": "Not found"}},
)

def _require_offer(db: Session, offer_id: UUID) -> None:
    if offer_service.get_offer(db, offer_id) is None:
        raise HTTPException(status_code=404, detail="Offer不存在")

@router.post("", response_model=OfferResponse)
def create_offer(
    offer_data: OfferCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    try:
        offer = offer_service.create_offer(db, offer_data, current_user.id)
        return offer_service.get_offer(db, offer.id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=OfferListResponse)
def list_offers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: Optional[str] = None,
    position_id: Optional[UUID] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    return offer_service.get_offers(
        db, page, page_size, status, position_id, search, current_user
    )

@router.get("/stats", response_model=OfferStats)
def get_offer_stats(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    return offer_service.get_offer_stats(db, current_user)


@router.get("/my-pending-count")
def get_my_pending_offer_count(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    return {"count": offer_service.get_my_pending_offer_count(db, current_user)}

@router.get("/{offer_id}", response_model=OfferResponse)
def get_offer(
    offer_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    offer = offer_service.get_offer(db, offer_id, current_user)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer不存在")
    return offer

@router.put("/{offer_id}", response_model=OfferResponse)
def update_offer(
    offer_id: UUID,
    offer_data: OfferUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    try:
        offer = offer_service.update_offer(db, offer_id, offer_data)
        if not offer:
            raise HTTPException(status_code=404, detail="Offer不存在")
        return offer_service.get_offer(db, offer.id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{offer_id}/send")
def send_offer(
    offer_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    _require_offer(db, offer_id)
    try:
        result = offer_service.send_offer(db, offer_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{offer_id}/decision")
def record_offer_decision(
    offer_id: UUID,
    request: OfferDecisionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    try:
        offer = offer_service.record_offer_decision(
            db,
            offer_id,
            current_user,
            request.decision,
            request.rejection_reason,
            request.rejection_detail,
            request.correction_reason,
        )
        return {
            "success": True,
            "status": offer.status.value,
            "offer_id": str(offer.id),
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{offer_id}/decision-audits")
def list_offer_decision_audits(
    offer_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]))
):
    if offer_service.get_offer(db, offer_id, current_user) is None:
        raise HTTPException(status_code=404, detail="Offer不存在")
    return offer_service.get_offer_decision_audits(db, offer_id)

@router.post("/{offer_id}/withdraw")
def withdraw_offer(
    offer_id: UUID,
    reason: Optional[str] = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    _require_offer(db, offer_id)
    try:
        offer = offer_service.withdraw_offer(db, offer_id, reason)
        return {"success": True, "message": "Offer已撤回", "offer_id": str(offer.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{offer_id}/reopen")
def reopen_offer(
    offer_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    _require_offer(db, offer_id)
    try:
        offer = offer_service.reopen_offer(db, offer_id)
        return {"success": True, "message": "Offer已重新打开", "offer_id": str(offer.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{offer_id}")
def delete_offer(
    offer_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    from app.models.models import Offer, OfferStatus
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer不存在")
    
    if offer.status not in [OfferStatus.DRAFT, OfferStatus.WITHDRAWN]:
        raise HTTPException(status_code=400, detail="只能删除草稿或已撤回的Offer")
    
    db.delete(offer)
    db.commit()
    return {"success": True, "message": "Offer已删除"}

public_router = APIRouter(
    prefix="/public/offers",
    tags=["public-offers"],
)

@public_router.get("/confirm/{token}")
def get_offer_by_token(
    token: str,
):
    raise HTTPException(status_code=410, detail="候选人Offer确认入口已停用")

@public_router.post("/confirm/{token}")
def confirm_offer_by_token(
    token: str,
):
    raise HTTPException(status_code=410, detail="候选人Offer确认入口已停用")
