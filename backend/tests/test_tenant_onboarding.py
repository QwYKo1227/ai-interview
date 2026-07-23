from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.database import get_unscoped_db
from app.config.tenant_session import (
    TenantSession,
    get_tenant_id,
    set_tenant_context,
)
from app.core.security import create_access_token, get_password_hash
from app.models.models import SystemConfig, User, UserRole
from app.models.tenant_models import (
    PlatformAuditLog,
    PlatformUser,
    Tenant,
    TenantDomain,
)
from app.schemas.tenant import TenantOnboardingRequest
from app.services import tenant_service
from app.services.tenant_service import (
    TENANT_ACTOR_MESSAGE,
    TENANT_CONFLICT_MESSAGE,
    TENANT_ONBOARDING_MESSAGE,
    TenantActorError,
    TenantConflictError,
    TenantOnboardingError,
    create_tenant_with_admin,
)


@pytest.fixture
def platform_admin(db):
    actor = PlatformUser(
        id=uuid4(),
        email="platform-admin@example.com",
        hashed_password=get_password_hash("PlatformPassword123"),
        is_active=True,
    )
    db.add(actor)
    db.commit()
    db.refresh(actor)
    db.expunge(actor)
    db.rollback()
    return actor


def make_onboarding_request(**overrides):
    values = {
        "code": "careray-cloud",
        "name": "CareRay Cloud",
        "primary_domain": "interview.careray-cloud.example",
        "admin_email": "admin@careray-cloud.example",
        "admin_password": "StrongPassword123",
    }
    values.update(overrides)
    return TenantOnboardingRequest(**values)


def test_create_tenant_creates_defaults(db, platform_admin):
    tenant = create_tenant_with_admin(
        db,
        make_onboarding_request(),
        actor_id=platform_admin.id,
    )

    assert (
        db.query(TenantDomain)
        .filter_by(tenant_id=tenant.id, is_primary=True)
        .count()
        == 1
    )
    assert db.query(SystemConfig).filter_by(tenant_id=tenant.id).count() == 1
    assert (
        db.query(User)
        .filter_by(tenant_id=tenant.id, role=UserRole.ADMIN)
        .count()
        == 1
    )
    audit = db.query(PlatformAuditLog).one()
    assert audit.actor_id == platform_admin.id
    assert audit.action == "tenant.created"
    assert audit.target_tenant_id == tenant.id


def test_duplicate_code_rolls_back_all_rows(db, platform_admin):
    payload = make_onboarding_request(code="careray")
    create_tenant_with_admin(db, payload, actor_id=platform_admin.id)

    with pytest.raises(TenantConflictError):
        create_tenant_with_admin(db, payload, actor_id=platform_admin.id)

    assert db.query(Tenant).filter_by(code="careray").count() == 1
    assert db.query(TenantDomain).count() == 1
    assert db.query(SystemConfig).count() == 1
    assert db.query(User).count() == 1
    assert db.query(PlatformAuditLog).count() == 1


def test_onboarding_normalizes_code_domain_and_email(db, platform_admin):
    payload = make_onboarding_request(
        code="  Photon-Thix  ",
        primary_domain="  INTERVIEW.PHOTON-THIX.EXAMPLE  ",
        admin_email="  Admin@Photon-Thix.Example  ",
    )

    tenant = create_tenant_with_admin(db, payload, actor_id=platform_admin.id)

    assert tenant.code == "photon-thix"
    assert db.query(TenantDomain).one().domain == "interview.photon-thix.example"
    assert db.query(User).one().email == "admin@photon-thix.example"


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "invalid_code"},
        {"code": "x" * 65},
        {"primary_domain": "https://tenant.example/path"},
        {"primary_domain": f"{'x' * 64}.example"},
        {"admin_email": "not-an-email"},
        {"admin_email": f"{'x' * 250}@example.com"},
    ],
)
def test_onboarding_rejects_invalid_identifiers(overrides):
    with pytest.raises(ValidationError):
        make_onboarding_request(**overrides)


def test_onboarding_password_accepts_exactly_twelve_utf8_bytes():
    password = "密A1abcdefg"

    assert len(password) < 12
    assert len(password.encode("utf-8")) == 12
    assert make_onboarding_request(admin_password=password).admin_password == password


@pytest.mark.parametrize(
    "password",
    [
        "A1abcdefg",
        "A1" + "a" * 71,
    ],
)
def test_onboarding_password_rejects_values_outside_utf8_byte_range(password):
    with pytest.raises(ValidationError):
        make_onboarding_request(admin_password=password)


