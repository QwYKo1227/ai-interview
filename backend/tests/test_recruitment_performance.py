from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.models.models import (
    Interview,
    InterviewStatus,
    Offer,
    OfferStatus,
    Position,
    PositionEvent,
    PositionEventType,
    PositionStatus,
    RecruitmentHcSlot,
    RecruitmentPause,
    RecruitmentSettlement,
    Resume,
    ScreeningResult,
    ResumeStatusEvent,
    ResumeStatus,
)
from app.services.recruitment_performance_service import (
    _candidate_allocations,
    _result_stage,
    available_periods,
    calculate_overview,
    get_config,
    sync_position_slots,
)
from app.services.position_service import get_position_stats


@pytest.fixture
def status_history(db, test_position):
    test_position.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    sync_position_slots(db, test_position, assigned_at=test_position.created_at)

    def record(changes, *, baseline="published"):
        previous = baseline
        db.add(PositionEvent(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            event_type=PositionEventType.STATUS_BASELINE,
            new_value=baseline, occurred_at=test_position.created_at,
        ))
        for day, status in changes:
            db.add(PositionEvent(
                tenant_id=test_position.tenant_id, position_id=test_position.id,
                event_type=PositionEventType.STATUS_CHANGED,
                old_value=previous, new_value=status,
                occurred_at=datetime(2026, 7, day, 12, tzinfo=timezone.utc),
            ))
            previous = status
        test_position.status = PositionStatus(previous.lower())
        db.commit()

    return record


@pytest.mark.parametrize("cutoff_day,deducted,effective", [(10, 6, 4), (20, 16, 4)])
def test_paused_position_stops_accumulating_days_and_points(
    db, test_position, test_user, status_history, cutoff_day, deducted, effective,
):
    status_history([(5, "paused")])
    overview = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, cutoff_day, 13, tzinfo=timezone.utc), use_settlement=False,
    )

    person = overview.people[0]
    position = person.positions[0]
    assert {slot.deducted_days for slot in position.slots} == {deducted}
    assert {slot.effective_held_days for slot in position.slots} == {effective}
    assert {slot.actual_days for slot in position.slots} == {effective}
    assert position.task_points == test_position.priority * effective * test_position.headcount
    assert person.task_points == position.task_points


@pytest.mark.parametrize("changes,cutoff_day,deducted,effective", [
    ([(5, "paused"), (10, "published")], 12, 5, 7),
    ([(5, "paused"), (10, "published"), (12, "paused")], 15, 9, 6),
    ([(5, "paused"), (10, "published")], 7, 3, 4),
    ([(15, "cancelled")], 10, 0, 10),
])
def test_position_status_history_is_clipped_to_scoring_cutoff(
    db, test_position, test_user, status_history, changes, cutoff_day, deducted, effective,
):
    status_history(changes)
    position = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, cutoff_day, 13, tzinfo=timezone.utc), use_settlement=False,
    ).people[0].positions[0]

    assert {slot.deducted_days for slot in position.slots} == {deducted}
    assert {slot.effective_held_days for slot in position.slots} == {effective}
    assert position.task_points == test_position.priority * effective * test_position.headcount


def test_position_and_approved_hc_pauses_are_deducted_once(
    db, test_position, test_user, status_history,
):
    status_history([(5, "paused"), (10, "published")])
    slots = db.query(RecruitmentHcSlot).filter_by(position_id=test_position.id).all()
    for status, first, last in [("approved", 7, 11), ("approved", 8, 10), ("pending", 1, 20)]:
        db.add(RecruitmentPause(
            tenant_id=test_position.tenant_id, slot_id=slots[0].id, status=status,
            start_at=datetime(2026, 7, first, tzinfo=timezone.utc),
            end_at=datetime(2026, 7, last, tzinfo=timezone.utc), reason="test",
        ))
    db.commit()

    scores = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, 12, 13, tzinfo=timezone.utc), use_settlement=False,
    ).people[0].positions[0].slots

    by_id = {slot.slot_id: slot for slot in scores}
    assert by_id[slots[0].id].deducted_days == 7
    assert by_id[slots[0].id].effective_held_days == 5
    assert by_id[slots[1].id].deducted_days == 5
    assert by_id[slots[1].id].effective_held_days == 7


