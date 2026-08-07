from types import SimpleNamespace

from app.models.models import ResumeStatus, ReviewRecommendation
from app.schemas.resume import ResumeUpdate
from app.services.resume_service import (
    _send_hr_review_notification,
    extract_contact_details,
    override_rejection,
    update_resume,
)


def test_hr_is_notified_when_department_review_finishes(
    db,
    test_resume,
    test_user,
    monkeypatch,
):
    sent = []

    class FakeMailService:
        def __init__(self, _db):
            self.config = SimpleNamespace(is_valid=lambda: True)

        def _send_email(self, to_email, subject, html_content):
            sent.append((to_email, subject, html_content))
            return True

    monkeypatch.setattr("app.services.mail_service.MailService", FakeMailService)
    monkeypatch.setattr(
        "app.services.system_config_service.get_system_config",
        lambda _db: SimpleNamespace(frontend_url="https://hr.example.com"),
    )

    _send_hr_review_notification(
        db,
        test_resume,
        [SimpleNamespace(
            recommendation=ReviewRecommendation.RECOMMEND,
            overall_score=8,
        )],
    )

    assert len(sent) == 1
    assert sent[0][0] == test_user.email
    assert "部门评审完成" in sent[0][1]
    assert f"https://hr.example.com/resumes/{test_resume.id}" in sent[0][2]


def test_resume_update_accepts_numeric_parsed_experience():
    update = ResumeUpdate.model_validate(
        {
            "candidate_name": "张三",
            "email": "zhangsan@example.com",
            "contact": "13800138000",
            "highest_degree": "本科",
            "school": "测试大学",
            "major": "计算机科学",
            "years_of_experience": 5,
            "recent_company": "示例科技",
        }
    )

    assert update.years_of_experience == "5"


def test_extract_contact_details_falls_back_to_flat_ai_fields():
    contact, email = extract_contact_details(
        {
            "candidate_name": "张三",
            "contact": "13800138000",
            "email": "zhangsan@example.com",
        }
    )

    assert contact == "13800138000"
    assert email == "zhangsan@example.com"


def test_extract_contact_details_supports_nested_ai_fields():
    contact, email = extract_contact_details(
        {
            "contact_info": {
                "phone": "13900139000",
                "email": "nested@example.com",
            },
        }
    )

    assert contact == "13900139000"
    assert email == "nested@example.com"


def test_update_resume_merges_editable_extracted_fields(db, test_resume):
    test_resume.parsed_data = {"school": "原学校", "custom_field": "保留"}
    db.commit()

    updated = update_resume(
        db,
        test_resume.id,
        ResumeUpdate(
            highest_degree="本科",
            school="新学校",
            major="计算机科学",
            years_of_experience="5",
            recent_company="示例科技",
        ),
    )

    assert updated.parsed_data == {
        "school": "新学校",
        "highest_degree": "本科",
        "major": "计算机科学",
        "years_of_experience": "5",
        "recent_company": "示例科技",
        "custom_field": "保留",
    }


def test_override_ai_rejection_restores_pending_review(db, test_resume, test_user):
    test_resume.status = ResumeStatus.AUTO_REJECTED_PENDING_REVIEW
    db.commit()

    restored = override_rejection(db, test_resume.id, test_user.id)

    assert restored.status == ResumeStatus.PENDING_REVIEW
