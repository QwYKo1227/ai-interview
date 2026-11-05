from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import check_roles
from app.core.tenant_dependencies import get_tenant_db
from app.models.models import User, UserRole
from app.schemas.recruitment_quality import ActionRequest, PolicyRequest
from app.services import recruitment_quality_service as service

router = APIRouter(prefix="/recruitment-quality", tags=["recruitment-quality"])
members = check_roles([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER])


@router.get("/overview")
def overview(
    cohort: Literal["all", "new", "historical"] = "all",
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_tenant_db), user: User = Depends(members),
):
    return service.overview(db, user, cohort=cohort, start_date=start_date, end_date=end_date)


@router.get("/config")
def config(db: Session = Depends(get_tenant_db), user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))):
    return service.config_response(db, user)


@router.get("/summary")
def summary(db: Session = Depends(get_tenant_db), user: User = Depends(members)):
    report = service.overview(db, user, cohort="all")
    return {**report["summary"], "attention_count": sum(
        n["overdue"] or n["status"] in {"missing", "waived"} for n in report["nodes"]
    )}


@router.post("/policies")
def publish(payload: PolicyRequest, db: Session = Depends(get_tenant_db), user: User = Depends(check_roles([UserRole.ADMIN]))):
    return service.publish_policy(db, user, payload)


@router.post("/bindings/{binding_id}/nodes/{node_key}/actions")
def action(binding_id: UUID, node_key: str, payload: ActionRequest,
           db: Session = Depends(get_tenant_db), user: User = Depends(members)):
    return service.record_action(db, user, binding_id, node_key, payload)
