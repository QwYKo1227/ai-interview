from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import inspect
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
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


def test_production_logging_installs_real_info_handler_and_redaction_filter():
    from app.core.observability import SensitiveDataFilter, install_observability

    app = FastAPI()
    install_observability(app)
    app_logger = logging.getLogger("app")

    assert app_logger.level <= logging.INFO
    assert app_logger.handlers
    assert any(
        isinstance(item, SensitiveDataFilter)
        for handler in app_logger.handlers
        for item in handler.filters
    )
    assert all(handler.formatter is not None for handler in app_logger.handlers)


def test_background_task_context_propagates_ids_and_redacts_secrets(caplog):
    from app.core.observability import (
        background_task_context,
        install_observability,
        logging_context,
    )

    app = FastAPI()
    install_observability(app)
    tenant_id, resource_id = uuid4(), uuid4()
    logger = logging.getLogger("app.background")

    @background_task_context
    def task(actual_tenant_id, actual_resource_id):
        assert actual_tenant_id == tenant_id
        assert actual_resource_id == resource_id
        logger.info("Authorization: Bearer top-secret")

    with caplog.at_level(logging.INFO, logger="app.background"):
        with logging_context(request_id="req-background"):
            task(tenant_id, resource_id)

    record = next(item for item in caplog.records if item.name == "app.background")
    assert record.request_id == "req-background"
    assert record.tenant_id == str(tenant_id)
    assert record.resource_id == str(resource_id)
    assert str(resource_id) in record.task_id
    assert "top-secret" not in caplog.text


def _request(app, peer, *, forwarded_for=None, host=None, forwarded_host=None):
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    if host is not None:
        headers.append((b"host", host.encode("latin-1")))
    if forwarded_host is not None:
        headers.append((b"x-forwarded-host", forwarded_host.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


def test_client_ip_uses_only_a_validated_trusted_proxy_chain(monkeypatch):
    from app.core import rate_limit

    assert hasattr(rate_limit, "resolve_client_ip"), "trusted proxy resolver is missing"
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    app = FastAPI()

    trusted = _request(
        app,
        "10.0.0.3",
        forwarded_for="198.51.100.9, 10.0.0.2",
    )
    forged = _request(
        app,
        "203.0.113.8",
        forwarded_for="198.51.100.9, 10.0.0.2",
    )
    malformed = _request(app, "10.0.0.3", forwarded_for="198.51.100.9, forged")

    assert rate_limit.resolve_client_ip(trusted) == "198.51.100.9"
    assert rate_limit.resolve_client_ip(forged) == "203.0.113.8"
    assert rate_limit.resolve_client_ip(malformed) == "10.0.0.3"


def test_request_host_accepts_forwarded_host_only_from_a_trusted_proxy(monkeypatch):
    from app.core.proxy import resolve_request_host

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    app = FastAPI()
    trusted = _request(
        app,
        "10.0.0.3",
        host="backend.internal:8000",
        forwarded_host="BÜCHER.Example.:443",
    )
    forged = _request(
        app,
        "203.0.113.8",
        host="direct.example:8000",
        forwarded_host="BÜCHER.Example.:443",
    )

    assert resolve_request_host(trusted) == "xn--bcher-kva.example"
    assert resolve_request_host(forged) == "direct.example"


def test_invalid_trusted_proxy_cidr_is_a_startup_configuration_error(monkeypatch):
    from app.core.proxy import trusted_proxy_networks

    monkeypatch.setenv(
        "TRUSTED_PROXY_CIDRS",
        "10.0.0.0/8,this-is-not-a-network",
    )
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        trusted_proxy_networks()

    root = Path(__file__).parents[2]
    main = (root / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert main.index("validate_proxy_configuration()") < main.index("seed_db()")


def test_rate_limit_enforces_ip_and_subject_quotas_independently():
    from app.core.rate_limit import (
        ApplicationRateLimiter,
        RateLimit,
        enforce_rate_limit,
    )

    app = FastAPI()
    app.state.rate_limiter = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=1, window_seconds=60)}
    )
    first_ip = _request(app, "198.51.100.10")
    second_ip = _request(app, "198.51.100.11")

    enforce_rate_limit(first_ip, "login", "tenant-a", "first@example.com")
    with pytest.raises(HTTPException) as same_ip:
        enforce_rate_limit(first_ip, "login", "tenant-a", "second@example.com")
    assert same_ip.value.status_code == 429

    other_app = FastAPI()
    other_app.state.rate_limiter = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=1, window_seconds=60)}
    )
    enforce_rate_limit(first_ip := _request(other_app, "198.51.100.10"), "login", "tenant-a", "same@example.com")
    with pytest.raises(HTTPException) as same_subject:
        enforce_rate_limit(_request(other_app, "198.51.100.11"), "login", "tenant-a", "same@example.com")
    assert same_subject.value.status_code == 429


