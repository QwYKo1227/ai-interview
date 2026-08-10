from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.tenant_dependencies import get_tenant_db
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    WorkflowExecutionCreate, WorkflowExecutionResponse
)
from app.services.workflow_service import WorkflowEngine, create_builtin_workflows
from app.models.workflow_models import WorkflowStatus
from app.models.models import User, UserRole
from app.core.security import check_roles
from app.routes.auth import get_current_user
from app.services.recruitment_access import require_position_access, require_resume_access
from app.services.workflow_access import (
    list_accessible_executions,
    require_execution_access,
)
from typing import List, Optional
from uuid import UUID

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"]
)


@router.get("", response_model=List[WorkflowResponse])
def list_workflows(
    skip: int = 0,
    limit: int = 100,
    status: Optional[WorkflowStatus] = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    engine = WorkflowEngine(db)
    return engine.get_workflows(skip=skip, limit=limit, status=status)


@router.post("", response_model=WorkflowResponse)
def create_workflow(
    workflow_data: WorkflowCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    engine = WorkflowEngine(db)
    return engine.create_workflow(workflow_data.dict(), current_user.id)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    engine = WorkflowEngine(db)
    workflow = engine.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    update_data: WorkflowUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    engine = WorkflowEngine(db)
    workflow = engine.update_workflow(workflow_id, update_data.dict(exclude_unset=True))
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN]))
):
    engine = WorkflowEngine(db)
    try:
        success = engine.delete_workflow(workflow_id)
        if not success:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"message": "Workflow deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/publish", response_model=WorkflowResponse)
def publish_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    engine = WorkflowEngine(db)
    workflow = engine.publish_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("/{workflow_id}/execute", response_model=WorkflowExecutionResponse)
def execute_workflow(
    workflow_id: UUID,
    execution_data: WorkflowExecutionCreate = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    engine = WorkflowEngine(db)
    if not engine.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    input_data = execution_data.input_data if execution_data else None
    if input_data:
        if input_data.get("resume_id"):
            require_resume_access(db, UUID(str(input_data["resume_id"])), current_user, manage=True)
        if input_data.get("position_id"):
            require_position_access(db, UUID(str(input_data["position_id"])), current_user)
    try:
        execution = engine.execute_workflow(
            workflow_id=workflow_id,
            input_data=input_data,
            user_id=current_user.id
        )
        db.refresh(execution)
        return engine.get_execution(execution.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workflow_id}/executions", response_model=List[WorkflowExecutionResponse])
def list_executions(
    workflow_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    engine = WorkflowEngine(db)
    if not engine.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return list_accessible_executions(
        db,
        workflow_id=workflow_id,
        current_user=current_user,
        skip=skip,
        limit=limit,
    )


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionResponse)
def get_execution(
    execution_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    engine = WorkflowEngine(db)
    execution = engine.get_execution(execution_id)
    return require_execution_access(db, execution, current_user)


@router.post("/init-builtin")
def init_builtin_workflows(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN]))
):
    create_builtin_workflows(db)
    return {"message": "Builtin workflows initialized"}
