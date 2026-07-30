from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.routes.interviews import EmailPreviewRequest
from app.schemas.interview import InterviewCreate


def test_interview_create_requires_interview_time():
    payload = {
        "resume_id": uuid4(),
        "position_id": uuid4(),
        "interview_time": datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        "interview_type": "onsite",
        "interview_location": "上海办公室",
    }
    payload.pop("interview_time")

    with pytest.raises(ValidationError):
        InterviewCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("interview_type", "required_field"),
    [("onsite", "interview_location"), ("video", "meeting_link")],
)
def test_interview_create_requires_details_for_selected_type(
    interview_type, required_field
):
    payload = {
        "resume_id": uuid4(),
        "position_id": uuid4(),
        "interview_time": datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        "interview_type": interview_type,
        "interview_location": "上海办公室",
        "meeting_link": "https://meeting.example.com/interview",
    }
    payload.pop(required_field)

    with pytest.raises(ValidationError):
        InterviewCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("interview_type", "required_field"),
    [("onsite", "interview_location"), ("video", "meeting_link")],
)
def test_email_preview_requires_details_for_selected_type(
    interview_type, required_field
):
    payload = {
        "resume_id": uuid4(),
        "position_id": uuid4(),
        "interview_time": "2026-08-01T10:00:00+08:00",
        "interview_type": interview_type,
        "interview_location": "上海办公室",
        "meeting_link": "https://meeting.example.com/interview",
    }
    payload.pop(required_field)

    with pytest.raises(ValidationError):
        EmailPreviewRequest.model_validate(payload)


@pytest.mark.parametrize("invalid_value", [None, "", "   "])
@pytest.mark.parametrize(
    ("interview_type", "required_field"),
    [("onsite", "interview_location"), ("video", "meeting_link")],
)
def test_required_detail_rejects_empty_values(
    interview_type, required_field, invalid_value
):
    common = {
        "resume_id": uuid4(),
        "position_id": uuid4(),
        "interview_type": interview_type,
        "interview_location": "上海办公室",
        "meeting_link": "https://meeting.example.com/interview",
    }
    common[required_field] = invalid_value

    with pytest.raises(ValidationError):
        InterviewCreate.model_validate({
            **common,
            "interview_time": datetime(
                2026, 8, 1, 10, 0, tzinfo=timezone.utc
            ),
        })
    with pytest.raises(ValidationError):
        EmailPreviewRequest.model_validate({
            **common,
            "interview_time": "2026-08-01T10:00:00+08:00",
        })


@pytest.mark.parametrize("interview_type", ["onsite", "video", "phone"])
def test_scheduling_fields_accept_values_required_by_type(interview_type):
    common = {
        "resume_id": uuid4(),
        "position_id": uuid4(),
        "interview_type": interview_type,
    }
    if interview_type == "onsite":
        common["interview_location"] = "上海办公室"
    elif interview_type == "video":
        common["meeting_link"] = "https://meeting.example.com/interview"

    InterviewCreate.model_validate({
        **common,
        "interview_time": datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
    })
    EmailPreviewRequest.model_validate({
        **common,
        "interview_time": "2026-08-01T10:00:00+08:00",
    })
