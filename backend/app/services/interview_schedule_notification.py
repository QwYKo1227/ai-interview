"""Short-lived authorization for schedule notification recipients."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.security import ALGORITHM, SECRET_KEY
from app.models.models import Interview
from app.schemas.interview import InterviewScheduleUpdate


TOKEN_TYPE = "interview_schedule_notification"
TOKEN_TTL = timedelta(minutes=15)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _schedule_snapshot(
    *,
    panel_members,
    interview_time: datetime,
    interview_type: str,
    interview_location: str | None,
    meeting_link: str | None,
) -> dict:
    return {
        "panel_members": sorted(str(member_id) for member_id in panel_members),
        "interview_time": _utc_iso(interview_time),
        "interview_type": interview_type,
        "interview_location": (interview_location or "").strip(),
        "meeting_link": (meeting_link or "").strip(),
    }


def _proposed_snapshot(schedule: InterviewScheduleUpdate) -> dict:
    return _schedule_snapshot(
        panel_members=schedule.panel_members,
        interview_time=schedule.interview_time,
        interview_type=schedule.interview_type,
        interview_location=schedule.interview_location,
        meeting_link=schedule.meeting_link,
    )


def _current_snapshot(interview: Interview) -> dict:
    return _schedule_snapshot(
        panel_members=interview.panel_members or [],
        interview_time=interview.interview_time,
        interview_type=interview.interview_type,
        interview_location=interview.interview_location,
        meeting_link=interview.meeting_link,
    )


def issue_schedule_notification_token(
    interview: Interview,
    schedule: InterviewScheduleUpdate,
    recipient_ids: set[UUID],
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(interview.id),
            "tenant_id": str(interview.tenant_id),
            "token_type": TOKEN_TYPE,
            "schedule": _proposed_snapshot(schedule),
            "recipient_ids": sorted(str(recipient_id) for recipient_id in recipient_ids),
            "iat": now,
            "exp": now + TOKEN_TTL,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def validate_schedule_notification_token(
    raw_token: str,
    interview: Interview,
    recipient_ids: list[UUID],
) -> None:
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 4096:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid schedule preview")
    try:
        claims = jwt.decode(
            raw_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require_sub": True, "require_exp": True},
        )
    except JWTError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired schedule preview",
        ) from error

    if (
        claims.get("token_type") != TOKEN_TYPE
        or claims.get("sub") != str(interview.id)
        or claims.get("tenant_id") != str(interview.tenant_id)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid schedule preview")
    if claims.get("schedule") != _current_snapshot(interview):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Schedule changed after the notification preview",
        )

    requested = [str(recipient_id) for recipient_id in recipient_ids]
    allowed = claims.get("recipient_ids")
    if (
        not isinstance(allowed, list)
        or len(requested) != len(set(requested))
        or not set(requested).issubset(set(allowed))
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Notification recipient was not included in the schedule preview",
        )