@pytest.mark.parametrize("baseline", ["PAUSED", "paused"])
def test_historical_paused_baseline_deducts_all_holding_days(
    db, test_user, status_history, baseline,
):
    status_history([], baseline=baseline)
    position = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, 10, 13, tzinfo=timezone.utc), use_settlement=False,
    ).people[0].positions[0]

    assert {slot.deducted_days for slot in position.slots} == {10}
    assert {slot.effective_held_days for slot in position.slots} == {0}
    assert position.task_points == 0


def test_cancelled_position_keeps_earned_score_in_overall_achievement_rate(
    db, test_position, test_resume, test_user, status_history,
):
    test_resume.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    db.add(ResumeStatusEvent(
        tenant_id=test_position.tenant_id, resume_id=test_resume.id,
        old_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
        new_status=ResumeStatus.INTERVIEW_PASSED.value, source="test",
        occurred_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
    ))
    status_history([(5, "cancelled")])
    active = Position(
        tenant_id=test_position.tenant_id, title="Active role", description="test",
        category=test_position.category, priority=4, headcount=1,
        status=PositionStatus.PUBLISHED, hiring_manager_id=test_user.id,
        created_at=test_position.created_at,
    )
    db.add(active)
    db.flush()
    sync_position_slots(db, active, assigned_at=active.created_at)
    db.commit()
    person = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, 10, 13, tzinfo=timezone.utc), use_settlement=False,
    ).people[0]

    cancelled = next(row for row in person.positions if row.position_id == test_position.id)
    assert cancelled.slots[0].result_coefficient == 0.6
    assert all(slot.task_points == 0 for slot in cancelled.slots)
    assert cancelled.score == pytest.approx(14.4)
    assert cancelled.task_points == 0
    assert cancelled.achievement_rate is None
    assert person.task_points == 40
    assert person.score == cancelled.score
    assert person.achievement_rate == pytest.approx(14.4 / 40)

    # Later candidate progress must not increase the retained cancelled score.
    test_resume.status = ResumeStatus.COMPLETED
    db.add(ResumeStatusEvent(
        tenant_id=test_position.tenant_id, resume_id=test_resume.id,
        old_status=ResumeStatus.INTERVIEW_PASSED.value,
        new_status=ResumeStatus.COMPLETED.value, source="test",
        occurred_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    ))
    db.commit()
    later = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, 20, 13, tzinfo=timezone.utc), use_settlement=False,
    ).people[0]
    assert later.task_points == 80
    assert later.score == person.score
    assert later.achievement_rate == pytest.approx(14.4 / 80)


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


@pytest.mark.parametrize("position_status", list(PositionStatus))
def test_performance_includes_current_position_status(
    client, db, auth_headers, test_position, position_status
):
    test_position.status = position_status
    db.commit()

    response = client.get("/api/recruitment-performance/me?period=2026-Q3", headers=auth_headers)

    assert response.status_code == 200
    position = response.json()["people"][0]["positions"][0]
    assert position["position_status"] == position_status.value


@pytest.mark.parametrize("stored_status", [None, "published"])
def test_settled_performance_shows_current_status_without_changing_snapshot(
    db, test_position, test_user, stored_status
):
    snapshot = calculate_overview(db, "2026-Q3", user=test_user, use_settlement=False).model_dump(mode="json")
    snapshot["status"] = "settled"
    snapshot["settlement_version"] = 1
    scored_position = snapshot["people"][0]["positions"][0]
    if stored_status is None:
        scored_position.pop("position_status")
    else:
        scored_position["position_status"] = stored_status
    settlement = RecruitmentSettlement(
        tenant_id=test_user.tenant_id, period="2026-Q3", version=1, snapshot=snapshot,
    )
    db.add(settlement)
    test_position.status = PositionStatus.CLOSED
    db.commit()

    result = calculate_overview(db, "2026-Q3", user=test_user)

    assert result.people[0].positions[0].position_status == "closed"
    assert result.people[0].positions[0].score == scored_position["score"]
    db.refresh(settlement)
    assert settlement.snapshot == snapshot


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


def test_scheduling_next_round_preserves_completed_interview_stage(
    db, test_position, test_resume, test_user
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    first_interview_ended_at = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    test_resume.status = ResumeStatus.INTERVIEW_SCHEDULED
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add_all([
        Interview(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            position_id=test_position.id,
            round=1,
            interview_category="hr",
            interview_time=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
            status=InterviewStatus.COMPLETED,
            ended_at=first_interview_ended_at,
        ),
        Interview(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            position_id=test_position.id,
            round=2,
            interview_category="manager",
            interview_time=datetime(2026, 7, 12, 10, tzinfo=timezone.utc),
            status=InterviewStatus.SCHEDULED,
        ),
    ])
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        user=test_user,
        now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        use_settlement=False,
    )

    slot = overview.people[0].positions[0].slots[0]
    assert slot.candidate_name == test_resume.candidate_name
    assert slot.result_stage == "HR面完成"
    assert slot.result_coefficient == 0.2
    assert slot.score > 0


