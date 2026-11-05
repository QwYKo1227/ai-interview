"""Versioned process rules, immutable application bindings and audit actions."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.tenant_models import TenantScopedMixin
from app.models.models import _tenant_identity, _tenant_reference, Resume, Position, Offer, Interview


def utcnow():
    return datetime.now(timezone.utc)


class QualityPolicy(TenantScopedMixin, Base):
    __tablename__ = "recruitment_quality_policies"
    __table_args__ = (
        _tenant_identity(__tablename__),
        _tenant_reference(__tablename__, "position_id", "positions"),
        _tenant_reference(__tablename__, "created_by", "users"),
        UniqueConstraint("tenant_id", "version", name="uq_quality_policy_version"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id = Column(UUID(as_uuid=True), nullable=True)
    version = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    rules = Column(JSON, nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityBinding(TenantScopedMixin, Base):
    __tablename__ = "recruitment_quality_bindings"
    __table_args__ = (
        _tenant_identity(__tablename__),
        _tenant_reference(__tablename__, "policy_id", "recruitment_quality_policies"),
        _tenant_reference(__tablename__, "position_id", "positions"),
        _tenant_reference(__tablename__, "resume_id", "resumes", ondelete="SET NULL", postgresql_set_null_columns=("resume_id",)),
        UniqueConstraint("tenant_id", "subject_key", name="uq_quality_binding_subject"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_key = Column(String(100), nullable=False)
    position_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    resume_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    policy_id = Column(UUID(as_uuid=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QualityAction(TenantScopedMixin, Base):
    __tablename__ = "recruitment_quality_actions"
    __table_args__ = (
        _tenant_identity(__tablename__),
        _tenant_reference(__tablename__, "binding_id", "recruitment_quality_bindings"),
        _tenant_reference(__tablename__, "actor_id", "users"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    binding_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    node_key = Column(String(120), nullable=False)
    kind = Column(String(30), nullable=False)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    reason = Column(Text, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def immutable(mapper, connection, target):
    raise ValueError("过程质量规则、绑定和审计记录不可改写，请追加新版本或事件")


for model in (QualityPolicy, QualityBinding, QualityAction):
    event.listen(model, "before_update", immutable)
    event.listen(model, "before_delete", immutable)


def retain_old_value(target, value, oldvalue, initiator):
    """Load expired values before assignment so audits retain the true transition."""
    return value


for attribute in (Resume.status, Resume.position_id, Position.hiring_manager_id, Offer.status, Offer.valid_until, Offer.onboard_date,
                  Interview.interview_time, Interview.interview_end_time):
    event.listen(attribute, "set", retain_old_value, active_history=True)


@event.listens_for(Session, "before_flush")
def enforce_quality_rules(session, flush_context, instances):
    # One guard for every ORM business entry point, including older update APIs.
    from app.services.recruitment_quality_service import guard_changes
    guard_changes(session)
