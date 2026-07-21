from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.orm import sessionmaker

from app.core.security import ALGORITHM, SECRET_KEY, create_access_token, get_password_hash
from app.core.tenant_context import TenantContext
from app.config.tenant_session import TenantSession
from app.models.models import User, UserRole
from app.models.tenant_models import Tenant, TenantDomain, TenantStatus


LOGIN_ERROR = "公司、账号或密码错误"


def create_user(db, tenant_id, email, password, *, is_active=True, role=UserRole.HR):
    user = User(
        tenant_id=tenant_id,
        email=email,
        hashed_password=get_password_hash(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_tenant_list_only_returns_active_tenant_summaries(client, db, tenant_a):
    tenant_a.logo_url = "https://cdn.example.com/careray.png"
    disabled = Tenant(
        code="disabled-co",
        name="Disabled Co",
        status=TenantStatus.DISABLED,
    )
    db.add_all(
        [
            disabled,
            TenantDomain(
                tenant_id=tenant_a.id,
                domain="login.careray.example",
                is_primary=True,
            ),
        ]
    )
    db.commit()

    response = client.get("/api/auth/tenants")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(tenant_a.id),
            "code": "careray",
            "name": "CareRay",
            "logo_url": "https://cdn.example.com/careray.png",
            "primary_domain": "login.careray.example",
        }
    ]


def test_login_selects_user_by_tenant(client, db, tenant_a, tenant_b):
    user_a = create_user(db, tenant_a.id, "same@example.com", "Password123")
    create_user(db, tenant_b.id, "same@example.com", "OtherPass123")

    response = client.post(
        "/api/auth/login",
        json={
            "tenant_code": "careray",
            "email": "same@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 200
    claims = jwt.decode(
        response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM]
    )
    assert claims["sub"] == str(user_a.id)
    assert claims["tenant_id"] == str(tenant_a.id)
    assert claims["role"] == UserRole.HR.value


def test_tenant_a_password_cannot_login_to_tenant_b(client, db, tenant_a, tenant_b):
    create_user(db, tenant_a.id, "same@example.com", "Password123")
    create_user(db, tenant_b.id, "same@example.com", "OtherPass123")

    response = client.post(
        "/api/auth/login",
        json={
            "tenant_code": "photonthix",
            "email": "same@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == LOGIN_ERROR


@pytest.mark.parametrize(
    ("tenant_code", "email", "password"),
    [
        ("missing", "member@example.com", "Password123"),
        ("disabled-co", "member@example.com", "Password123"),
        ("careray", "missing@example.com", "Password123"),
        ("careray", "disabled@example.com", "Password123"),
        ("careray", "member@example.com", "WrongPassword123"),
    ],
)
def test_login_failures_share_one_unauthorized_response(
    client, db, tenant_a, tenant_code, email, password
):
    db.add(
        Tenant(
            code="disabled-co",
            name="Disabled Co",
            status=TenantStatus.DISABLED,
        )
    )
    db.commit()
    create_user(db, tenant_a.id, "member@example.com", "Password123")
    create_user(
        db,
        tenant_a.id,
        "disabled@example.com",
        "Password123",
        is_active=False,
    )

    response = client.post(
        "/api/auth/login",
        json={
            "tenant_code": tenant_code,
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": LOGIN_ERROR}
    assert response.headers["www-authenticate"] == "Bearer"


def test_create_access_token_uses_tenant_scoped_identity_claims(tenant_a):
    user_id = uuid4()

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_a.id,
        role=UserRole.ADMIN.value,
        expires_delta=timedelta(minutes=5),
    )

    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_a.id)
    assert claims["role"] == UserRole.ADMIN.value
    assert isinstance(claims["exp"], int)


def test_legacy_form_login_cannot_omit_tenant_code(client, db, tenant_a):
    create_user(db, tenant_a.id, "member@example.com", "Password123")

    response = client.post(
        "/api/auth/token",
        data={"username": "member@example.com", "password": "Password123"},
    )

    assert response.status_code == 422


def test_legacy_form_login_requires_and_honors_tenant_code(
    client, db, tenant_a, tenant_b
):
    create_user(db, tenant_a.id, "same@example.com", "Password123")
    create_user(db, tenant_b.id, "same@example.com", "OtherPass123")

    response = client.post(
        "/api/auth/token",
        data={
            "tenant_code": "photonthix",
            "username": "same@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == LOGIN_ERROR


def auth_header(user, *, tenant_id=None, role=None):
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant_id or user.tenant_id,
        role=role or user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def raw_token(**overrides):
    claims = {
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": UserRole.HR.value,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def test_valid_token_authenticates_user_with_uuid_subject(
    client, db, tenant_a
):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")

    response = client.get("/api/auth/me", headers=auth_header(user))

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_matching_domain_is_normalized_for_case_and_port(client, db, tenant_a):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain="login.careray.example",
            is_primary=True,
        )
    )
    db.commit()
    headers = {
        **auth_header(user),
        "Host": "LOGIN.CARERAY.EXAMPLE:8443",
    }

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200


def test_token_tenant_must_match_mapped_domain(
    client, db, tenant_a, tenant_b
):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    db.add(
        TenantDomain(
            tenant_id=tenant_b.id,
            domain="login.photonthix.example",
            is_primary=True,
        )
    )
    db.commit()
    headers = {
        **auth_header(user),
        "Host": "login.photonthix.example",
    }

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 403


def test_unknown_host_is_unified_entry_and_untrusted_tenant_inputs_are_ignored(
    client, db, tenant_a, tenant_b
):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    headers = {
        **auth_header(user),
        "Host": "app.example.test:443",
        "X-Tenant-ID": str(tenant_b.id),
    }

    response = client.get(
        f"/api/auth/me?tenant_id={tenant_b.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_disabled_tenant_invalidates_an_existing_token(client, db, tenant_a):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    headers = auth_header(user)
    tenant_a.status = TenantStatus.DISABLED
    db.commit()

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"tenant_id": str(uuid4()), "role": "hr"},
        {"sub": str(uuid4()), "role": "hr"},
        {"sub": str(uuid4()), "tenant_id": str(uuid4())},
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "hr",
        },
        {
            "sub": 123,
            "tenant_id": str(uuid4()),
            "role": "hr",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": "member@example.com",
            "tenant_id": str(uuid4()),
            "role": "hr",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": str(uuid4()),
            "tenant_id": 123,
            "role": "hr",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": str(uuid4()),
            "tenant_id": "not-a-uuid",
            "role": "hr",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": 123,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "hr",
            "exp": "tomorrow",
        },
    ],
)
def test_missing_or_invalid_claims_are_rejected(client, claims):
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_token_decoder_requires_strict_tenant_identity_claims():
    from app.core import security

    assert hasattr(security, "decode_access_token"), "strict decoder is missing"

    token = raw_token(role=123)
    with pytest.raises(Exception):
        security.decode_access_token(token)


