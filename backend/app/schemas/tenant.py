from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.tenant_models import TenantStatus


class TenantSummary(BaseModel):
    id: UUID
    code: str
    name: str
    logo_url: Optional[str] = None
    primary_domain: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TenantCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    name: str = Field(max_length=255)
    logo_url: Optional[str] = None


class TenantResponse(TenantSummary):
    status: TenantStatus
    created_at: datetime
    updated_at: datetime
