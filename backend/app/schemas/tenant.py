from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.tenant_models import TenantDomain, TenantStatus


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


class TenantDomainCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    is_primary: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return TenantDomain(domain=value, tenant_id=UUID(int=0)).domain


class TenantDomainUpdate(BaseModel):
    domain: Optional[str] = Field(default=None, min_length=1, max_length=253)
    is_primary: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return TenantDomain(domain=value, tenant_id=UUID(int=0)).domain


class TenantDomainResponse(BaseModel):
    id: UUID
    domain: str
    is_primary: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantDetailResponse(TenantResponse):
    domains: list[TenantDomainResponse]


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


class TenantOnboardingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    primary_domain: str = Field(min_length=1, max_length=253)
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

    @field_validator("primary_domain", mode="before")
    @classmethod
    def normalize_domain(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("primary_domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        # Reuse the model's authoritative hostname normalization and validation.
        return TenantDomain(domain=value, tenant_id=UUID(int=0)).domain

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
        password_bytes = len(value.encode("utf-8"))
        if password_bytes < 12:
            raise ValueError("密码必须至少为 12 个 UTF-8 字节")
        if password_bytes > 72:
            raise ValueError("密码最多为 72 个 UTF-8 字节")
        if not any(character.isalpha() for character in value):
            raise ValueError("password must include a letter")
        if not any(character.isdigit() for character in value):
            raise ValueError("password must include a digit")
        return value
