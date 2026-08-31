from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.models.models import (
    Offer,
    OfferStatus,
    PositionEvent,
    PositionEventType,
    RecruitmentHcSlot,
    ResumeStatusEvent,
    ResumeStatus,
)
from app.services.recruitment_performance_service import available_periods, calculate_overview, sync_position_slots


def test_available_periods_span_position_history_through_current_quarter(db, test_position):
    test_position.created_at = datetime(2026, 4, 10)
    db.commit()

    result = available_periods(db, today=date(2026, 8, 17))

    assert result.periods == ["2026-Q2", "2026-Q3"]
    assert result.default_period == "2026-Q3"


def test_hr_can_load_period_options(client, auth_headers, test_position):
    response = client.get("/api/recruitment-performance/periods", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["default_period"] in response.json()["periods"]


def test_new_hc_slots_use_their_actual_assignment_time(db, test_position):
    position_created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    initial_slots = sync_position_slots(db, test_position, assigned_at=position_created_at)
    test_position.headcount = 3
    added_at = datetime(2026, 8, 18, 9, tzinfo=timezone.utc)

    slots = sync_position_slots(db, test_position, assigned_at=added_at)

    assert [slot.assigned_at for slot in slots[:2]] == [position_created_at, position_created_at]
    assert slots[2].assigned_at == added_at


def test_hr_sees_only_own_performance(client, auth_headers, test_position):
    response = client.get("/api/recruitment-performance/me?period=2026-Q3", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "2026-Q3"
    assert body["status"] == "trial"
    assert [person["user_id"] for person in body["people"]] == [str(test_position.hiring_manager_id)]


def test_interviewer_cannot_access_performance(client, interviewer_auth_headers):
    response = client.get("/api/recruitment-performance/me?period=2026-Q3", headers=interviewer_auth_headers)

    assert response.status_code == 403


def test_result_coefficient_applies_to_complete_quarter_holding_days(
    db, test_position, test_resume, test_user
):
    test_position.created_at = datetime(2026, 7, 1)
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    sync_position_slots(db, test_position, assigned_at=test_position.created_at)
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        user=test_user,
        now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        use_settlement=False,
    )

    slot = overview.people[0].positions[0].slots[0]
    assert slot.effective_held_days == 10
    assert slot.result_coefficient == 0.6
    assert slot.score == slot.task_points * slot.time_coefficient * 0.6


def test_reassigned_position_resets_effective_holding_but_keeps_full_cycle_days(
    db, test_position, test_user, test_admin
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    owner_changed_at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    cutoff = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add_all([
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.INITIAL_OWNER,
            new_value=str(test_user.id),
            occurred_at=round_started_at,
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_user.id),
            new_value=str(test_admin.id),
            occurred_at=owner_changed_at,
        ),
    ])
    test_position.hiring_manager_id = test_admin.id
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        now=cutoff,
        use_settlement=False,
    )

    assert [person.user_id for person in overview.people] == [test_admin.id]
    assert len(overview.people[0].positions) == 1
    slots = overview.people[0].positions[0].slots
    assert {slot.actual_days for slot in slots} == {20}
    assert {slot.effective_held_days for slot in slots} == {10}


def test_first_decision_stage_owner_keeps_handoff_credit(
    db, test_position, test_resume, test_user, test_admin
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    milestone_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    owner_changed_at = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    cutoff = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add_all([
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.INITIAL_OWNER,
            new_value=str(test_user.id),
            occurred_at=round_started_at,
        ),
        ResumeStatusEvent(
            id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
            new_status=ResumeStatus.INTERVIEW_PASSED.value,
            source="test",
            occurred_at=milestone_at,
        ),
        ResumeStatusEvent(
            id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.INTERVIEW_IN_PROGRESS.value,
            new_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
            source="test",
            occurred_at=milestone_at,
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_user.id),
            new_value=str(test_admin.id),
            occurred_at=owner_changed_at,
        ),
    ])
    test_position.hiring_manager_id = test_admin.id
    test_user.is_active = False
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        now=cutoff,
        use_settlement=False,
    )

    people = {person.user_id: person for person in overview.people}
    assert set(people) == {test_user.id, test_admin.id}
    current_slot = people[test_admin.id].positions[0].slots[0]
    assert current_slot.actual_days == 20
    assert current_slot.effective_held_days == 10
    assert len(people[test_user.id].handoff_credits) == 1
    assert people[test_user.id].is_active is False
    credit = people[test_user.id].handoff_credits[0]
    assert credit.position_id == test_position.id
    assert credit.transferred_at == owner_changed_at
    assert credit.task_points == 40
    assert credit.score == pytest.approx(28.8)
    assert len(credit.slots) == 1
    assert credit.slots[0].candidate_name == test_resume.candidate_name
    assert people[test_user.id].task_points == credit.task_points
    assert people[test_user.id].score == credit.score


