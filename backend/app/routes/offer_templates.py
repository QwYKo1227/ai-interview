from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.core.tenant_dependencies import get_tenant_db
from app.schemas.offer_template import (
    OfferTemplateCreate, OfferTemplateUpdate, OfferTemplateResponse, OfferTemplateListResponse
)
from app.services import offer_template_service
from app.core.security import check_roles
from app.models.models import OfferTemplate, User, UserRole
from app.services.recruitment_access import require_position_access

router = APIRouter(
    prefix="/offer-templates",
    tags=["offer-templates"],
    responses={404: {"description": "Not found"}},
)

@router.post("", response_model=OfferTemplateResponse)
def create_template(
    template_data: OfferTemplateCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    if template_data.position_id is not None:
        require_position_access(db, template_data.position_id, current_user)
    template = offer_template_service.create_template(db, template_data, current_user.id)
    return offer_template_service.get_template(db, template.id)

@router.get("", response_model=OfferTemplateListResponse)
def list_templates(
    position_id: Optional[UUID] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    if position_id is not None:
        require_position_access(db, position_id, current_user)
    items = offer_template_service.get_templates(
        db, position_id, include_inactive, current_user
    )
    return {"items": items, "total": len(items)}

@router.get("/default/{position_id}", response_model=OfferTemplateResponse)
def get_default_template(
    position_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_position_access(db, position_id, current_user)
    template = offer_template_service.get_default_template_for_position(db, position_id)
    if not template:
        raise HTTPException(status_code=404, detail="未找到默认模板")
    return template

@router.get("/{template_id}", response_model=OfferTemplateResponse)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    stored = db.query(OfferTemplate).filter(OfferTemplate.id == template_id).first()
    if stored is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if stored.position_id is not None:
        require_position_access(db, stored.position_id, current_user)
    template = offer_template_service.get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template

@router.put("/{template_id}", response_model=OfferTemplateResponse)
def update_template(
    template_id: UUID,
    template_data: OfferTemplateUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    stored = db.query(OfferTemplate).filter(OfferTemplate.id == template_id).first()
    if stored is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if stored.position_id is not None:
        require_position_access(db, stored.position_id, current_user)
    if template_data.position_id is not None:
        require_position_access(db, template_data.position_id, current_user)
    template = offer_template_service.update_template(db, template_id, template_data)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return offer_template_service.get_template(db, template.id)

@router.delete("/{template_id}")
def delete_template(
    template_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    stored = db.query(OfferTemplate).filter(OfferTemplate.id == template_id).first()
    if stored is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if stored.position_id is not None:
        require_position_access(db, stored.position_id, current_user)
    success = offer_template_service.delete_template(db, template_id)
    if not success:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"success": True, "message": "模板已删除"}
