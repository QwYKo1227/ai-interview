import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_request_observability_adds_request_id_and_structured_context(caplog):
    from app.core.observability import install_observability

    app = FastAPI()
    install_observability(app)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/public/{token}")
    def public_link(token: str):
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="app.request"), TestClient(app) as client:
        response = client.get(
            "/health", headers={"X-Request-ID": "req-safe-123"}
        )
        client.get("/public/super-secret-public-token")

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-safe-123"
    record = next(record for record in caplog.records if record.name == "app.request")
    assert record.request_id == "req-safe-123"
    assert record.tenant_id is None
    assert record.user_id is None
    assert record.route == "/health"
    assert record.status == 200
    public_record = next(
        record
        for record in caplog.records
        if record.name == "app.request" and record.request_id != "req-safe-123"
    )
    assert public_record.route == "/public/{token}"
    assert "super-secret-public-token" not in caplog.text


def test_observability_redacts_authorization_tokens_and_secret_values():
    from app.core.observability import redact_sensitive

    secret = "super-secret-value"
    rendered = redact_sensitive(
        f"Authorization: Bearer {secret} api_key={secret} smtp_password={secret}"
    )

    assert secret not in rendered
    assert rendered.count("[REDACTED]") >= 3


def test_rate_limiter_state_is_per_application_and_returns_429(client, db, tenant_a):
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit
    from app.core.security import get_password_hash
    from app.models.models import User, UserRole

    db.add(
        User(
            tenant_id=tenant_a.id,
            email="member@example.com",
            hashed_password=get_password_hash("Password123"),
            role=UserRole.HR,
        )
    )
    db.commit()
    client.app.state.rate_limiter = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=2, window_seconds=60)}
    )
    payload = {
        "tenant_code": tenant_a.code,
        "email": "member@example.com",
        "password": "WrongPassword123",
    }

    assert client.post("/api/auth/login", json=payload).status_code == 401
    assert client.post("/api/auth/login", json=payload).status_code == 401
    limited = client.post("/api/auth/login", json=payload)

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1

    other_app = FastAPI()
    other = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=2, window_seconds=60)}
    )
    other_app.state.rate_limiter = other
    assert other is not client.app.state.rate_limiter
    assert other.snapshot() == {}


def test_public_upload_has_its_own_429_tier(
    client, db, tenant_a, test_resume, monkeypatch
):
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit
    from app.routes import resumes
    from app.schemas.resume import ResumeResponse

    client.app.state.rate_limiter = ApplicationRateLimiter(
        policies={"public_upload": RateLimit(limit=1, window_seconds=60)}
    )
    tenant_code = tenant_a.code
    position_id = test_resume.position_id
    resume_response = ResumeResponse.model_validate(test_resume)
    monkeypatch.setattr(
        resumes,
        "upload_public_resume",
        lambda *_args, **_kwargs: resume_response,
    )
    db.expunge_all()
    data = {
        "tenant_code": tenant_code,
        "position_id": str(position_id),
    }
    files = {"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")}

    first = client.post("/api/resumes", data=data, files=files)
    limited = client.post("/api/resumes", data=data, files=files)

    assert first.status_code == 200
    assert limited.status_code == 429


def test_public_code_run_has_its_own_429_tier(client, monkeypatch):
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit
    from app.routes import coding_tests

    client.app.state.rate_limiter = ApplicationRateLimiter(
        policies={"public_code_run": RateLimit(limit=1, window_seconds=60)}
    )
    monkeypatch.setattr(coding_tests, "_validate_public_request", lambda *_args: None)
    monkeypatch.setattr(
        coding_tests,
        "run_public_code",
        lambda *_args: {
            "passed": True,
            "score": 100,
            "results": [],
            "error": None,
            "raw": None,
        },
    )
    token = "a" * 43
    payload = {"code": "print(1)", "language": "python"}

    first = client.post(f"/api/public/coding-tests/{token}/run", json=payload)
    limited = client.post(f"/api/public/coding-tests/{token}/run", json=payload)

    assert first.status_code == 200
    assert limited.status_code == 429


def test_local_startup_uses_roles_alembic_and_tenant_scoped_seed():
    root = Path(__file__).parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    backend_env = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    demo_seed = (
        root / "backend" / "scripts" / "seed_demo_data.py"
    ).read_text(encoding="utf-8")
    main = (root / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert "APP_RUNTIME_PASSWORD" in compose
    assert "APP_MIGRATION_PASSWORD" in compose
    assert "01-app-roles.sh" in compose
    assert "MIGRATION_DATABASE_URL=postgresql://app_migration:" in backend_env
    assert "DATABASE_URL=postgresql://app_runtime:" in backend_env
    assert "alembic upgrade head" in readme
    assert "migrate_system_config_singleton.py" not in readme
    assert "Base.metadata.create_all" not in demo_seed
    assert "tenant_session(" in demo_seed
    assert "with tenant_session(" in main
