from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.interview_timing import require_interview_start_time


SCHEDULED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def interview_at_scheduled_time():
    return SimpleNamespace(interview_time=SCHEDULED_AT)


def test_start_is_blocked_before_fifteen_minute_window():
    with pytest.raises(HTTPException) as error:
        require_interview_start_time(
            interview_at_scheduled_time(),
            now=SCHEDULED_AT - timedelta(minutes=15, seconds=1),
        )

    assert error.value.status_code == 409
    assert '距离“开始面试”按钮启用还需等待 1 分钟' in error.value.detail


def test_start_is_allowed_exactly_fifteen_minutes_early():
    require_interview_start_time(
        interview_at_scheduled_time(),
        now=SCHEDULED_AT - timedelta(minutes=15),
    )


def test_start_is_allowed_after_scheduled_time():
    require_interview_start_time(
        interview_at_scheduled_time(),
        now=SCHEDULED_AT + timedelta(minutes=1),
    )