def test_duplicate_domain_returns_fixed_conflict_without_partial_rows(
    db, platform_admin
):
    existing = Tenant(code="existing", name="Existing")
    db.add(existing)
    db.flush()
    db.add(
        TenantDomain(
            tenant_id=existing.id,
            domain="interview.careray-cloud.example",
            is_primary=True,
        )
    )
    db.commit()

    with pytest.raises(TenantConflictError) as exc_info:
        create_tenant_with_admin(
            db,
            make_onboarding_request(code="new-code"),
            actor_id=platform_admin.id,
        )

    assert str(exc_info.value) == TENANT_CONFLICT_MESSAGE
    assert db.query(Tenant).count() == 1
    assert db.query(SystemConfig).count() == 0
    assert db.query(User).count() == 0
    assert db.query(PlatformAuditLog).count() == 0


def test_invalid_or_inactive_actor_cannot_create_any_rows(db, platform_admin):
    actor_id = platform_admin.id
    db.query(PlatformUser).filter(PlatformUser.id == actor_id).update(
        {PlatformUser.is_active: False}
    )
    db.commit()

    for invalid_actor_id in (actor_id, uuid4()):
        with pytest.raises(TenantActorError) as exc_info:
            create_tenant_with_admin(
                db,
                make_onboarding_request(code=f"tenant-{invalid_actor_id.hex[:8]}"),
                actor_id=invalid_actor_id,
            )
        assert str(exc_info.value) == TENANT_ACTOR_MESSAGE

    assert db.query(Tenant).count() == 0
    assert db.query(TenantDomain).count() == 0
    assert db.query(SystemConfig).count() == 0
    assert db.query(User).count() == 0
    assert db.query(PlatformAuditLog).count() == 0


def test_unexpected_failure_rolls_back_every_row_and_hides_internal_error(
    db, platform_admin, monkeypatch, caplog
):
    secret = "StrongPassword123-INTERNAL-DB-DETAIL"

    def fail_hash(_password):
        raise RuntimeError(secret)

    monkeypatch.setattr(tenant_service, "get_password_hash", fail_hash)

    with pytest.raises(TenantOnboardingError) as exc_info:
        create_tenant_with_admin(
            db,
            make_onboarding_request(),
            actor_id=platform_admin.id,
        )

    assert str(exc_info.value) == TENANT_ONBOARDING_MESSAGE
    assert secret not in str(exc_info.value)
    assert secret not in caplog.text
    assert db.query(Tenant).count() == 0
    assert db.query(TenantDomain).count() == 0
    assert db.query(SystemConfig).count() == 0
    assert db.query(User).count() == 0
    assert db.query(PlatformAuditLog).count() == 0


def test_final_flush_failure_rolls_back_admin_and_audit_too(
    db, platform_admin, monkeypatch
):
    original_flush = db.flush
    flush_calls = 0

    def fail_final_flush(*args, **kwargs):
        nonlocal flush_calls
        flush_calls += 1
        if flush_calls == 2:
            raise RuntimeError("internal final flush detail")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_final_flush)

    with pytest.raises(TenantOnboardingError, match=TENANT_ONBOARDING_MESSAGE):
        create_tenant_with_admin(
            db,
            make_onboarding_request(),
            actor_id=platform_admin.id,
        )

    assert db.query(Tenant).count() == 0
    assert db.query(TenantDomain).count() == 0
    assert db.query(SystemConfig).count() == 0
    assert db.query(User).count() == 0
    assert db.query(PlatformAuditLog).count() == 0


def test_onboarding_uses_one_session_and_one_transaction(
    db, platform_admin, monkeypatch
):
    transaction_begins = []
    tenant_context_sessions = []
    original_set_tenant_context = tenant_service.set_tenant_context

    def record_begin(session, transaction, connection):
        transaction_begins.append((session, transaction, connection))

    def record_tenant_context(session, tenant_id):
        tenant_context_sessions.append(session)
        return original_set_tenant_context(session, tenant_id)

    event.listen(db, "after_begin", record_begin)
    monkeypatch.setattr(
        tenant_service,
        "set_tenant_context",
        record_tenant_context,
    )
    monkeypatch.setattr(
        db,
        "commit",
        lambda: pytest.fail("service must use its one transaction boundary"),
    )
    try:
        create_tenant_with_admin(
            db,
            make_onboarding_request(),
            actor_id=platform_admin.id,
        )
    finally:
        event.remove(db, "after_begin", record_begin)

    assert tenant_context_sessions == [db]
    assert len(transaction_begins) == 1
    assert transaction_begins[0][0] is db


