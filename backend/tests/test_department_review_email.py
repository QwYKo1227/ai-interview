from unittest.mock import MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient
from app.services.mail_service import MailService
from app.schemas.resume import DepartmentReviewEmailPreviewRequest
from pydantic import ValidationError
import pytest


def test_department_review_email_preview_rejects_a_mismatched_review_url():
    with pytest.raises(ValidationError, match="评审链接与评审令牌不匹配"):
        DepartmentReviewEmailPreviewRequest(
            public_token="a" * 40,
            review_url="https://recruiting.example.com/public/review/" + "b" * 40,
        )

def test_department_review_email_preview_contains_reviewer_and_public_link(
    client: TestClient,
    test_resume,
    test_interviewer,
    auth_headers,
    db,
):
    test_resume.ai_review = "AI 建议重点核实稳定性"
    test_resume.hr_review = "请重点关注跨部门协作经验"
    db.commit()

    created = client.post(
        f"/api/resumes/{test_resume.id}/department-reviews",
        data={"reviewer_id": str(test_interviewer.id)},
        headers=auth_headers,
    )
    assert created.status_code == status.HTTP_200_OK
    review = created.json()
    expected_review_url = (
        f"https://recruiting.example.com/public/review/{review['public_token']}"
    )

    with patch("app.services.mail_service.get_mail_service", side_effect=MailService):
        response = client.post(
            f"/api/resumes/{test_resume.id}/department-reviews/{review['id']}/email-preview",
            json={
                "public_token": review["public_token"],
                "review_url": expected_review_url,
            },
            headers=auth_headers,
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["review_id"] == review["id"]
    assert payload["to_email"] == test_interviewer.email
    assert payload["reviewer_name"] == test_interviewer.full_name
    assert test_resume.position.title in payload["subject"]
    assert test_resume.candidate_name in payload["content"]
    assert f'href="{expected_review_url}"' in payload["content"]
    assert '<table role="presentation"' in payload["content"]
    assert 'data-section="review-details-table"' in payload["content"]
    assert "linear-gradient" not in payload["content"]
    assert "HR 评语" in payload["content"]
    assert "请重点关注跨部门协作经验" in payload["content"]
    assert "AI 初筛意见" not in payload["content"]
    assert "AI 建议重点核实稳定性" not in payload["content"]


def test_department_review_email_is_sent_to_assigned_reviewer(
    client: TestClient,
    test_resume,
    test_interviewer,
    auth_headers,
):
    created = client.post(
        f"/api/resumes/{test_resume.id}/department-reviews",
        data={"reviewer_id": str(test_interviewer.id)},
        headers=auth_headers,
    )
    assert created.status_code == status.HTTP_200_OK
    review = created.json()
    mail_service = MagicMock()
    mail_service._send_email.return_value = True

    with patch("app.services.mail_service.get_mail_service", return_value=mail_service):
        response = client.post(
            f"/api/resumes/{test_resume.id}/department-reviews/{review['id']}/send-email",
            json={"subject": "请评审", "content": "<p>评审内容</p>"},
            headers=auth_headers,
        )

    assert response.status_code == status.HTTP_200_OK
    mail_service._send_email.assert_called_once_with(
        to_email=test_interviewer.email,
        subject="请评审",
        html_content="<p>评审内容</p>",
    )
