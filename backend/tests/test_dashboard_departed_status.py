from datetime import datetime, timedelta, timezone

from app.models.models import Offer, OfferStatus, Resume, ResumeStatus
from app.services.dashboard_service import (
    get_overview,
    get_position_analytics,
    get_recent_activities,
    get_recruitment_funnel,
    get_timeline_analytics,
)


def test_dashboard_splits_current_cumulative_and_departed_hires(
    db,
    test_position,
    test_resume,
    test_user,
):
    now = datetime.now(timezone.utc)
    test_resume.status = ResumeStatus.DEPARTED
    test_resume.parsed_at = now - timedelta(days=20)
    current_resume = Resume(
        tenant_id=test_position.tenant_id,
        position_id=test_position.id,
        candidate_name="Current Employee",
        email="current@example.com",
        status=ResumeStatus.COMPLETED,
        parsed_at=now - timedelta(days=15),
    )
    db.add(current_resume)
    db.flush()
    db.add_all([
        Offer(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            position_id=test_position.id,
            candidate_name=test_resume.candidate_name,
            candidate_email=test_resume.email,
            position_title=test_position.title,
            status=OfferStatus.DEPARTED,
            actual_onboarded_at=now - timedelta(days=7),
            departed_at=now - timedelta(days=1),
            created_by=test_user.id,
        ),
        Offer(
            tenant_id=test_position.tenant_id,
            resume_id=current_resume.id,
            position_id=test_position.id,
            candidate_name=current_resume.candidate_name,
            candidate_email=current_resume.email,
            position_title=test_position.title,
            status=OfferStatus.ACCEPTED,
            actual_onboarded_at=now - timedelta(days=2),
            created_by=test_user.id,
        ),
    ])
    db.commit()

    stages = {item["stage"]: item for item in get_recruitment_funnel(db)["stages"]}
    assert stages["current_employed"]["count"] == 1
    assert stages["cumulative_onboarded"]["count"] == 2
    assert stages["departed"]["count"] == 1

    position = next(
        item for item in get_position_analytics(db)["positions"]
        if item["id"] == str(test_position.id)
    )
    assert position["current_employed"] == 1
    assert position["cumulative_onboarded"] == 2
    assert position["departed"] == 1

    metrics = get_overview(db)["metrics"]
    assert metrics["current_employed"] == 1
    assert metrics["cumulative_onboarded"] == 2
    assert metrics["departed"] == 1

    timeline = get_timeline_analytics(db, days=30)
    assert sum(item["hires"] for item in timeline["timeline"]) == 2
    assert sum(item["departures"] for item in timeline["timeline"]) == 1

    departed_activity = next(
        item for item in get_recent_activities(db)
        if item["id"] == str(test_resume.id)
    )
    assert departed_activity["status"] == "已离职"