def test_same_session_can_sequentially_onboard_distinct_tenants_without_leaking_scope(
    db, platform_admin
):
    first = create_tenant_with_admin(
        db,
        make_onboarding_request(
            code="first-tenant",
            primary_domain="first.example",
            admin_email="admin@first.example",
        ),
        actor_id=platform_admin.id,
    )
    with pytest.raises(RuntimeError, match="tenant-scoped"):
        get_tenant_id(db)

    second = create_tenant_with_admin(
        db,
        make_onboarding_request(
            code="second-tenant",
            primary_domain="second.example",
            admin_email="admin@second.example",
        ),
        actor_id=platform_admin.id,
    )

    with pytest.raises(RuntimeError, match="tenant-scoped"):
        get_tenant_id(db)
    assert first.id != second.id
    assert db.query(Tenant).count() == 2
    assert db.query(TenantDomain).count() == 2
    assert db.query(SystemConfig).count() == 2
    assert db.query(User).count() == 2
    assert db.query(PlatformAuditLog).count() == 2


def test_binding_remains_immutable_during_onboarding_transaction(
    db, platform_admin, monkeypatch
):
    original_get_password_hash = tenant_service.get_password_hash
    attempted_rebind = []

    def verify_binding_is_immutable(password):
        with pytest.raises(ValueError, match="does not match session tenant"):
            set_tenant_context(db, uuid4())
        attempted_rebind.append(True)
        return original_get_password_hash(password)

    monkeypatch.setattr(
        tenant_service,
        "get_password_hash",
        verify_binding_is_immutable,
    )

    create_tenant_with_admin(
        db,
        make_onboarding_request(),
        actor_id=platform_admin.id,
    )

    assert attempted_rebind == [True]


def test_failed_onboarding_releases_internal_scope_for_safe_retry(
    db, platform_admin, monkeypatch
):
    original_get_password_hash = tenant_service.get_password_hash
    attempts = 0

    def fail_once(password):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("internal failure")
        return original_get_password_hash(password)

    monkeypatch.setattr(tenant_service, "get_password_hash", fail_once)

    with pytest.raises(TenantOnboardingError):
        create_tenant_with_admin(
            db,
            make_onboarding_request(code="failed-tenant"),
            actor_id=platform_admin.id,
        )
    with pytest.raises(RuntimeError, match="tenant-scoped"):
        get_tenant_id(db)

    recovered = create_tenant_with_admin(
        db,
        make_onboarding_request(code="recovered-tenant"),
        actor_id=platform_admin.id,
    )

    assert recovered.code == "recovered-tenant"
    assert db.query(Tenant).count() == 1


def test_internal_onboarding_release_cannot_unbind_ordinary_tenant_session(
    db, tenant_a, tenant_b
):
    from app.config.tenant_session import _release_platform_onboarding_context

    tenant_db = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    try:
        with pytest.raises(TypeError, match="TenantCapableSession"):
            _release_platform_onboarding_context(tenant_db, tenant_a.id)
        with pytest.raises(ValueError, match="does not match session tenant"):
            set_tenant_context(tenant_db, tenant_b.id)
        assert get_tenant_id(tenant_db) == tenant_a.id
    finally:
        tenant_db.close()


@pytest.fixture
def platform_client(db):
    from app.routes import auth, platform

    test_app = FastAPI()
    test_app.include_router(auth.router, prefix="/api")
    test_app.include_router(platform.router, prefix="/api")

    def override_db():
        try:
            yield db
        finally:
            if db.in_transaction():
                db.rollback()

    test_app.dependency_overrides[get_unscoped_db] = override_db
    with TestClient(test_app) as test_client:
        yield test_client