def test_rate_limiter_has_bounded_ttl_lru_storage():
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit

    assert "max_buckets" in inspect.signature(ApplicationRateLimiter).parameters
    now = [0.0]
    limiter = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=2, window_seconds=10)},
        clock=lambda: now[0],
        max_buckets=2,
    )

    for identity in ("one", "two", "three"):
        assert limiter.check("login", identity) is None
    assert len(limiter.snapshot()) == 2

    now[0] = 11.0
    assert limiter.check("login", "four") is None
    assert len(limiter.snapshot()) == 1


def test_rate_limiter_application_initialization_is_concurrency_safe():
    from app.core import rate_limit

    assert hasattr(rate_limit, "get_rate_limiter"), "startup limiter accessor is missing"
    app = FastAPI()
    with ThreadPoolExecutor(max_workers=16) as executor:
        limiters = list(executor.map(lambda _item: rate_limit.get_rate_limiter(app), range(64)))

    assert len({id(limiter) for limiter in limiters}) == 1


def test_rate_limiter_concurrent_checks_never_exceed_the_quota():
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit

    limiter = ApplicationRateLimiter(
        policies={"login": RateLimit(limit=25, window_seconds=60)}
    )
    with ThreadPoolExecutor(max_workers=32) as executor:
        results = list(
            executor.map(lambda _item: limiter.check("login", "shared"), range(200))
        )

    assert sum(result is None for result in results) == 25
    assert sum(result is not None for result in results) == 175


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


def test_public_upload_subject_is_stable_private_and_preserves_ip_quota():
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit, enforce_rate_limit
    from app.routes.resumes import _public_upload_rate_subject

    tenant_id, position_id = uuid4(), uuid4()
    first = _public_upload_rate_subject(
        tenant_id,
        position_id,
        candidate_name="  Candidate One ",
        email=" PERSON@Example.COM ",
        contact=" 138-0013-8000 ",
    )
    normalized = _public_upload_rate_subject(
        tenant_id,
        position_id,
        candidate_name="candidate one",
        email="person@example.com",
        contact="13800138000",
    )
    second = _public_upload_rate_subject(
        tenant_id,
        position_id,
        candidate_name="Candidate Two",
        email="other@example.com",
        contact=None,
    )

    assert first == normalized
    assert first != second
    assert len(first) == 64
    assert "person@example.com" not in first

    app = FastAPI()
    app.state.rate_limiter = ApplicationRateLimiter(
        policies={"public_upload": RateLimit(limit=1, window_seconds=60)}
    )
    enforce_rate_limit(_request(app, "198.51.100.10"), "public_upload", first)
    enforce_rate_limit(_request(app, "198.51.100.11"), "public_upload", second)
    with pytest.raises(HTTPException) as rotated_identity:
        enforce_rate_limit(
            _request(app, "198.51.100.10"),
            "public_upload",
            _public_upload_rate_subject(
                tenant_id,
                position_id,
                candidate_name="Rotated",
                email="rotated@example.com",
                contact=None,
            ),
        )
    assert rotated_identity.value.status_code == 429


