from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import check_roles
from app.core.tenant_dependencies import get_tenant_db
from app.models.models import RecruitmentHcSlot, RecruitmentPause, User, UserRole
from app.schemas.recruitment_performance import (
    PauseDecision,
    PauseRequest,
    PerformanceConfigPayload,
    PerformanceConfigResponse,
    PerformanceLeaderboard,
    PerformanceOverview,
    PerformancePeriodOptions,
    SettlementRequest,
)
from app.services.recruitment_leaderboard_service import calculate_leaderboard
from app.services.recruitment_performance_service import (
    available_periods,
    calculate_overview,
    current_period,
    get_config,
    publish_config,
    settle_period,
)


router = APIRouter(prefix="/recruitment-performance", tags=["recruitment-performance"])


@router.get("/periods", response_model=PerformancePeriodOptions)
def periods(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    return available_periods(db)


@router.get("/overview", response_model=PerformanceOverview)
def overview(
    period: str = Query(default_factory=current_period),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    return calculate_overview(db, period)


@router.get("/me", response_model=PerformanceOverview)
def my_performance(
    period: str = Query(default_factory=current_period),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    return calculate_overview(db, period, user=current_user)


@router.get("/leaderboard", response_model=PerformanceLeaderboard)
def leaderboard(
    period: str = Query(default_factory=current_period),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    return calculate_leaderboard(db, period, current_user=current_user)


@router.get("/people/{user_id}", response_model=PerformanceOverview)
def person_detail(
    user_id: UUID,
    period: str = Query(default_factory=current_period),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    person = db.query(User).filter(User.id == user_id).first()
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    return calculate_overview(db, period, user=person)


@router.get("/config", response_model=PerformanceConfigResponse)
def read_config(
    period: str = Query(default_factory=current_period),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    return get_config(db, period)


@router.put("/config", response_model=PerformanceConfigResponse)
def write_config(
    payload: PerformanceConfigPayload,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    return publish_config(db, current_user, payload)


@router.post("/settlements/{period}", response_model=PerformanceOverview)
def settle(
    period: str,
    payload: SettlementRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    return settle_period(db, current_user, period, payload.reason)


@router.post("/slots/{slot_id}/pause-requests")
def request_pause(
    slot_id: UUID,
    payload: PauseRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.HR, UserRole.ADMIN])),
):
    slot = db.query(RecruitmentHcSlot).filter(RecruitmentHcSlot.id == slot_id).first()
    if slot is None:
        raise HTTPException(status_code=404, detail="HC名额不存在")
    if current_user.role == UserRole.HR and slot.position.hiring_manager_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能申请暂停自己负责的HC")
    pause = RecruitmentPause(
        tenant_id=current_user.tenant_id,
        slot_id=slot.id,
        requested_by=current_user.id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        reason=payload.reason,
    )
    db.add(pause)
    db.commit()
    return {"id": pause.id, "status": pause.status}


@router.get("/pause-requests")
def list_pause_requests(
    status: str = "pending",
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    rows = db.query(RecruitmentPause).filter(RecruitmentPause.status == status).order_by(RecruitmentPause.created_at).all()
    return [{
        "id": row.id,
        "slot_id": row.slot_id,
        "position_title": row.slot.position.title if getattr(row, "slot", None) else None,
        "start_at": row.start_at,
        "end_at": row.end_at,
        "reason": row.reason,
        "status": row.status,
    } for row in rows]


@router.post("/pause-requests/{pause_id}/decision")
def decide_pause(
    pause_id: UUID,
    payload: PauseDecision,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    pause = db.query(RecruitmentPause).filter(RecruitmentPause.id == pause_id).first()
    if pause is None:
        raise HTTPException(status_code=404, detail="暂停申请不存在")
    if pause.status != "pending":
        raise HTTPException(status_code=409, detail="该申请已经处理")
    pause.status = "approved" if payload.approve else "rejected"
    pause.approved_by = current_user.id
    pause.decided_at = datetime.now(timezone.utc)
    if payload.end_at is not None:
        pause.end_at = payload.end_at
    if payload.reason:
        pause.reason = f"{pause.reason}\n审批说明：{payload.reason}"
    db.commit()
    return {"id": pause.id, "status": pause.status}
