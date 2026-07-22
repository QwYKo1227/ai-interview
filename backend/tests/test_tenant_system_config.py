from unittest.mock import MagicMock

import pytest

from app.config.tenant_session import TenantSession
from app.models.models import SystemConfig
from app.services import ai_service
from app.services.mail_service import MailService
from app.services.system_config_service import get_system_config
from app.utils.prompt_manager import PromptManager


def _tenant_db(db, tenant_id):
    return TenantSession(bind=db.get_bind(), tenant_id=tenant_id)


def test_system_config_is_selected_by_trusted_tenant_scope(db, tenant_a, tenant_b):
    db.add_all(
        [
            SystemConfig(
                tenant_id=tenant_a.id,
                singleton_key=True,
                smtp_host="smtp.a.test",
                llm_model="model-a",
                prompt_configs={"tenant_prompt": {"system": "A", "user": "A {name}"}},
            ),
            SystemConfig(
                tenant_id=tenant_b.id,
                singleton_key=True,
                smtp_host="smtp.b.test",
                llm_model="model-b",
                prompt_configs={"tenant_prompt": {"system": "B", "user": "B {name}"}},
            ),
        ]
    )
    db.commit()

    with _tenant_db(db, tenant_a.id) as tenant_db:
        assert get_system_config(tenant_db).smtp_host == "smtp.a.test"
        assert ai_service._get_llm_config(tenant_db)["llm_model"] == "model-a"
        assert PromptManager().get_prompt("tenant_prompt", db=tenant_db, name="Alice") == {
            "system": "A",
            "user": "A Alice",
        }

    with _tenant_db(db, tenant_b.id) as tenant_db:
        assert get_system_config(tenant_db).smtp_host == "smtp.b.test"
        assert ai_service._get_llm_config(tenant_db)["llm_model"] == "model-b"
        assert PromptManager().get_prompt("tenant_prompt", db=tenant_db, name="Bob") == {
            "system": "B",
            "user": "B Bob",
        }


def test_get_system_config_rejects_unscoped_or_forged_session(db, tenant_a):
    db.info["tenant_id"] = tenant_a.id
    with pytest.raises(RuntimeError, match="tenant-scoped"):
        get_system_config(db)


def test_mail_service_snapshots_each_tenants_smtp_configuration(db, tenant_a, tenant_b):
    db.add_all(
        [
            SystemConfig(
                tenant_id=tenant_a.id,
                smtp_host="smtp.a.test",
                smtp_port=465,
                smtp_username="user-a",
                smtp_password="secret-a",
                smtp_security="ssl",
                mail_from="a@test",
                mail_enabled=True,
            ),
            SystemConfig(
                tenant_id=tenant_b.id,
                smtp_host="smtp.b.test",
                smtp_port=587,
                smtp_username="user-b",
                smtp_password="secret-b",
                smtp_security="starttls",
                mail_from="b@test",
                mail_enabled=True,
            ),
        ]
    )
    db.commit()

    with _tenant_db(db, tenant_a.id) as tenant_db:
        service_a = MailService(tenant_db)
    with _tenant_db(db, tenant_b.id) as tenant_db:
        service_b = MailService(tenant_db)

    assert (service_a.config.smtp_host, service_a.config.smtp_username) == (
        "smtp.a.test",
        "user-a",
    )
    assert (service_b.config.smtp_host, service_b.config.smtp_username) == (
        "smtp.b.test",
        "user-b",
    )


def test_secret_values_are_not_logged_on_smtp_failure(monkeypatch, caplog):
    config = MagicMock()
    config.smtp_host = "smtp.test"
    config.smtp_port = 465
    config.smtp_username = "tenant-user"
    config.smtp_password = "TOP-SECRET-SMTP-PASSWORD"
    config.smtp_security = "ssl"
    config.mail_from = "sender@test"
    config.mail_from_name = "Tenant"
    config.mail_enabled = True
    monkeypatch.setattr("app.services.mail_service.get_system_config", lambda _db: config)
    monkeypatch.setattr(
        "app.services.mail_service.smtplib.SMTP_SSL",
        MagicMock(side_effect=RuntimeError("connection failed")),
    )

    with caplog.at_level("ERROR"):
        assert MailService(MagicMock()).send_test_email("recipient@test.com") is False

    assert "TOP-SECRET-SMTP-PASSWORD" not in caplog.text


def test_llm_exception_does_not_print_secret(monkeypatch, capsys):
    secret = "TOP-SECRET-LLM-KEY"
    monkeypatch.setattr(
        ai_service.prompt_manager,
        "get_prompt",
        lambda *_args, **_kwargs: {"system": "system", "user": "user"},
    )
    monkeypatch.setattr(
        ai_service,
        "_get_llm_config",
        lambda _db=None: {
            "llm_provider": "openai",
            "llm_base_url": "https://llm.test",
            "llm_model": "tenant-model",
            "llm_temperature": 0.2,
            "llm_max_tokens": None,
            "llm_api_key": secret,
        },
    )
    monkeypatch.setattr(
        ai_service, "_get_client", MagicMock(side_effect=RuntimeError(secret))
    )

    assert ai_service.analyze_resume("resume", "position", db=MagicMock()) == {}
    assert secret not in capsys.readouterr().out
