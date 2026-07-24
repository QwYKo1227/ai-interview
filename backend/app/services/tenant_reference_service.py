from typing import Type, TypeVar
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


def require_tenant_entity(
    db: Session,
    model: Type[ModelT],
    entity_id: UUID,
    detail: str,
) -> ModelT:
    entity = db.query(model).filter(model.id == entity_id).first()
    if entity is None:
        raise HTTPException(status_code=404, detail=detail)
    return entity