def platform_login(platform_client, platform_admin):
    response = platform_client.post(
        "/api/platform/auth/login",
        json={
            "email": platform_admin.email,
            "password": "PlatformPassword123",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_platform_and_tenant_tokens_are_mutually_rejected(
    platform_client, db, platform_admin
):
    platform_headers = platform_login(platform_client, platform_admin)
    tenant = Tenant(code="token-tenant", name="Token Tenant")
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        email="tenant-user@example.com",
        hashed_password=get_password_hash("TenantPassword123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    tenant_token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        role=user.role.value,
    )

    platform_response = platform_client.post(
        "/api/platform/tenants",
        headers={"Authorization": f"Bearer {tenant_token}"},
        json=make_onboarding_request().model_dump(mode="json"),
    )
    tenant_response = platform_client.get("/api/auth/me", headers=platform_headers)

    assert platform_response.status_code == 401
    assert tenant_response.status_code == 401


def test_platform_create_rejects_tenant_id_impersonation(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    payload = make_onboarding_request().model_dump(mode="json")
    payload["tenant_id"] = str(uuid4())

    response = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


def test_platform_validation_error_does_not_echo_admin_password(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    secret = "leaked-secret"
    payload = make_onboarding_request().model_dump(mode="json")
    payload["admin_password"] = secret

    response = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid platform request"}
    assert secret not in response.text


def test_platform_create_accepts_exactly_twelve_utf8_byte_password(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    payload = make_onboarding_request().model_dump(mode="json")
    payload["admin_password"] = "密A1abcdefg"

    response = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "password",
    [
        "A1abcdefg",
        "A1" + "a" * 71,
    ],
)
def test_platform_create_rejects_passwords_outside_utf8_byte_range(
    platform_client, platform_admin, password
):
    headers = platform_login(platform_client, platform_admin)
    payload = make_onboarding_request().model_dump(mode="json")
    payload["admin_password"] = password

    response = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid platform request"}


def test_duplicate_platform_onboarding_returns_safe_fixed_409(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    payload = make_onboarding_request().model_dump(mode="json")

    first = platform_client.post("/api/platform/tenants", headers=headers, json=payload)
    second = platform_client.post("/api/platform/tenants", headers=headers, json=payload)

    assert first.status_code == 201
    assert first.json()["primary_domain"] == payload["primary_domain"]
    assert second.status_code == 409
    assert second.json() == {"detail": TENANT_CONFLICT_MESSAGE}
    assert "admin_password" not in second.text


def test_platform_write_on_registered_company_host_uses_isolated_host_session(
    platform_client, db, tenant_a, platform_admin, monkeypatch
):
    """专属域名校验不得占用平台写事务所使用的 Session。"""

    company_host = "platform-entry.careray.example"
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain=company_host,
            is_primary=True,
        )
    )
    db.commit()
    monkeypatch.setenv("UNIFIED_ENTRY_HOSTS", "")

    login = platform_client.post(
        "/api/platform/auth/login",
        headers={"Host": company_host},
        json={
            "email": platform_admin.email,
            "password": "PlatformPassword123",
        },
    )
    assert login.status_code == 200

    payload = make_onboarding_request(
        code="dedicated-host-created",
        primary_domain="dedicated-host-created.example",
        admin_email="admin@dedicated-host-created.example",
    ).model_dump(mode="json")
    created = platform_client.post(
        "/api/platform/tenants",
        headers={
            "Host": company_host,
            "Authorization": f"Bearer {login.json()['access_token']}",
        },
        json=payload,
    )

    assert created.status_code == 201
    assert created.json()["code"] == "dedicated-host-created"


def test_disabled_tenant_rejects_new_login_and_old_token_with_403_but_keeps_data(
    platform_client, db, platform_admin
):
    platform_headers = platform_login(platform_client, platform_admin)
    payload = make_onboarding_request().model_dump(mode="json")
    created = platform_client.post(
        "/api/platform/tenants", headers=platform_headers, json=payload
    )
    assert created.status_code == 201
    tenant_id = created.json()["id"]

    login_payload = {
        "tenant_code": "careray-cloud",
        "email": "admin@careray-cloud.example",
        "password": "StrongPassword123",
    }
    login = platform_client.post("/api/auth/login", json=login_payload)
    assert login.status_code == 200
    tenant_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert platform_client.get("/api/auth/me", headers=tenant_headers).status_code == 200
    original_user = db.query(User).one()
    original_config = db.query(SystemConfig).one()
    original_user_snapshot = {
        "id": original_user.id,
        "tenant_id": original_user.tenant_id,
        "email": original_user.email,
        "role": original_user.role,
        "is_active": original_user.is_active,
    }
    original_config_snapshot = {
        "id": original_config.id,
        "tenant_id": original_config.tenant_id,
        "mail_enabled": original_config.mail_enabled,
        "smtp_host": original_config.smtp_host,
    }
    db.rollback()

    disabled = platform_client.patch(
        f"/api/platform/tenants/{tenant_id}/status",
        headers=platform_headers,
        json={"status": "disabled"},
    )

    assert disabled.status_code == 200
    assert platform_client.post("/api/auth/login", json=login_payload).status_code == 403
    assert platform_client.get("/api/auth/me", headers=tenant_headers).status_code == 403
    retained_user = db.query(User).one()
    retained_config = db.query(SystemConfig).one()
    assert {
        "id": retained_user.id,
        "tenant_id": retained_user.tenant_id,
        "email": retained_user.email,
        "role": retained_user.role,
        "is_active": retained_user.is_active,
    } == original_user_snapshot
    assert {
        "id": retained_config.id,
        "tenant_id": retained_config.tenant_id,
        "mail_enabled": retained_config.mail_enabled,
        "smtp_host": retained_config.smtp_host,
    } == original_config_snapshot


def test_status_change_for_missing_tenant_returns_fixed_404(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)

    response = platform_client.patch(
        f"/api/platform/tenants/{uuid4()}/status",
        headers=headers,
        json={"status": "disabled"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Tenant not found"}


def test_platform_can_list_and_inspect_tenants_with_domains(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    created = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=make_onboarding_request().model_dump(mode="json"),
    )
    tenant_id = created.json()["id"]

    listing = platform_client.get("/api/platform/tenants", headers=headers)
    detail = platform_client.get(
        f"/api/platform/tenants/{tenant_id}", headers=headers
    )

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [tenant_id]
    assert detail.status_code == 200
    assert detail.json()["domains"] == [
        {
            "id": detail.json()["domains"][0]["id"],
            "domain": "interview.careray-cloud.example",
            "is_primary": True,
            "created_at": detail.json()["domains"][0]["created_at"],
        }
    ]


def test_platform_domain_maintenance_is_audited(
    platform_client, db, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    created = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=make_onboarding_request().model_dump(mode="json"),
    ).json()
    tenant_id = created["id"]

    added = platform_client.post(
        f"/api/platform/tenants/{tenant_id}/domains",
        headers=headers,
        json={"domain": "jobs.careray-cloud.example", "is_primary": False},
    )
    assert added.status_code == 201
    domain_id = added.json()["id"]
    promoted = platform_client.patch(
        f"/api/platform/tenants/{tenant_id}/domains/{domain_id}",
        headers=headers,
        json={"domain": "CAREERS.CARERAY-CLOUD.EXAMPLE:443", "is_primary": True},
    )
    assert promoted.status_code == 200
    assert promoted.json()["domain"] == "careers.careray-cloud.example"
    assert promoted.json()["is_primary"] is True
    demoted = platform_client.patch(
        f"/api/platform/tenants/{tenant_id}/domains/{domain_id}",
        headers=headers,
        json={"is_primary": False},
    )
    assert demoted.status_code == 409
    assert demoted.json() == {
        "detail": "Primary domain must be replaced before removal"
    }
    domains = platform_client.get(
        f"/api/platform/tenants/{tenant_id}", headers=headers
    ).json()["domains"]
    secondary_id = next(item["id"] for item in domains if not item["is_primary"])
    deleted = platform_client.delete(
        f"/api/platform/tenants/{tenant_id}/domains/{secondary_id}",
        headers=headers,
    )
    assert deleted.status_code == 204

    actions = [
        row.action
        for row in db.query(PlatformAuditLog)
        .filter(PlatformAuditLog.target_tenant_id == UUID(created["id"]))
        .order_by(PlatformAuditLog.created_at)
        .all()
    ]
    assert actions == [
        "tenant.created",
        "tenant.domain_added",
        "tenant.domain_updated",
        "tenant.domain_deleted",
    ]


def test_platform_duplicate_domain_has_distinct_stable_conflict(
    platform_client, platform_admin
):
    headers = platform_login(platform_client, platform_admin)
    created = platform_client.post(
        "/api/platform/tenants",
        headers=headers,
        json=make_onboarding_request().model_dump(mode="json"),
    ).json()

    first = platform_client.post(
        f"/api/platform/tenants/{created['id']}/domains",
        headers=headers,
        json={"domain": "jobs.careray-cloud.example", "is_primary": False},
    )
    duplicate = platform_client.post(
        f"/api/platform/tenants/{created['id']}/domains",
        headers=headers,
        json={"domain": "JOBS.CARERAY-CLOUD.EXAMPLE:443", "is_primary": False},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Domain already exists"}
