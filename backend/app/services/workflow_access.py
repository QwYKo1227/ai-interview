"""Authorization and scoped pagination for workflow executions."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models.models import User
from app.models.workflow_models import WorkflowExecution
from app.services.recruitment_access import (
    is_admin,
    require_position_access,
    require_resume_access,
)


def can_access_execution(
    db: Session,
    execution: WorkflowExecution,
    current_user: User,
) -> bool:
    if is_admin(current_user):
        return True

    data = execution.input_data or {}
    has_linked_resource = False
    try:
        resume_id = data.get("resume_id")
        if resume_id:
            has_linked_resource = True
            require_resume_access(
                db,
                UUID(str(resume_id)),
                current_user,
                manage=True,
            )

        position_id = data.get("position_id")
        if position_id:
            has_linked_resource = True
            require_position_access(db, UUID(str(position_id)), current_user)
    except (HTTPException, TypeError, ValueError):
        return False

    if has_linked_resource:
        return True
    return execution.triggered_by == current_user.id


def require_execution_access(
    db: Session,
    execution: WorkflowExecution | None,
    current_user: User,
) -> WorkflowExecution:
    if execution is None or not can_access_execution(db, execution, current_user):
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


def list_accessible_executions(
    db: Session,
    *,
    workflow_id: UUID,
    current_user: User,
    skip: int,
    limit: int,
    batch_size: int = 200,
):
    query = (
        db.query(WorkflowExecution)
        .options(joinedload(WorkflowExecution.node_executions))
        .filter(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.created_at.desc())
    )
    if is_admin(current_user):
        return query.offset(skip).limit(limit).all()

    visible_seen = 0
    result = []
    offset = 0
    while len(result) < limit:
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        offset += len(batch)
        for execution in batch:
            if not can_access_execution(db, execution, current_user):
                continue
            if visible_seen < skip:
                visible_seen += 1
                continue
            result.append(execution)
            if len(result) == limit:
                break
    return result