def test_position_reassigned_back_to_same_owner_has_no_frozen_handoff_credit(
    db, test_position, test_resume, test_user, test_admin
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    test_resume.status = ResumeStatus.OFFER_ACCEPTED
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add_all([
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.INITIAL_OWNER,
            new_value=str(test_user.id),
            occurred_at=round_started_at,
        ),
        ResumeStatusEvent(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
            new_status=ResumeStatus.INTERVIEW_PASSED.value,
            source="test",
            occurred_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_user.id),
            new_value=str(test_admin.id),
            occurred_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_admin.id),
            new_value=str(test_user.id),
            occurred_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        ),
        Offer(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            position_id=test_position.id,
            candidate_name=test_resume.candidate_name,
            candidate_email=test_resume.email,
            position_title=test_position.title,
            status=OfferStatus.ACCEPTED,
            accepted_at=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
            created_by=test_user.id,
        ),
    ])
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        now=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
        use_settlement=False,
    )

    assert [person.user_id for person in overview.people] == [test_user.id]
    assert len(overview.people[0].positions) == 1
    candidate_slot = next(
        slot for slot in overview.people[0].positions[0].slots
        if slot.candidate_name == test_resume.candidate_name
    )
    assert candidate_slot.actual_days == 15
    assert candidate_slot.effective_held_days == 10
    assert overview.people[0].positions[0].task_points > 0
    assert overview.people[0].handoff_credits == []


def test_zero_credit_at_first_handoff_expires_the_opportunity(
    db, test_position, test_resume, test_user, test_admin
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    test_position.hiring_manager_id = test_user.id
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add_all([
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.INITIAL_OWNER,
            new_value=str(test_user.id),
            occurred_at=round_started_at,
        ),
        ResumeStatusEvent(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
            new_status=ResumeStatus.INTERVIEW_PASSED.value,
            source="test",
            occurred_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        ),
        ResumeStatusEvent(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.INTERVIEW_PASSED.value,
            new_status=ResumeStatus.INTERVIEW_FAILED.value,
            source="test",
            occurred_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_user.id),
            new_value=str(test_admin.id),
            occurred_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ),
        ResumeStatusEvent(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.INTERVIEW_FAILED.value,
            new_status=ResumeStatus.INTERVIEW_PASSED.value,
            source="test",
            occurred_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        ),
        PositionEvent(
            tenant_id=test_position.tenant_id,
            position_id=test_position.id,
            event_type=PositionEventType.OWNER_CHANGED,
            old_value=str(test_admin.id),
            new_value=str(test_user.id),
            occurred_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        ),
    ])
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
        use_settlement=False,
    )

    assert all(not person.handoff_credits for person in overview.people)


def test_admin_can_publish_next_quarter_config(client, admin_auth_headers):
    payload = {
            "effective_year": 2026,
            "effective_quarter": 4,
            "target_days": {
                "campus": 30,
                "domestic_functional": 45,
                "domestic_rd": 75,
                "overseas": 90,
                "executive_expert": 120,
            },
            "time_coefficients": {
                "lte_80": 1.2,
                "80_90": 1.1,
                "90_100": 1,
                "100_110": 0.9,
                "110_130": 0.8,
                "130_150": 0.7,
                "gt_150": 0.5,
            },
            "result_coefficients": {
                "onboarded": 1,
                "offer_accepted": 0.9,
                "offer_pending": 0.8,
                "interview_passed": 0.6,
                "business_interview_completed": 0.4,
                "hr_interview_completed": 0.2,
                "open": 0,
            },
        }
    response = client.put(
        "/api/recruitment-performance/config",
        headers=admin_auth_headers,
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["version"] == 1

    revised = client.put("/api/recruitment-performance/config", headers=admin_auth_headers, json=payload)
    assert revised.status_code == 200
    assert revised.json()["version"] == 2


def test_owner_can_confirm_actual_onboarding(
    client, db, auth_headers, test_position, test_resume, test_user
):
    accepted_at = datetime.now(timezone.utc) - timedelta(days=1)
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        status=OfferStatus.ACCEPTED,
        accepted_at=accepted_at,
        created_by=test_user.id,
    )
    test_resume.status = ResumeStatus.OFFER_ACCEPTED
    db.add(offer)
    db.commit()

    response = client.post(
        f"/api/offers/{offer.id}/confirm-onboarding",
        headers=auth_headers,
        json={"actual_onboard_date": date.today().isoformat()},
    )

    assert response.status_code == 200
    db.refresh(test_resume)
    db.refresh(offer)
    assert test_resume.status == ResumeStatus.COMPLETED
    assert offer.actual_onboarded_at is not None
    assert db.query(RecruitmentHcSlot).filter(RecruitmentHcSlot.completed_at.isnot(None)).count() == 1


def test_owner_can_confirm_onboarding_on_same_beijing_date_as_offer_acceptance(
    client, db, auth_headers, test_position, test_resume, test_user
):
    accepted_at = datetime.now(timezone.utc)
    beijing_date = accepted_at.astimezone(timezone(timedelta(hours=8))).date()
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        status=OfferStatus.ACCEPTED,
        accepted_at=accepted_at,
        created_by=test_user.id,
    )
    test_resume.status = ResumeStatus.OFFER_ACCEPTED
    db.add(offer)
    db.commit()

    response = client.post(
        f"/api/offers/{offer.id}/confirm-onboarding",
        headers=auth_headers,
        json={"actual_onboard_date": beijing_date.isoformat()},
    )

    assert response.status_code == 200
