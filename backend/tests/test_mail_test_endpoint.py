from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routes.settings import test_mail_settings as send_mail_test_request
from app.schemas.settings import MailTestRequest


def test_mail_test_endpoint_sends_to_requested_recipient():
    mail_service = MagicMock()
    mail_service.config.is_valid.return_value = True
    mail_service.send_test_email.return_value = True

    with patch("app.services.mail_service.get_mail_service", return_value=mail_service):
        response = send_mail_test_request(
            payload=MailTestRequest(recipient="recipient@example.com"),
            db=MagicMock(),
            _current_user=MagicMock(),
        )

    mail_service.send_test_email.assert_called_once_with("recipient@example.com")
    assert response == {"message": "测试邮件发送成功"}


def test_mail_test_endpoint_returns_502_when_smtp_send_fails():
    mail_service = MagicMock()
    mail_service.config.is_valid.return_value = True
    mail_service.send_test_email.return_value = False

    with patch("app.services.mail_service.get_mail_service", return_value=mail_service):
        with pytest.raises(HTTPException) as exc_info:
            send_mail_test_request(
                payload=MailTestRequest(recipient="recipient@example.com"),
                db=MagicMock(),
                _current_user=MagicMock(),
            )

    assert exc_info.value.status_code == 502


def test_mail_test_request_rejects_invalid_recipient():
    with pytest.raises(ValidationError):
        MailTestRequest(recipient="not-an-email")
