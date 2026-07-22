import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base
from app.models.tenant_models import TenantScopedMixin, utcnow


class StoredFile(TenantScopedMixin, Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        Index("ix_stored_files_tenant_resource", "tenant_id", "resource_type", "resource_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    object_key = Column(String(512), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(255))
    size = Column(BigInteger, nullable=False)
    category = Column(String(64), nullable=False)
    resource_type = Column(String(64), index=True)
    resource_id = Column(UUID(as_uuid=True), index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