def test_review_status_after_completed_interview_preserves_completed_stage(
    db, test_position, test_resume, test_user
):
    round_started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    interview_ended_at = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
    test_position.created_at = round_started_at
    test_resume.status = ResumeStatus.PENDING_REVIEW
    sync_position_slots(db, test_position, assigned_at=round_started_at)
    db.add(
        Interview(
            tenant_id=test_position.tenant_id,
            resume_id=test_resume.id,
            position_id=test_position.id,
            round=1,
            interview_category="manager",
            interview_time=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
            status=InterviewStatus.COMPLETED,
            ended_at=interview_ended_at,
        )
    )
    db.commit()

    overview = calculate_overview(
        db,
        "2026-Q3",
        user=test_user,
        now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        use_settlement=False,
    )

    slot = overview.people[0].positions[0].slots[0]
    assert slot.candidate_name == test_resume.candidate_name
    assert slot.result_stage == "业务面完成"
    assert slot.result_coefficient == 0.4
    assert slot.score > 0


def test_placeholder_emails_do_not_merge_distinct_candidates(
    db, test_position, test_resume
):
    test_resume.email = "未知"
    another_resume = Resume(
        tenant_id=test_position.tenant_id,
        candidate_name="李四",
        contact="13800138001",
        email="未知",
        position_id=test_position.id,
        file_path="/uploads/another_resume.pdf",
        raw_text="李四的简历内容...",
        status=ResumeStatus.PENDING_REVIEW,
        screening_result=ScreeningResult.PASSED,
    )
    db.add(another_resume)
    db.commit()

    allocations = _candidate_allocations(
        db,
        [test_position],
        get_config(db, "2026-Q3").result_coefficients,
    )

    assert {resume.candidate_name for resume, _, _ in allocations[test_position.id]} == {
        test_resume.candidate_name,
        another_resume.candidate_name,
    }


def test_interview_passed_uses_status_event_time(db, test_resume):
    passed_at = datetime(2026, 7, 8, 9, tzinfo=timezone.utc)
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    db.add(
        ResumeStatusEvent(
            tenant_id=test_resume.tenant_id,
            resume_id=test_resume.id,
            old_status=ResumeStatus.PENDING_INTERVIEW_RESULT.value,
            new_status=ResumeStatus.INTERVIEW_PASSED.value,
            source="test",
            occurred_at=passed_at,
        )
    )
    db.commit()

    stage, achieved_at = _result_stage(db, test_resume)

    assert stage == "interview_passed"
    assert achieved_at == passed_at


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


