from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch
from datetime import datetime, timezone
from email import policy
from email.parser import Parser
import smtplib

import pytest

from app.services.mail_service import MailService


def _mail_config(smtp_security: str):
    return SimpleNamespace(
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        mail_from="sender@example.com",
        mail_from_name="招聘系统",
        mail_enabled=True,
        smtp_security=smtp_security,
    )


def _db_with_mail_config(smtp_security: str):
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = _mail_config(smtp_security)
    return db


@patch("app.services.mail_service.smtplib.SMTP_SSL")
@patch("app.services.mail_service.get_system_config")
def test_send_test_email_uses_ssl_smtp(mock_get_config, mock_smtp_ssl):
    server = MagicMock()
    mock_smtp_ssl.return_value = server
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())

    assert service.send_test_email("recipient@example.com") is True

    mock_smtp_ssl.assert_called_once_with(
        "smtp.example.com", 465, context=ANY, timeout=15
    )
    server.login.assert_called_once_with("smtp-user", "smtp-password")
    server.sendmail.assert_called_once()
    server.quit.assert_called_once()


@patch("app.services.mail_service.smtplib.SMTP")
@patch("app.services.mail_service.get_system_config")
def test_send_test_email_uses_starttls_smtp(mock_get_config, mock_smtp):
    server = MagicMock()
    mock_smtp.return_value = server
    mock_get_config.return_value = _mail_config("starttls")
    service = MailService(MagicMock())

    assert service.send_test_email("recipient@example.com") is True

    mock_smtp.assert_called_once_with("smtp.example.com", 465, timeout=15)
    assert server.ehlo.call_count == 2
    server.starttls.assert_called_once_with(context=ANY)
    server.login.assert_called_once_with("smtp-user", "smtp-password")
    server.sendmail.assert_called_once()
    server.quit.assert_called_once()


@patch("app.services.mail_service.smtplib.SMTP_SSL")
@patch("app.services.mail_service.get_system_config")
def test_send_test_email_stays_successful_when_quit_fails_after_delivery(mock_get_config, mock_smtp_ssl):
    server = MagicMock()
    server.quit.side_effect = OSError("connection already closed")
    mock_smtp_ssl.return_value = server
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())

    assert service.send_test_email("recipient@example.com") is True

    server.sendmail.assert_called_once()


@patch("app.services.mail_service.get_system_config")
@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPAuthenticationError(535, b"SMTP-PASSWORD-TOKEN"),
        smtplib.SMTPException("SMTP-PASSWORD-TOKEN"),
        RuntimeError("SMTP-PASSWORD-TOKEN"),
    ],
    ids=["authentication", "protocol", "general"],
)
def test_smtp_delivery_errors_do_not_log_secret(mock_get_config, caplog, error):
    secret = "SMTP-PASSWORD-TOKEN"
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())
    service._create_smtp_connection = MagicMock(
        side_effect=error
    )

    with caplog.at_level("ERROR"):
        assert service.send_test_email("recipient@example.com") is False

    assert secret not in caplog.text


@patch("app.services.mail_service.get_system_config")
def test_smtp_close_error_does_not_log_secret_for_shared_send_path(mock_get_config, caplog):
    secret = "SMTP-PASSWORD-TOKEN"
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())
    server = MagicMock()
    server.quit.side_effect = OSError(secret)
    service._create_smtp_connection = MagicMock(return_value=server)

    with caplog.at_level("WARNING"):
        assert service._send_email(
            "recipient@example.com", "subject", "<p>body</p>"
        ) is True

    assert secret not in caplog.text


@patch("app.services.mail_service.get_system_config")
def test_shared_send_path_preserves_the_preview_html_in_the_mime_part(mock_get_config):
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())
    server = MagicMock()
    service._create_smtp_connection = MagicMock(return_value=server)
    preview_html = '<table role="presentation"><tr><td><a href="https://example.com/review">立即审核</a></td></tr></table>'

    assert service._send_email("recipient@example.com", "评审邀请", preview_html)

    raw_message = server.sendmail.call_args.args[2]
    parsed = Parser(policy=policy.default).parsestr(raw_message)
    html_part = next(
        part for part in parsed.walk() if part.get_content_type() == "text/html"
    )
    assert html_part.get_content().strip() == preview_html


@patch("app.services.mail_service.get_system_config")
def test_interview_invitation_uses_china_time_and_omits_contact_and_signature(
    mock_get_config,
):
    mock_get_config.return_value = _mail_config("ssl")
    service = MailService(MagicMock())
    service._send_email = MagicMock(return_value=True)

    assert service.send_interview_invitation(
        interview=MagicMock(),
        candidate_email="candidate@example.com",
        candidate_name="候选人",
        position_title="后端工程师",
        interview_time=datetime(2026, 7, 29, 2, 30, tzinfo=timezone.utc),
    ) is True

    html_content = service._send_email.call_args.args[2]
    assert "2026年07月29日 10:30" in html_content
    assert "联系人" not in html_content
    assert "© 公司 人力资源部" not in html_content
    assert 'bgcolor="#667eea"' in html_content
    assert 'data-section="interview-tips-table"' in html_content
    assert 'bgcolor="#fff3cd"' in html_content
    assert '<div style="background-color: #fff3cd' not in html_content
    assert "border-left: 4px solid #ffc107" in html_content
    assert 'width="4" bgcolor="#ffc107"' not in html_content
    assert "请携带个人简历及相关证件" not in html_content


def test_cancellation_notification_reaches_candidate_and_interviewer(
    db,
    test_interview,
    test_resume,
    test_interviewer,
):
    test_interview.cancel_reason = "候选人申请改期"
    db.commit()
    service = MailService.__new__(MailService)
    service.db = db
    service._send_email = MagicMock(return_value=True)

    result = service.send_interview_cancellation_for_interview(test_interview)

    assert result["success"] is True
    recipients = {call.args[0] for call in service._send_email.call_args_list}
    assert recipients == {test_resume.email, test_interviewer.email}
    html = service._send_email.call_args_list[0].args[2]
    assert "候选人申请改期" in html
    assert "原面试时间" in html
