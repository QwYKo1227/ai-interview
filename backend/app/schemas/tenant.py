from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.password_policy import validate_password_policy
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


class TenantAdminResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TenantDetailResponse(TenantResponse):
    admins: list[TenantAdminResponse]


class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    model_config = ConfigDict(extra="forbid")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class TenantStatusUpdate(BaseModel):
    status: TenantStatus

    model_config = ConfigDict(extra="forbid")


class TenantAdminPasswordResetRequest(BaseModel):
    new_password: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_policy(value)


class TenantOnboardingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr
    admin_password: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("admin_email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        normalized = str(value).strip().lower()
        if len(normalized) > 255:
            raise ValueError("email must be at most 255 characters")
        return normalized

    @field_validator("admin_password")
    @classmethod
    def validate_admin_password(cls, value: str) -> str:
        return validate_password_policy(value)
