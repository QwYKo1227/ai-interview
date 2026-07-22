"""Opaque public links backed by one-way token digests."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config.tenant_session import get_tenant_id, set_tenant_context
from app.models.tenant_models import PublicAccessToken, Tenant, TenantDomain, TenantStatus


PUBLIC_NOT_FOUND = "Public resource not found"
SUPPORTED_RESOURCE_TYPES = frozenset({"offer", "coding_test", "department_review", "stored_file"})
RAW_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")


@dataclass(frozen=True)
class TenantContextAndResource:
    tenant_id: UUID
    resource_type: str
    resource_id: UUID
    resource: Any


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _resource_model(resource_type: str):
    from app.models.models import CodingTest, DepartmentReview, Offer
    from app.models.file_models import StoredFile

    return {
        "offer": Offer,
        "coding_test": CodingTest,
        "department_review": DepartmentReview,
        "stored_file": StoredFile,
    }[resource_type]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PUBLIC_NOT_FOUND)


def _aware_utc(value: datetime) -> datetime:
    # SQLite drops timezone offsets even for DateTime(timezone=True).
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def issue_public_token(
    db: Session,
    tenant_id: UUID,
    resource_type: str,
    resource_id: UUID,
    expires_at: datetime,
) -> str:
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise ValueError("unsupported public resource type")
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")

    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.status == TenantStatus.ACTIVE)
        .first()
    )
    if tenant is None:
        raise _not_found()

    model = _resource_model(resource_type)
    resource = (
        db.query(model)
        .filter(model.id == resource_id, model.tenant_id == tenant_id)
        .first()
    )
    if resource is None:
        raise _not_found()

    revoke_public_tokens(db, tenant_id, resource_type, resource_id)
    raw_token = secrets.token_urlsafe(32)
    record = PublicAccessToken(
        token_hash=hash_token(raw_token),
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    return raw_token


def revoke_public_tokens(
    db: Session, tenant_id: UUID, resource_type: str, resource_id: UUID
) -> int:
    return db.query(PublicAccessToken).filter(
        PublicAccessToken.tenant_id == tenant_id,
        PublicAccessToken.resource_type == resource_type,
        PublicAccessToken.resource_id == resource_id,
        PublicAccessToken.revoked_at.is_(None),
    ).update(
        {PublicAccessToken.revoked_at: datetime.now(timezone.utc)},
        synchronize_session="fetch",
    )


def resolve_public_token(
    db: Session,
    raw_token: str,
    resource_type: str,
) -> TenantContextAndResource:
    if (
        resource_type not in SUPPORTED_RESOURCE_TYPES
        or not isinstance(raw_token, str)
        or RAW_TOKEN_PATTERN.fullmatch(raw_token) is None
    ):
        raise _not_found()
    digest = hash_token(raw_token)
    record = (
        db.query(PublicAccessToken)
        .filter(PublicAccessToken.token_hash == digest)
        .first()
    )
    if (
        record is None
        or not hmac.compare_digest(record.token_hash, digest)
        or record.resource_type != resource_type
        or record.revoked_at is not None
    ):
        raise _not_found()
    if _aware_utc(record.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Public link expired",
        )

    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == record.tenant_id, Tenant.status == TenantStatus.ACTIVE)
        .first()
    )
    if tenant is None:
        raise _not_found()

    try:
        bound_tenant = get_tenant_id(db)
    except RuntimeError:
        set_tenant_context(db, record.tenant_id)
    else:
        if bound_tenant != record.tenant_id:
            raise _not_found()

    model = _resource_model(resource_type)
    resource = db.query(model).filter(model.id == record.resource_id).first()
    if resource is None:
        raise _not_found()
    return TenantContextAndResource(
        tenant_id=record.tenant_id,
        resource_type=resource_type,
        resource_id=record.resource_id,
        resource=resource,
    )


def enforce_public_request_tenant(
    db: Session,
    *,
    request_host: str,
    tenant_id: UUID,
    tenant_code: str | None = None,
) -> None:
    """Reject contradictory trusted tenant selectors; unknown hosts are gateways."""

    hostname = request_host.strip().lower().partition(":")[0]
    domain = None
    if hostname:
        domain = db.query(TenantDomain).filter(TenantDomain.domain == hostname).first()
    if domain is not None and domain.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Public link tenant mismatch")
    if tenant_code is not None:
        tenant = (
            db.query(Tenant)
            .filter(
                Tenant.id == tenant_id,
                Tenant.code == tenant_code,
                Tenant.status == TenantStatus.ACTIVE,
            )
            .first()
        )
        if tenant is None:
            raise HTTPException(status_code=403, detail="Public link tenant mismatch")


def resolve_public_tenant(
    db: Session,
    *,
    request_host: str,
    tenant_code: str | None = None,
) -> UUID:
    """Resolve an active tenant from URL code and/or a registered host."""
    hostname = request_host.strip().lower().partition(":")[0]
    domain = db.query(TenantDomain).filter(TenantDomain.domain == hostname).first() if hostname else None
    coded_tenant = None
    if tenant_code:
        coded_tenant = db.query(Tenant).filter(
            Tenant.code == tenant_code, Tenant.status == TenantStatus.ACTIVE
        ).first()
        if coded_tenant is None:
            raise _not_found()
    if domain is not None and coded_tenant is not None and domain.tenant_id != coded_tenant.id:
        raise HTTPException(status_code=403, detail="Public tenant mismatch")
    tenant_id = coded_tenant.id if coded_tenant is not None else (domain.tenant_id if domain else None)
    if tenant_id is None:
        raise _not_found()
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.status == TenantStatus.ACTIVE
    ).first()
    if tenant is None:
        raise _not_found()
    set_tenant_context(db, tenant.id)
    return tenant.id