def test_public_upload_with_empty_identity_uses_only_each_request_ip(
    client, db, tenant_a, test_resume, monkeypatch
):
    """空姓名/邮箱/电话不应让不同 IP 共用同一个候选人桶。"""

    from app.core import rate_limit
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit
    from app.routes import resumes
    from app.schemas.resume import ResumeResponse

    client.app.state.rate_limiter = ApplicationRateLimiter(
        policies={
            "public_upload": RateLimit(limit=1, window_seconds=60),
            "public_upload_tenant": RateLimit(limit=100, window_seconds=60),
        }
    )
    resume_response = ResumeResponse.model_validate(test_resume)
    monkeypatch.setattr(
        rate_limit,
        "resolve_client_ip",
        lambda request: request.headers["x-test-client-ip"],
    )
    monkeypatch.setattr(
        resumes,
        "upload_public_resume",
        lambda *_args, **_kwargs: resume_response,
    )
    tenant_code = tenant_a.code
    position_id = test_resume.position_id
    data = {
        "tenant_code": tenant_code,
        "position_id": str(position_id),
    }
    db.expunge_all()
    files = {"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")}

    first_ip = client.post(
        "/api/resumes",
        data=data,
        files=files,
        headers={"x-test-client-ip": "198.51.100.10"},
    )
    different_ip = client.post(
        "/api/resumes",
        data=data,
        files=files,
        headers={"x-test-client-ip": "198.51.100.11"},
    )
    repeated_first_ip = client.post(
        "/api/resumes",
        data=data,
        files=files,
        headers={"x-test-client-ip": "198.51.100.10"},
    )

    assert first_ip.status_code == 200
    assert different_ip.status_code == 200
    assert repeated_first_ip.status_code == 429


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


