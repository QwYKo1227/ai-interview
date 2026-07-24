from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.config.database import get_unscoped_db
from app.core.tenant_dependencies import get_tenant_db
from app.schemas.position import (
    PositionCreate, PositionUpdate, PositionResponse,
    PositionWithStats, PositionStats, JDGenerateRequest,
    JDGenerateResponse, PositionDetailResponse, QuestionBankBrief,
    JDChatRequest, HiringManagerOption
)
from app.services.position_service import (
    create_position, get_positions, get_positions_with_stats,
    get_position, update_position, delete_position,
    get_position_stats, get_linked_question_banks, generate_position_jd,
    get_hiring_managers, get_position_departments
)
from app.services.ai_service import generate_jd_stream, chat_jd_stream
from app.models.models import PositionUrgency, User, UserRole
from app.core.security import check_roles
from app.routes.auth import get_current_user
from app.services.public_token_service import resolve_public_tenant
from app.core.proxy import resolve_request_host
from typing import List
from uuid import UUID

router = APIRouter(
    prefix="/positions",
    tags=["positions"]
)

@router.post("", response_model=PositionResponse)
def create_position_route(
    position: PositionCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    return create_position(db, position)

@router.get("", response_model=List[PositionWithStats])
def get_positions_route(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: UUID = None,
    department: str = None,
    urgency: PositionUrgency = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    return get_positions_with_stats(
        db,
        skip=skip,
        limit=limit,
        status=status,
        title=title,
        hiring_manager_id=hiring_manager_id,
        department=department,
        urgency=urgency,
    )


@router.get("/hiring-managers", response_model=List[HiringManagerOption])
def get_hiring_managers_route(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    return get_hiring_managers(db)


@router.get("/departments", response_model=List[str])
def get_position_departments_route(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    return get_position_departments(db)

@router.get("/public", response_model=List[PositionResponse])
def get_public_positions_route(
    request: Request,
    tenant_code: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_unscoped_db),
):
    resolve_public_tenant(
        db, request_host=resolve_request_host(request), tenant_code=tenant_code
    )
    return get_positions(db, skip=skip, limit=limit, status="published")

@router.post("/generate-jd", response_model=JDGenerateResponse)
def generate_jd_route(
    request: JDGenerateRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    result = generate_position_jd(
        db=db,
        title=request.title,
        department=request.department,
        location=request.location,
        salary_range=request.salary_range,
        keywords=request.keywords
    )
    return JDGenerateResponse(**result)

@router.post("/generate-jd-stream")
def generate_jd_stream_route(
    request: JDGenerateRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    return StreamingResponse(
        generate_jd_stream(
            title=request.title,
            department=request.department,
            location=request.location,
            salary_range=request.salary_range,
            keywords=request.keywords,
            db=db,
        ),
        media_type="text/event-stream"
    )

@router.post("/chat-jd-stream")
def chat_jd_stream_route(
    request: JDChatRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    return StreamingResponse(
        chat_jd_stream(
            messages=request.messages,
            current_description=request.current_description,
            current_requirements=request.current_requirements,
            db=db,
        ),
        media_type="text/event-stream"
    )

@router.get("/{position_id}", response_model=PositionDetailResponse)
def get_position_route(
    position_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    position = get_position(db, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    stats = get_position_stats(db, position_id)
    linked_banks = get_linked_question_banks(db, position_id)

    hiring_manager_name = None
    if position.hiring_manager_id:
        from app.models.models import User
        user = db.query(User).filter(User.id == position.hiring_manager_id).first()
        if user:
            hiring_manager_name = user.full_name

    return PositionDetailResponse(
        **{c.name: getattr(position, c.name) for c in position.__table__.columns},
        stats=stats.model_dump(),
        hiring_manager_name=hiring_manager_name,
        linked_question_banks=[b.model_dump() for b in linked_banks]
    )

@router.get("/{position_id}/stats", response_model=PositionStats)
def get_position_stats_route(
    position_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    position = get_position(db, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return get_position_stats(db, position_id)

@router.get("/{position_id}/question-banks", response_model=List[QuestionBankBrief])
def get_position_question_banks_route(
    position_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    position = get_position(db, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return get_linked_question_banks(db, position_id)

@router.put("/{position_id}", response_model=PositionResponse)
def update_position_route(
    position_id: UUID,
    position: PositionUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    db_position = update_position(db, position_id, position)
    if not db_position:
        raise HTTPException(status_code=404, detail="Position not found")
    return db_position

@router.delete("/{position_id}", response_model=PositionResponse)
def delete_position_route(
    position_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    db_position = delete_position(db, position_id)
    if not db_position:
        raise HTTPException(status_code=404, detail="Position not found")
    return db_position
public_router = APIRouter(prefix="/public", tags=["public-positions"])


def _public_positions(db: Session, request: Request, tenant_code: str | None, skip: int, limit: int):
    resolve_public_tenant(
        db, request_host=resolve_request_host(request), tenant_code=tenant_code
    )
    return get_positions(db, skip=skip, limit=limit, status="published")


@public_router.get("/positions", response_model=List[PositionResponse])
def get_domain_public_positions(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_unscoped_db),
):
    return _public_positions(db, request, None, skip, limit)


@public_router.get("/positions/{position_id}", response_model=PositionResponse)
def get_domain_public_position(
    position_id: UUID,
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    resolve_public_tenant(db, request_host=resolve_request_host(request))
    position = get_position(db, position_id)
    if position is None or getattr(position.status, "value", position.status) != "published":
        raise HTTPException(status_code=404, detail="Public resource not found")
    return position


@public_router.get("/{tenant_code}/positions", response_model=List[PositionResponse])
def get_tenant_public_positions(
    tenant_code: str,
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_unscoped_db),
):
    return _public_positions(db, request, tenant_code, skip, limit)


@public_router.get("/{tenant_code}/positions/{position_id}", response_model=PositionResponse)
def get_tenant_public_position(
    tenant_code: str,
    position_id: UUID,
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    resolve_public_tenant(
        db, request_host=resolve_request_host(request), tenant_code=tenant_code
    )
    position = get_position(db, position_id)
    if position is None or getattr(position.status, "value", position.status) != "published":
        raise HTTPException(status_code=404, detail="Public resource not found")
    return position
