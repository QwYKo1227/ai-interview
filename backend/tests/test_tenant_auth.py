from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.orm import sessionmaker

from app.routes import auth as auth_routes
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


def test_dedicated_domain_rejects_login_for_another_tenant(
    client, db, tenant_a, tenant_b
):
    create_user(db, tenant_a.id, "same@example.com", "Password123")
    create_user(db, tenant_b.id, "same@example.com", "OtherPass123")
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain="login.careray.example",
            is_primary=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/auth/login",
        headers={"Host": "LOGIN.CARERAY.EXAMPLE:8443"},
        json={
            "tenant_code": tenant_b.code,
            "email": "same@example.com",
            "password": "OtherPass123",
        },
    )

    assert response.status_code == 403


def test_unified_entry_allows_explicit_tenant_login(
    client, db, tenant_b, monkeypatch
):
    monkeypatch.setenv("UNIFIED_ENTRY_HOSTS", "testserver,gateway.example.test")
    create_user(db, tenant_b.id, "member@example.com", "Password123")

    response = client.post(
        "/api/auth/login",
        headers={"Host": "gateway.example.test"},
        json={
            "tenant_code": tenant_b.code,
            "email": "member@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 200


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
        ("careray", "missing@example.com", "Password123"),
        ("careray", "disabled@example.com", "Password123"),
        ("careray", "member@example.com", "WrongPassword123"),
    ],
)
def test_login_failures_share_one_unauthorized_response(
    client, db, tenant_a, tenant_code, email, password, monkeypatch
):
    db.add(
        Tenant(
            code="disabled-co",
            name="Disabled Co",
            status=TenantStatus.DISABLED,
        )
    )
    db.commit()
    member = create_user(db, tenant_a.id, "member@example.com", "Password123")
    disabled_user = create_user(
        db,
        tenant_a.id,
        "disabled@example.com",
        "Password123",
        is_active=False,
    )
    password_checks = []
    original_verify_password = auth_routes.verify_password

    def spy_verify_password(plain_password, hashed_password):
        password_checks.append((plain_password, hashed_password))
        return original_verify_password(plain_password, hashed_password)

    monkeypatch.setattr(auth_routes, "verify_password", spy_verify_password)

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
    assert len(password_checks) == 1

    if tenant_code == "careray" and email == member.email:
        expected_hash = member.hashed_password
    else:
        expected_hash = getattr(auth_routes, "DUMMY_PASSWORD_HASH", None)
    assert password_checks[0] == (password, expected_hash)


def test_successful_login_verifies_the_real_password_hash_once(
    client, db, tenant_a, monkeypatch
):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    password_checks = []
    original_verify_password = auth_routes.verify_password

    def spy_verify_password(plain_password, hashed_password):
        password_checks.append((plain_password, hashed_password))
        return original_verify_password(plain_password, hashed_password)

    monkeypatch.setattr(auth_routes, "verify_password", spy_verify_password)

    response = client.post(
        "/api/auth/login",
        json={
            "tenant_code": tenant_a.code,
            "email": user.email,
            "password": "Password123",
        },
    )

    assert response.status_code == 200
    assert password_checks == [("Password123", user.hashed_password)]


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
        "token_type": "tenant",
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


