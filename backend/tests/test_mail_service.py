from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

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