def test_expired_or_invalid_signature_is_rejected(client):
    expired = raw_token(exp=datetime.now(timezone.utc) - timedelta(seconds=1))
    wrong_signature = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "hr",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "wrong-secret",
        algorithm=ALGORITHM,
    )

    for token in (expired, wrong_signature):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


def test_email_subject_tokens_are_not_accepted(client, db, tenant_a):
    create_user(db, tenant_a.id, "member@example.com", "Password123")
    token = raw_token(
        sub="member@example.com",
        tenant_id=str(tenant_a.id),
    )

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_get_tenant_db_yields_scoped_session_and_closes_it(
    db, monkeypatch, tenant_a
):
    try:
        from app.core.tenant_dependencies import get_tenant_db
    except ModuleNotFoundError:
        pytest.fail("tenant_dependencies module is not implemented")

    class TrackingTenantSession(TenantSession):
        was_closed = False

        def close(self):
            self.was_closed = True
            return super().close()

    factory = sessionmaker(
        bind=db.get_bind(),
        class_=TrackingTenantSession,
        autoflush=False,
    )
    monkeypatch.setattr("app.config.database.TenantSessionLocal", factory)
    context = TenantContext(
        tenant_id=tenant_a.id,
        tenant_code=tenant_a.code,
        source="jwt",
    )
    dependency = get_tenant_db(context)

    tenant_db = next(dependency)
    try:
        assert isinstance(tenant_db, TenantSession)
        assert tenant_db.info["tenant_id"] == tenant_a.id
    finally:
        dependency.close()

    assert tenant_db.was_closed is True


def test_authenticated_user_management_is_tenant_scoped(
    client, db, tenant_a, tenant_b
):
    admin = create_user(
        db,
        tenant_a.id,
        "admin@example.com",
        "Password123",
        role=UserRole.ADMIN,
    )
    create_user(db, tenant_b.id, "other@example.com", "Password123")

    response = client.get("/api/auth/users", headers=auth_header(admin))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(admin.id)]
