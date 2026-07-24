import builtins
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import coding_test_service, resume_service
from app.services.mail_service import MailService
from app.utils.prompt_manager import PromptManager


@pytest.mark.parametrize(
    "reader,path",
    [
        (resume_service.read_file_content, "resume.pdf"),
        (coding_test_service._read_file_content, "question-bank.pdf"),
        (coding_test_service._read_file_content, "question-bank.docx"),
    ],
)
def test_worker_file_errors_do_not_emit_original_exception(
    monkeypatch, capsys, caplog, reader, path
):
    secret = "Authorization: Bearer SECRET"
    monkeypatch.setattr(coding_test_service.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(builtins, "open", MagicMock(side_effect=RuntimeError(secret)))
    if path.endswith(".docx"):
        monkeypatch.setattr(
            "docx.Document", MagicMock(side_effect=RuntimeError(secret))
        )

    with caplog.at_level(logging.ERROR):
        assert reader(path) == ""

    captured = capsys.readouterr()
    emitted = captured.out + captured.err + caplog.text
    assert secret not in emitted


@pytest.mark.parametrize(
    "template,kwargs",
    [
        ("{Authorization_Bearer_SECRET}", {}),
        ("{value}", {"value": None}),
    ],
    ids=["missing-variable", "format-error"],
)
def test_prompt_format_errors_never_return_or_print_secret(
    monkeypatch, capsys, template, kwargs
):
    secret = "Authorization: Bearer SECRET"
    manager = PromptManager()
    monkeypatch.setattr(
        manager,
        "_get_prompt_config",
        lambda *_args, **_kwargs: {"system": "system", "user": template},
    )
    if kwargs:
        class SecretFormatValue:
            def __format__(self, _format_spec):
                raise RuntimeError(secret)

        kwargs["value"] = SecretFormatValue()

    result = manager.get_prompt("tenant_prompt", **kwargs)

    emitted = capsys.readouterr().out + str(result)
    assert secret not in emitted
    assert "Authorization_Bearer_SECRET" not in emitted


def test_mail_template_error_does_not_log_smtp_secret(monkeypatch, caplog):
    secret = "smtp-password-SECRET"
    config = SimpleNamespace(
        smtp_host="smtp.test",
        smtp_port=465,
        smtp_username="user",
        smtp_password=secret,
        smtp_security="ssl",
        mail_from="sender@test.com",
        mail_from_name="Tenant",
        mail_enabled=True,
    )
    monkeypatch.setattr("app.services.mail_service.get_system_config", lambda _db: config)
    monkeypatch.setattr(
        "app.services.mail_service.jinja_env.get_template",
        MagicMock(side_effect=RuntimeError(secret)),
    )
    service = MailService(MagicMock())

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        service._render_template("interview_invitation.html", {})

    assert secret not in caplog.text


def test_hr_notification_error_does_not_log_original_exception(monkeypatch, caplog):
    secret = "smtp-password-SECRET"
    db = MagicMock()
    db.query.side_effect = RuntimeError(secret)

    with caplog.at_level(logging.ERROR):
        resume_service._send_hr_review_notification(db, MagicMock(), [MagicMock()])

    assert secret not in caplog.text
