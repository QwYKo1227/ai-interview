from datetime import datetime, timedelta, timezone

from app.models.models import (
    DepartmentReview,
    Interview,
    InterviewPanel,
    InterviewStatus,
)
from app.services.dashboard_service import get_interviewer_dashboard


def test_interviewer_dashboard_is_scoped_to_assigned_work(
    db, test_interviewer, test_user, test_position, test_resume
):
    now = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
    db.add_all([
        DepartmentReview(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            reviewer_id=test_interviewer.id,
            is_completed=False,
        ),
        DepartmentReview(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            reviewer_id=test_user.id,
            is_completed=False,
        ),
    ])

    upcoming = Interview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        interview_time=now + timedelta(hours=2),
        interview_end_time=now + timedelta(hours=3),
        status=InterviewStatus.SCHEDULED,
        lifecycle_state="scheduled",
    )
    ended = Interview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        interview_time=now - timedelta(hours=2),
        interview_end_time=now - timedelta(hours=1),
        status=InterviewStatus.COMPLETED,
        lifecycle_state="ended",
    )
    unassigned = Interview(
        tenant_id=test_resume.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        interview_time=now + timedelta(hours=4),
        interview_end_time=now + timedelta(hours=5),
        status=InterviewStatus.SCHEDULED,
        lifecycle_state="scheduled",
    )
    db.add_all([upcoming, ended, unassigned])
    db.flush()
    db.add_all([
        InterviewPanel(
            tenant_id=test_resume.tenant_id,
            interview_id=upcoming.id,
            interviewer_id=test_interviewer.id,
            is_submitted=False,
        ),
        InterviewPanel(
            tenant_id=test_resume.tenant_id,
            interview_id=ended.id,
            interviewer_id=test_interviewer.id,
            is_submitted=False,
        ),
        InterviewPanel(
            tenant_id=test_resume.tenant_id,
            interview_id=unassigned.id,
            interviewer_id=test_user.id,
            is_submitted=False,
        ),
    ])
    db.commit()

    result = get_interviewer_dashboard(db, test_interviewer, now=now)

    assert result["metrics"] == {
        "pending_reviews": 1,
        "today_interviews": 2,
        "pending_feedback": 1,
    }
    assert [item["id"] for item in result["upcoming_interviews"]] == [str(upcoming.id)]
    assert result["upcoming_interviews"][0]["candidate_name"] == test_resume.candidate_name
    assert result["upcoming_interviews"][0]["position_title"] == test_position.title
