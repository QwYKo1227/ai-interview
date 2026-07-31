from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException

from app.models.models import Interview


CHINA_TIMEZONE = timezone(timedelta(hours=8))


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _remaining_text(seconds: int) -> str:
    minutes = ceil(seconds / 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remaining_minutes = divmod(minutes, 60)
    if remaining_minutes == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {remaining_minutes} 分钟"


def require_interview_start_time(
    interview: Interview,
    *,
    now: datetime | None = None,
) -> None:
    scheduled_at = as_utc(interview.interview_time)
    current = as_utc(now) if now is not None else datetime.now(timezone.utc)
    if scheduled_at is None or current >= scheduled_at:
        return

    remaining_seconds = max(1, ceil((scheduled_at - current).total_seconds()))
    scheduled_text = scheduled_at.astimezone(CHINA_TIMEZONE).strftime("%Y年%m月%d日 %H:%M")
    raise HTTPException(
        status_code=409,
        detail=(
            f"面试尚未到开始时间，计划开始时间为 {scheduled_text}，"
            f"还需等待 {_remaining_text(remaining_seconds)}"
        ),
    )