@pytest.mark.parametrize(
    ("endpoint", "bucket", "payload", "service_name"),
    [
        (
            "submit",
            "public_code_submit",
            {"code": "print(1)", "language": "python"},
            "submit_public_code",
        ),
        (
            "submit-essay",
            "public_essay_submit",
            {"answers": [{"question_id": "q1", "answer": "long answer"}]},
            "submit_essay_answers",
        ),
    ],
)
def test_high_cost_public_submission_is_limited_before_business_execution(
    client, monkeypatch, endpoint, bucket, payload, service_name
):
    from app.core.rate_limit import ApplicationRateLimiter, RateLimit
    from app.models.models import CodingSubmissionStatus
    from app.routes import coding_tests

    client.app.state.rate_limiter = ApplicationRateLimiter(
        policies={bucket: RateLimit(limit=1, window_seconds=60)}
    )
    monkeypatch.setattr(coding_tests, "_validate_public_request", lambda *_args: None)
    calls = []

    def fake_submit(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(
            id=uuid4(),
            coding_test_id=uuid4(),
            language="python",
            run_result={},
            passed=True,
            score=100,
            status=CodingSubmissionStatus.SUBMITTED,
            created_at=datetime.utcnow(),
            submitted_at=datetime.utcnow(),
        )

    monkeypatch.setattr(coding_tests, service_name, fake_submit)
    token = "a" * 43

    first = client.post(f"/api/public/coding-tests/{token}/{endpoint}", json=payload)
    limited = client.post(f"/api/public/coding-tests/{token}/{endpoint}", json=payload)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert calls == [True]


def test_production_access_logs_cannot_record_public_token_urls():
    root = Path(__file__).parents[2]
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    nginx = (root / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    caddy = (root / "Caddyfile").read_text(encoding="utf-8")

    assert "--no-access-log" in compose
    assert "TRUSTED_PROXY_CIDRS" in compose
    assert "header_up X-Forwarded-For {remote_host}" in caddy
    assert "map $request_uri $loggable_request" in nginx
    assert "map $uri $loggable_request" not in nginx
    assert "access_log /var/log/nginx/access.log main if=$loggable_request;" in nginx
    for prefix in (
        "/api/public/",
        "/public/coding-tests/",
        "/public/review/",
        "/offer-confirm/",
    ):
        assert prefix in nginx
    assert nginx.count("access_log off;") >= 2
    assert nginx.count("error_log /dev/null crit;") >= 2
    verifier = (
        root / "scripts" / "verify-nginx-token-logs.sh"
    ).read_text(encoding="utf-8")
    windows_verifier = (
        root / "scripts" / "verify-nginx-token-logs.ps1"
    ).read_text(encoding="utf-8")
    for token_kind in ("coding", "offer", "review"):
        assert token_kind in verifier
        assert token_kind in windows_verifier
    assert "docker logs" in verifier
    assert "docker logs" in windows_verifier
    assert "SENTINEL" in verifier
    assert "sentinel" in windows_verifier
    for script in (verifier, windows_verifier):
        assert "SAFE_SENTINEL" in script or "safeSentinel" in script
        assert "State.Running" in script
        assert "200" in script
        assert "404" in script
        assert "502" in script
        assert "504" in script
    assert "[ ! -L \"$file\" ]" in verifier
    assert "cat \"$file\"" in verifier
    assert r"/^[[:space:]]*HTTP\/1\.[01] [0-9][0-9][0-9]/" in verifier
    assert "Get-Content" not in windows_verifier


def test_rollout_waits_for_caddy_ca_before_each_certificate_export():
    root = Path(__file__).parents[2]
    rollout = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")

    exports = [
        index
        for index in range(len(rollout))
        if rollout.startswith(
            "caddy:/data/caddy/pki/authorities/local/root.crt",
            index,
        )
    ]
    assert len(exports) == 2
    for export_index in exports:
        preceding = rollout[max(0, export_index - 1200):export_index]
        assert "CADDY_CA_READY" in preceding
        assert "30" in preceding
        assert "test -s /data/caddy/pki/authorities/local/root.crt" in preceding


def test_rollout_host_allowlist_and_https_order_match_production_policy():
    root = Path(__file__).parents[2]
    rollout = (
        root / "docs" / "deployment" / "multi-tenant-production-rollout.md"
    ).read_text(encoding="utf-8")

    drill_start = rollout.index("export DRILL_API_PORT")
    drill_end = rollout.index("数据库、文件、18 表对比", drill_start)
    drill = rollout[drill_start:drill_end]
    assert "-e UNIFIED_ENTRY_HOSTS=127.0.0.1" in drill

    formal_start = rollout.index("## 5.")
    formal_end = rollout.index("## 7.", formal_start)
    formal = rollout[formal_start:formal_end]
    assert formal.index("up -d caddy") < formal.index("PLATFORM_TOKEN=")
    assert "--cacert" in formal
    assert "https://interview.careray.com/api/platform/auth/login" in formal
    assert "http://127.0.0.1/api/platform/auth/login" not in formal


def test_postgres_integration_does_not_replace_the_production_role_script():
    root = Path(__file__).parents[2]
    integration = (
        root / "backend" / "tests" / "integration" / "test_postgres_rls.py"
    ).read_text(encoding="utf-8")
    runner = (
        root / "backend" / "tests" / "integration" / "run_postgres_suite.sh"
    ).read_text(encoding="utf-8")

    assert "_initialize_roles_directly" not in integration
    assert "/docker-entrypoint-initdb.d/01-app-roles.sh" in integration
    assert "COPY (SELECT '') TO PROGRAM" in integration
    assert "/docker-entrypoint-initdb.d/01-app-roles.sh" in runner
    assert "TEST_POSTGRES_ROLE_SCRIPT_VIA_COPY_PROGRAM=1" in runner
    assert runner.index("01-app-roles.sh") < runner.index("pytest")


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