def test_auth_me_returns_only_the_jwt_tenants_company_summary(
    client, db, tenant_a, tenant_b
):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    tenant_a.logo_url = "https://cdn.example.com/careray.png"
    db.add_all(
        [
            TenantDomain(
                tenant_id=tenant_a.id,
                domain="login.careray.example",
                is_primary=True,
            ),
            TenantDomain(
                tenant_id=tenant_b.id,
                domain="login.photonthix.example",
                is_primary=True,
            ),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/auth/me?tenant_id={tenant_b.id}",
        headers={**auth_header(user), "X-Tenant-ID": str(tenant_b.id)},
    )

    assert response.status_code == 200
    assert response.json()["tenant"] == {
        "id": str(tenant_a.id),
        "code": "careray",
        "name": "CareRay",
        "logo_url": "https://cdn.example.com/careray.png",
        "primary_domain": "login.careray.example",
    }


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


def test_unknown_host_is_rejected_even_with_untrusted_tenant_inputs(
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

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown request host"}


def test_trailing_dot_host_still_enforces_dedicated_tenant(
    client, db, tenant_a, tenant_b
):
    create_user(db, tenant_a.id, "same@example.com", "Password123")
    create_user(db, tenant_b.id, "same@example.com", "OtherPass123")
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain="login.careray.example",
            is_primary=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/auth/login",
        headers={"Host": "LOGIN.CARERAY.EXAMPLE.:443"},
        json={
            "tenant_code": tenant_b.code,
            "email": "same@example.com",
            "password": "OtherPass123",
        },
    )

    assert response.status_code == 403


def test_untrusted_forwarded_host_cannot_override_unknown_direct_host(
    client, db, tenant_a
):
    create_user(db, tenant_a.id, "member@example.com", "Password123")
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain="login.careray.example",
            is_primary=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/auth/login",
        headers={
            "Host": "attacker.invalid",
            "X-Forwarded-Host": "login.careray.example",
        },
        json={
            "tenant_code": tenant_a.code,
            "email": "member@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 400


def test_disabled_tenant_invalidates_an_existing_token(client, db, tenant_a):
    user = create_user(db, tenant_a.id, "member@example.com", "Password123")
    headers = auth_header(user)
    tenant_a.status = TenantStatus.DISABLED
    db.commit()

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 403


def test_disabled_tenant_only_returns_403_after_valid_credentials(
    client, db, tenant_a
):
    create_user(db, tenant_a.id, "member@example.com", "Password123")
    tenant_a.status = TenantStatus.DISABLED
    db.commit()

    wrong_password = client.post(
        "/api/auth/login",
        json={
            "tenant_code": tenant_a.code,
            "email": "member@example.com",
            "password": "WrongPassword123",
        },
    )
    missing_user = client.post(
        "/api/auth/login",
        json={
            "tenant_code": tenant_a.code,
            "email": "missing@example.com",
            "password": "Password123",
        },
    )
    valid_credentials = client.post(
        "/api/auth/login",
        json={
            "tenant_code": tenant_a.code,
            "email": "member@example.com",
            "password": "Password123",
        },
    )

    assert wrong_password.status_code == 401
    assert missing_user.status_code == 401
    assert valid_credentials.status_code == 403


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


@pytest.mark.parametrize("token_type", [None, "platform", "bearer"])
def test_tenant_token_decoder_rejects_missing_or_wrong_token_type(token_type):
    from app.core import security

    token = raw_token()
    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if token_type is None:
        claims.pop("token_type")
    else:
        claims["token_type"] = token_type
    invalid = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)

    with pytest.raises(Exception):
        security.decode_access_token(invalid)


def test_platform_decoder_accepts_only_platform_claim_shape():
    from app.core.platform_security import (
        create_platform_access_token,
        decode_platform_access_token,
    )

    user_id = uuid4()
    assert decode_platform_access_token(
        create_platform_access_token(user_id=user_id)
    ).user_id == user_id

    tenant_claims = jwt.decode(
        raw_token(sub=str(user_id)), SECRET_KEY, algorithms=[ALGORITHM]
    )
    wrong_type = jwt.encode(tenant_claims, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(Exception):
        decode_platform_access_token(wrong_type)


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


def test_create_user_normalizes_email_before_duplicate_query(
    client, db, tenant_a
):
    admin = create_user(
        db,
        tenant_a.id,
        "admin@example.com",
        "Password123",
        role=UserRole.ADMIN,
    )
    create_user(db, tenant_a.id, "member@example.com", "Password123")

    response = client.post(
        "/api/auth/users",
        headers=auth_header(admin),
        json={
            "email": "MEMBER@EXAMPLE.COM",
            "password": "AnotherPassword123",
            "role": "hr",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Email already registered"}


def test_create_user_maps_database_unique_race_to_stable_conflict(
    client, db, tenant_a, monkeypatch
):
    from sqlalchemy.exc import IntegrityError
    from app.config.tenant_session import TenantSession

    admin = create_user(
        db,
        tenant_a.id,
        "admin@example.com",
        "Password123",
        role=UserRole.ADMIN,
    )
    rollbacks = []

    class Diagnostic:
        constraint_name = "uq_users_tenant_lower_email"

    class UniqueEmailViolation(RuntimeError):
        sqlstate = "23505"
        diag = Diagnostic()

    def raise_unique_conflict(_session):
        raise IntegrityError("INSERT users", {}, UniqueEmailViolation("unique conflict"))

    real_rollback = TenantSession.rollback

    def track_rollback(session):
        rollbacks.append(True)
        return real_rollback(session)

    monkeypatch.setattr(TenantSession, "commit", raise_unique_conflict)
    monkeypatch.setattr(TenantSession, "rollback", track_rollback)
    try:
        response = client.post(
            "/api/auth/users",
            headers=auth_header(admin),
            json={
                "email": "new-user@example.com",
                "password": "AnotherPassword123",
                "role": "hr",
            },
        )
    except IntegrityError:
        pytest.fail("database uniqueness conflict escaped the route as a 500")

    assert response.status_code == 409
    assert response.json() == {"detail": "Email already registered"}
    assert rollbacks


def test_email_unique_conflict_classifier_rejects_other_integrity_errors():
    from sqlalchemy.exc import IntegrityError
    from app.routes.auth import _is_email_unique_conflict

    class Diagnostic:
        constraint_name = None

    class DatabaseViolation(RuntimeError):
        sqlstate = None
        diag = Diagnostic()

    def error(sqlstate, constraint_name):
        original = DatabaseViolation("database error")
        original.sqlstate = sqlstate
        original.diag.constraint_name = constraint_name
        return IntegrityError("INSERT users", {}, original)

    assert _is_email_unique_conflict(
        error("23505", "uq_users_tenant_lower_email")
    )
    assert not _is_email_unique_conflict(error("23505", "uq_users_tenant_id_id"))
    assert not _is_email_unique_conflict(
        error("23503", "fk_users_tenant_id_tenants")
    )
    assert not _is_email_unique_conflict(
        IntegrityError("INSERT users", {}, RuntimeError("generic integrity error"))
    )
