from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError, StatementError

from app.models.base import Base
from app.models.tenant_models import (
    PlatformAuditLog,
    PlatformUser,
    PublicAccessToken,
    Tenant,
    TenantDomain,
    TenantScopedMixin,
    TenantStatus,
)
from app.schemas.tenant import TenantCreate, TenantResponse, TenantSummary


def test_tenant_code_is_unique(db):
    db.add(Tenant(code="careray", name="CareRay", status=TenantStatus.ACTIVE))
    db.commit()

    db.add(Tenant(code="careray", name="Duplicate", status=TenantStatus.ACTIVE))
    with pytest.raises(IntegrityError):
        db.commit()


def test_tenant_code_accepts_only_lowercase_letters_digits_and_hyphens():
    with pytest.raises(ValueError):
        Tenant(code="Care_Ray", name="CareRay", status=TenantStatus.ACTIVE)

    with pytest.raises(ValidationError):
        TenantCreate(code="Care_Ray", name="CareRay")


def test_tenant_code_length_is_limited_in_schema_and_orm():
    valid_code = "a" * 64
    assert TenantCreate(code=valid_code, name="CareRay").code == valid_code
    assert Tenant(code=valid_code, name="CareRay").code == valid_code

    with pytest.raises(ValidationError):
        TenantCreate(code="a" * 65, name="CareRay")
    with pytest.raises(ValueError):
        Tenant(code="a" * 65, name="CareRay")


def test_tenant_name_length_is_limited_in_schema_and_orm():
    valid_name = "n" * 255
    assert TenantCreate(code="careray", name=valid_name).name == valid_name
    assert Tenant(code="careray", name=valid_name).name == valid_name

    with pytest.raises(ValidationError):
        TenantCreate(code="careray", name="n" * 256)
    with pytest.raises(ValueError):
        Tenant(code="careray", name="n" * 256)


def test_tenant_code_cannot_be_changed_after_creation(db):
    tenant = Tenant(code="careray", name="CareRay", status=TenantStatus.ACTIVE)
    db.add(tenant)
    db.commit()

    tenant.code = "photonthix"
    with pytest.raises(ValueError):
        db.commit()


def test_tenant_status_rejects_unknown_value(db):
    db.add(Tenant(code="careray", name="CareRay", status="unknown"))

    with pytest.raises(StatementError):
        db.commit()


def test_tenant_domain_is_globally_unique(db, tenant_a, tenant_b):
    db.add(TenantDomain(tenant_id=tenant_a.id, domain="interview.careray.com", is_primary=True))
    db.commit()

    db.add(TenantDomain(tenant_id=tenant_b.id, domain="interview.careray.com", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()


def test_tenant_domain_is_normalized_before_uniqueness_check(db, tenant_a, tenant_b):
    db.add(TenantDomain(tenant_id=tenant_a.id, domain="Interview.CareRay.com:443", is_primary=True))
    db.commit()

    db.add(TenantDomain(tenant_id=tenant_b.id, domain="interview.careray.com", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "invalid_domain",
    ["", "   ", "https://example.com", "example.com/path", "example..com", "bad_domain.example"],
)
def test_tenant_domain_rejects_non_host_values(invalid_domain):
    with pytest.raises(ValueError):
        TenantDomain(tenant_id=uuid4(), domain=invalid_domain, is_primary=True)


def test_tenant_has_at_most_one_primary_domain(db, tenant_a):
    db.add(TenantDomain(tenant_id=tenant_a.id, domain="interview.careray.com", is_primary=True))
    db.commit()

    db.add(TenantDomain(tenant_id=tenant_a.id, domain="jobs.careray.com", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()


def test_platform_user_is_separate_from_tenant_user(db):
    user = PlatformUser(
        email="platform-admin@example.com",
        hashed_password="hashed-password",
        full_name="Platform Admin",
    )
    db.add(user)
    db.commit()

    assert user.id is not None
    assert "tenant_id" not in PlatformUser.__table__.columns


def test_platform_audit_log_records_actor_and_target_tenant(db, tenant_a):
    actor = PlatformUser(email="platform-admin@example.com", hashed_password="hashed-password")
    db.add(actor)
    db.commit()

    entry = PlatformAuditLog(
        actor_id=actor.id,
        action="tenant.created",
        target_tenant_id=tenant_a.id,
    )
    db.add(entry)
    db.commit()

    assert entry.actor_id == actor.id
    assert entry.target_tenant_id == tenant_a.id


def test_public_access_token_stores_only_sha256_hash(db, tenant_a):
    raw_token = "a-secret-token"
    token = PublicAccessToken(
        token_hash="beef" * 16,
        tenant_id=tenant_a.id,
        resource_type="offer",
        resource_id=uuid4(),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    db.add(token)
    db.commit()

    assert token.token_hash != raw_token
    assert "token" not in PublicAccessToken.__table__.columns
    assert PublicAccessToken.__table__.c.token_hash.type.length == 64


def test_public_access_token_rejects_raw_or_non_sha256_hashes(tenant_a):
    with pytest.raises(ValueError):
        PublicAccessToken(
            token_hash="a-secret-token",
            tenant_id=tenant_a.id,
            resource_type="offer",
            resource_id=uuid4(),
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


def test_tenant_scoped_mixin_requires_tenant_id_after_final_migration():
    class TenantScopedRecord(TenantScopedMixin, Base):
        __tablename__ = "test_tenant_scoped_records"

        id = Column(Integer, primary_key=True)

    tenant_id = TenantScopedRecord.__table__.c.tenant_id

    assert isinstance(tenant_id.type, UUID)
    assert tenant_id.nullable is False
    assert tenant_id.index is True
    assert {foreign_key.target_fullname for foreign_key in tenant_id.foreign_keys} == {"tenants.id"}


def test_tenant_schemas_expose_summary_create_and_response():
    create = TenantCreate(code="careray", name="CareRay", logo_url="https://example.com/logo.png")
    summary = TenantSummary(
        id=uuid4(),
        code=create.code,
        name=create.name,
        logo_url=create.logo_url,
        primary_domain="interview.careray.com",
    )
    response = TenantResponse(
        id=summary.id,
        code=summary.code,
        name=summary.name,
        status=TenantStatus.ACTIVE,
        logo_url=summary.logo_url,
        primary_domain=summary.primary_domain,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    assert summary.code == "careray"
    assert summary.primary_domain == "interview.careray.com"
    assert response.status is TenantStatus.ACTIVE
