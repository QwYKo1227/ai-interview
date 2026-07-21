import enum
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, JSON, String, event, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declared_attr, validates

from app.models.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


TENANT_CODE_PATTERN = re.compile(r"^[a-z0-9-]+$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(
        Enum(
            TenantStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=TenantStatus.ACTIVE,
    )
    logo_url = Column(String)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @validates("code")
    def validate_code(self, key, value):
        if not isinstance(value, str) or not TENANT_CODE_PATTERN.fullmatch(value):
            raise ValueError("tenant code must contain only lowercase letters, digits, and hyphens")
        return value


@event.listens_for(Tenant, "before_update")
def prevent_tenant_code_change(mapper, connection, target):
    if inspect(target).attrs.code.history.has_changes():
        raise ValueError("tenant code cannot be changed after creation")


class TenantScopedMixin:
    @declared_attr
    def tenant_id(cls):
        return Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)


class TenantDomain(Base):
    __tablename__ = "tenant_domains"
    __table_args__ = (
        Index(
            "uq_tenant_domains_primary_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    domain = Column(String(255), nullable=False, unique=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    @validates("domain")
    def normalize_domain(self, key, value):
        return value.strip().lower().split(":", 1)[0]


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PlatformAuditLog(Base):
    __tablename__ = "platform_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=True, index=True)
    action = Column(String(128), nullable=False)
    target_tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PublicAccessToken(Base):
    __tablename__ = "public_access_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime, default=utcnow, nullable=False)

    @validates("token_hash")
    def validate_token_hash(self, key, value):
        if not isinstance(value, str) or not SHA256_HEX_PATTERN.fullmatch(value):
            raise ValueError("token_hash must be a lowercase SHA-256 hexadecimal digest")
        return value