@pytest.mark.parametrize("stored_credit", [False, True])
def test_first_decision_stage_owner_keeps_handoff_credit_until_position_cancelled(
    db, test_position, test_resume, test_user, test_admin, stored_credit,
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
    assert credit.position_status == test_position.status.value
    assert credit.transferred_at == owner_changed_at
    assert credit.task_points == 40
    assert credit.score == pytest.approx(28.8)
    assert len(credit.slots) == 1
    assert credit.slots[0].candidate_name == test_resume.candidate_name
    assert people[test_user.id].task_points == credit.task_points
    assert people[test_user.id].score == credit.score

    transfer = db.query(PositionEvent).filter_by(
        position_id=test_position.id, event_type=PositionEventType.OWNER_CHANGED,
    ).one()
    if stored_credit:
        transfer.event_metadata = {"handoff_credit": {
            "recipient_user_id": str(test_user.id), "period": "2026-Q3",
            "detail": credit.model_dump(mode="json"),
        }}
    original_metadata = transfer.event_metadata
    test_position.status = PositionStatus.CANCELLED
    db.add(PositionEvent(
        tenant_id=test_position.tenant_id, position_id=test_position.id,
        event_type=PositionEventType.STATUS_CHANGED,
        old_value="published", new_value="cancelled",
        occurred_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    ))
    db.commit()

    cancelled = calculate_overview(db, "2026-Q3", now=cutoff, use_settlement=False)

    assert all(person.task_points == 0 and person.score > 0 for person in cancelled.people)
    old_owner = next(person for person in cancelled.people if person.user_id == test_user.id)
    cancelled_credit = old_owner.handoff_credits[0]
    assert cancelled_credit.task_points == 0
    assert cancelled_credit.score == credit.score
    assert all(slot.task_points == 0 and slot.score > 0 for slot in cancelled_credit.slots)
    db.refresh(transfer)
    assert transfer.event_metadata == original_metadata


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


@pytest.mark.parametrize("now", [
    datetime(2026, 8, 17, tzinfo=timezone.utc),
    datetime(2026, 11, 17, tzinfo=timezone.utc),
])
def test_admin_can_publish_next_quarter_config(client, admin_auth_headers, monkeypatch, now):
    from app.services import recruitment_performance_service

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(recruitment_performance_service, "datetime", FixedDateTime)
    current_quarter = (now.month - 1) // 3 + 1
    payload = {
            "effective_year": now.year + (current_quarter == 4),
            "effective_quarter": current_quarter % 4 + 1,
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
    assert response.json()["effective_year"] == payload["effective_year"]
    assert response.json()["effective_quarter"] == payload["effective_quarter"]

    revised = client.put("/api/recruitment-performance/config", headers=admin_auth_headers, json=payload)
    assert revised.status_code == 200
    assert revised.json()["version"] == 2

    current = client.put(
        "/api/recruitment-performance/config",
        headers=admin_auth_headers,
        json={**payload, "effective_year": now.year, "effective_quarter": current_quarter},
    )
    assert current.status_code == 409


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
    assert offer.onboarding_recorded_at is not None
    assert response.json()["onboarding_recorded_at"] is not None
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


def test_owner_can_record_departure_and_release_hc_with_under_30_day_credit_rollback(
    client, db, auth_headers, test_position, test_resume, test_user
):
    onboard_date = date.today() - timedelta(days=7)
    accepted_at = datetime.now(timezone.utc) - timedelta(days=8)
    test_position.created_at = accepted_at - timedelta(days=5)
    sync_position_slots(db, test_position, assigned_at=accepted_at - timedelta(days=5))
    replacement = Resume(
        tenant_id=test_position.tenant_id,
        candidate_name="李四",
        contact="13800138001",
        email="lisi@example.com",
        position_id=test_position.id,
        file_path="/uploads/replacement.pdf",
        raw_text="替补候选人",
        status=ResumeStatus.INTERVIEW_PASSED,
        screening_result=ScreeningResult.PASSED,
    )
    db.add(replacement)
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
    assert client.post(
        f"/api/offers/{offer.id}/confirm-onboarding",
        headers=auth_headers,
        json={"actual_onboard_date": onboard_date.isoformat()},
    ).status_code == 200
    occupied_slot_id = db.query(RecruitmentHcSlot.id).filter_by(
        position_id=test_position.id,
        candidate_resume_id=test_resume.id,
    ).scalar()

    response = client.post(
        f"/api/offers/{offer.id}/departure",
        headers=auth_headers,
        json={
            "actual_departure_date": date.today().isoformat(),
            "release_hc": True,
            "reason": "员工主动离职",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "departed"
    assert response.json()["departure_released_hc"] is True
    db.expire_all()
    db.refresh(test_resume)
    db.refresh(offer)
    historical_slot = db.get(RecruitmentHcSlot, occupied_slot_id)
    assert test_resume.status == ResumeStatus.DEPARTED
    assert _result_stage(db, test_resume)[0] == "offer_accepted"
    assert historical_slot.status == "released"
    assert historical_slot.candidate_resume_id == test_resume.id
    assert historical_slot.completed_at is not None
    assert historical_slot.recruitment_round == 1
    position_stats = get_position_stats(db, test_position.id)
    assert position_stats.occupied_headcount == 0
    assert position_stats.current_employed == 0
    assert position_stats.cumulative_onboarded == 1
    assert position_stats.departed == 1
    replacement_slot = db.query(RecruitmentHcSlot).filter_by(
        position_id=test_position.id,
        slot_number=historical_slot.slot_number,
        recruitment_round=2,
    ).one()
    assert replacement_slot.status == "active"
    assert replacement_slot.candidate_resume_id is None
    assert replacement_slot.assigned_at.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    ).date() == date.today()
    overview = calculate_overview(
        db,
        f"{date.today().year}-Q{(date.today().month - 1) // 3 + 1}",
        use_settlement=False,
    )
    position_score = overview.people[0].positions[0]
    assert position_score.hc_count == test_position.headcount
    assert position_score.current_employed_count == 0
    assert position_score.cumulative_onboarded_count == 1
    assert position_score.departed_count == 1
    historical_score = next(item for item in position_score.slots if item.slot_id == historical_slot.id)
    current_score = next(item for item in position_score.slots if item.slot_id == replacement_slot.id)
    assert historical_score.departed_at is not None
    assert historical_score.departure_released_hc is True
    assert historical_score.recruitment_round == 1
    assert historical_score.task_points > 0
    assert current_score.recruitment_round == 2
    assert current_score.candidate_name == replacement.candidate_name
    later_overview = calculate_overview(
        db,
        f"{date.today().year}-Q{(date.today().month - 1) // 3 + 1}",
        now=datetime.now(timezone.utc) + timedelta(days=10),
        use_settlement=False,
    )
    later_historical_score = next(
        item for item in later_overview.people[0].positions[0].slots
        if item.slot_id == historical_slot.id
    )
    assert later_historical_score.task_points == historical_score.task_points
    assert later_historical_score.score == historical_score.score


def test_owner_can_record_departure_without_releasing_hc(
    client, db, auth_headers, test_position, test_resume, test_user
):
    onboard_date = date.today() - timedelta(days=7)
    accepted_at = datetime.now(timezone.utc) - timedelta(days=8)
    test_position.created_at = accepted_at - timedelta(days=5)
    sync_position_slots(db, test_position, assigned_at=accepted_at - timedelta(days=5))
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
    assert client.post(
        f"/api/offers/{offer.id}/confirm-onboarding",
        headers=auth_headers,
        json={"actual_onboard_date": onboard_date.isoformat()},
    ).status_code == 200

    response = client.post(
        f"/api/offers/{offer.id}/departure",
        headers=auth_headers,
        json={"actual_departure_date": date.today().isoformat(), "release_hc": False},
    )

    assert response.status_code == 200
    assert response.json()["departure_released_hc"] is False
    db.expire_all()
    slot = db.query(RecruitmentHcSlot).filter_by(
        position_id=test_position.id,
        candidate_resume_id=test_resume.id,
    ).one()
    assert slot.status == "departed_retained"
    assert slot.candidate_resume_id == test_resume.id
    db.refresh(test_resume)
    assert test_resume.status == ResumeStatus.DEPARTED
    position_stats = get_position_stats(db, test_position.id)
    assert position_stats.occupied_headcount == 1
    assert position_stats.current_employed == 0
    assert position_stats.cumulative_onboarded == 1
    assert position_stats.departed == 1
    assert db.query(RecruitmentHcSlot).filter_by(
        position_id=test_position.id,
        slot_number=slot.slot_number,
    ).count() == 1
    overview = calculate_overview(
        db,
        f"{date.today().year}-Q{(date.today().month - 1) // 3 + 1}",
        use_settlement=False,
    )
    score_slot = next(
        item for item in overview.people[0].positions[0].slots if item.slot_id == slot.id
    )
    position_score = overview.people[0].positions[0]
    assert position_score.current_employed_count == 0
    assert position_score.cumulative_onboarded_count == 1
    assert position_score.departed_count == 1
    assert score_slot.departure_released_hc is False
    assert score_slot.task_points > 0
    later_overview = calculate_overview(
        db,
        f"{date.today().year}-Q{(date.today().month - 1) // 3 + 1}",
        now=datetime.now(timezone.utc) + timedelta(days=10),
        use_settlement=False,
    )
    later_score_slot = next(
        item for item in later_overview.people[0].positions[0].slots if item.slot_id == slot.id
    )
    assert later_score_slot.task_points == score_slot.task_points
    assert later_score_slot.score == score_slot.score


def test_onboarded_offer_decision_correction_requires_departure_flow(
    client, db, auth_headers, test_position, test_resume, test_user
):
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        status=OfferStatus.ACCEPTED,
        accepted_at=datetime.now(timezone.utc) - timedelta(days=2),
        created_by=test_user.id,
    )
    test_resume.status = ResumeStatus.OFFER_ACCEPTED
    db.add(offer)
    db.commit()
    assert client.post(
        f"/api/offers/{offer.id}/confirm-onboarding",
        headers=auth_headers,
        json={"actual_onboard_date": (date.today() - timedelta(days=1)).isoformat()},
    ).status_code == 200

    response = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={
            "decision": "rejected",
            "rejection_reason": "personal",
            "correction_reason": "错误操作",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "已确认入职的候选人不能改为Offer结果，请使用登记离职"
