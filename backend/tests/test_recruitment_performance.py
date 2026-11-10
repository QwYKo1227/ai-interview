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
    _candidate_allocations_at,
    _result_stage,
    available_periods,
    calculate_overview,
    get_config,
    sync_position_slots,
)
from app.services.position_service import get_position_stats


@pytest.mark.parametrize("entry", ["batch", "restore"])
@pytest.mark.parametrize("mode", ["correction", "new_cycle"])
def test_reopen_api_forwards_selected_mode(client, db, test_position, admin_auth_headers, entry, mode):
    original = sync_position_slots(db, test_position, assigned_at=test_position.created_at)
    original_ids = {slot.id for slot in original}
    test_position.status = PositionStatus.CLOSED
    if entry == "restore":
        test_position.deleted_at = datetime.now(timezone.utc)
    db.commit()
    payload = {"reason": "恢复招聘", "reopen_mode": mode}
    if entry == "batch":
        payload.update(position_ids=[str(test_position.id)], status="published")
        response = client.post("/api/positions/batch-status", json=payload, headers=admin_auth_headers)
    else:
        response = client.post(f"/api/positions/{test_position.id}/restore", json=payload, headers=admin_auth_headers)
    assert response.status_code == 200
    db.expire_all()
    current = sync_position_slots(db, db.get(Position, test_position.id))
    assert len(current) == test_position.headcount
    assert ({slot.id for slot in current} == original_ids) == (mode == "correction")


@pytest.mark.parametrize("terminal", ["closed", "cancelled"])
@pytest.mark.parametrize("entry", ["update", "batch", "legacy", "legacy_first_release", "legacy_explicit_mode"])
def test_correcting_accidental_termination_keeps_original_cycle(
    db, test_position, test_user, test_admin, status_history, monkeypatch, terminal, entry,
):
    from app.schemas.position import PositionUpdate
    from app.services import position_service

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 6, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(position_service, "datetime", Clock)
    status_history([(5, terminal)])
    original_ids = {slot.id for slot in sync_position_slots(db, test_position)}
    if entry.startswith("legacy"):
        metadata = {}
        if entry == "legacy_first_release":
            metadata = {"previous_recruitment_config": {"priority": 4, "category": "domestic_rd"}}
        elif entry == "legacy_explicit_mode":
            metadata = {"reopen_mode": "new_cycle"}
        db.add(PositionEvent(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            event_type=PositionEventType.STATUS_CHANGED, old_value=terminal,
            new_value="published", reason="误操作恢复", occurred_at=Clock.now(),
            event_metadata=metadata,
        ))
        test_position.status = PositionStatus.PUBLISHED
        db.commit()
    elif entry == "update":
        position_service.update_position(db, test_position.id, PositionUpdate(
            status=PositionStatus.PUBLISHED, status_change_reason="误操作恢复",
        ), actor=test_admin)
    else:
        position_service.batch_update_position_status(
            db, [test_position.id], PositionStatus.PUBLISHED, reason="误操作恢复", actor=test_admin,
        )
    overview = calculate_overview(
        db, "2026-Q3", now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc), use_settlement=False,
    )
    rows = overview.people[0].positions
    assert len(rows) == 1
    assert rows[0].position_status == "published"
    assert {slot.slot_id for slot in rows[0].slots} == original_ids
    assert {slot.effective_held_days for slot in rows[0].slots} == {10}
    assert rows[0].hc_count == test_position.headcount


def test_auto_closed_hc_uses_onboarding_result_after_same_day_acceptance(
    db, test_position, test_resume, test_user, monkeypatch,
):
    from app.services import offer_service

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 10, 4, tzinfo=timezone.utc)

    monkeypatch.setattr(offer_service, "datetime", Clock)
    test_position.headcount = 1
    test_position.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_resume.created_at = test_position.created_at
    test_resume.status = ResumeStatus.OFFER_ACCEPTED
    sync_position_slots(db, test_position, assigned_at=test_position.created_at)
    accepted_at = datetime(2026, 7, 10, 2, tzinfo=timezone.utc)
    offer = Offer(
        tenant_id=test_position.tenant_id, position_id=test_position.id,
        resume_id=test_resume.id, candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email, position_title=test_position.title,
        status=OfferStatus.ACCEPTED, accepted_at=accepted_at,
    )
    db.add(offer)
    db.add(ResumeStatusEvent(
        tenant_id=test_position.tenant_id, resume_id=test_resume.id,
        new_status=ResumeStatus.OFFER_PENDING.value, source="offer_sent",
        occurred_at=datetime(2026, 7, 8, 2, tzinfo=timezone.utc),
    ))
    db.add(ResumeStatusEvent(
        tenant_id=test_position.tenant_id, resume_id=test_resume.id,
        old_status=ResumeStatus.OFFER_PENDING.value,
        new_status=ResumeStatus.OFFER_ACCEPTED.value, source="offer_decision",
        occurred_at=accepted_at,
    ))
    db.commit()
    offer_service.confirm_onboarding(db, offer.id, date(2026, 7, 10), test_user)
    assert test_position.status == PositionStatus.CLOSED
    result = calculate_overview(db, "2026-Q3", now=Clock.now(), use_settlement=False)
    position = result.people[0].positions[0]
    assert position.current_employed_count == 1
    assert position.slots[0].result_stage == "已入职"
    assert position.slots[0].result_coefficient == 1.0
    assert position.highest_result_stage == "已入职"
    from app.services.recruitment_performance_service import _historical_result_stage

    assert _historical_result_stage(
        db, test_resume, datetime(2026, 7, 9, 12, tzinfo=timezone.utc),
    )[0] == "offer_pending"
    # A later departure must not affect the closure result. Once visible,
    # departure within 30 days retains the existing 0.9 rollback policy.
    offer.departed_at = datetime(2026, 7, 11, tzinfo=timezone.utc)
    db.commit()
    assert _historical_result_stage(db, test_resume, Clock.now())[0] == "onboarded"
    assert _historical_result_stage(db, test_resume, offer.departed_at.replace(tzinfo=timezone.utc))[0] == "offer_accepted"


def test_onboarding_closes_only_when_all_hc_are_confirmed(db, test_position, test_user):
    from app.services.offer_service import confirm_onboarding

    offers = []
    for number in range(2):
        resume = Resume(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            candidate_name=f"候选人{number}", email=f"hc{number}@example.com",
            status=ResumeStatus.OFFER_ACCEPTED,
        )
        db.add(resume)
        db.flush()
        offer = Offer(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            resume_id=resume.id, candidate_name=resume.candidate_name,
            candidate_email=resume.email, position_title=test_position.title,
            status=OfferStatus.ACCEPTED, accepted_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(offer)
        offers.append(offer)
    db.commit()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    confirm_onboarding(db, offers[0].id, today, test_user)
    assert test_position.status == PositionStatus.OPEN
    # Retrying a confirmation neither allocates another HC nor closes early.
    confirm_onboarding(db, offers[0].id, today, test_user)
    assert test_position.status == PositionStatus.OPEN
    assert len([s for s in sync_position_slots(db, test_position) if s.status == "completed"]) == 1
    confirm_onboarding(db, offers[1].id, today, test_user)
    assert test_position.status == PositionStatus.CLOSED


def test_marked_reopen_creates_missing_hc_at_cycle_start(db, test_position):
    initial = datetime(2026, 7, 1, tzinfo=timezone.utc)
    reopened = datetime(2026, 8, 1, tzinfo=timezone.utc)
    old_slots = sync_position_slots(db, test_position, assigned_at=initial)
    db.add(PositionEvent(
        tenant_id=test_position.tenant_id, position_id=test_position.id,
        event_type=PositionEventType.STATUS_CHANGED,
        old_value="closed", new_value="published", occurred_at=reopened,
        event_metadata={"reopen_mode": "new_cycle", "recruitment_cycle_policy_version": 1},
    ))
    test_position.status = PositionStatus.PUBLISHED
    db.commit()
    new_slots = sync_position_slots(db, test_position)
    db.commit()
    assert len(new_slots) == test_position.headcount
    assert {s.id for s in new_slots}.isdisjoint(s.id for s in old_slots)
    assert all(s.assigned_at.replace(tzinfo=timezone.utc) == reopened for s in new_slots)


def test_previous_onboarding_does_not_fill_reopened_position(db, test_position, test_user, test_admin):
    from app.schemas.position import PositionUpdate
    from app.services.offer_service import confirm_onboarding, record_departure
    from app.services.position_service import update_position

    test_position.headcount = 1
    today = datetime.now(timezone(timedelta(hours=8))).date()
    old_offer = None
    for number in range(2):
        resume = Resume(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            candidate_name=f"第{number + 1}轮入职", email=f"round{number}@example.com",
            status=ResumeStatus.OFFER_ACCEPTED,
        )
        db.add(resume)
        db.flush()
        offer = Offer(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            resume_id=resume.id, candidate_name=resume.candidate_name,
            candidate_email=resume.email, position_title=test_position.title,
            status=OfferStatus.ACCEPTED, accepted_at=datetime.now(timezone.utc),
        )
        db.add(offer)
        db.commit()
        if number == 1:
            assert test_position.status == PositionStatus.PUBLISHED
            assert get_position_stats(db, test_position.id).occupied_headcount == 0
            confirm_onboarding(db, old_offer.id, today, test_user)
            assert get_position_stats(db, test_position.id).occupied_headcount == 0
            assert test_position.status == PositionStatus.PUBLISHED
            # Departure of a historical hire must not create replacement HC in this cycle.
            record_departure(db, old_offer.id, today, True, test_user)
            assert len(sync_position_slots(db, test_position)) == 1
        confirm_onboarding(db, offer.id, today, test_user)
        assert test_position.status == PositionStatus.CLOSED
        if number == 0:
            old_offer = offer
            update_position(db, test_position.id, PositionUpdate(
                status=PositionStatus.PUBLISHED, status_change_reason="新增HC",
                reopen_mode="new_cycle",
            ), actor=test_admin)
    assert get_position_stats(db, test_position.id).occupied_headcount == 1
    period = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
    rows = calculate_overview(db, period, use_settlement=False).people[0].positions
    assert [row.recruitment_cycle for row in rows] == [1, 2]
    assert [row.onboarded_count for row in rows] == [0, 1]
    assert [row.cumulative_onboarded_count for row in rows] == [1, 1]
    assert rows[0].slots[0].candidate_name == "第1轮入职"
    assert rows[1].slots[0].candidate_name == "第2轮入职"


@pytest.mark.parametrize("reopen_method", ["update", "batch", "restore", "new_owner"])
def test_reopened_position_gets_fresh_hc_and_separate_performance(
    db, test_position, test_resume, test_user, test_admin, monkeypatch, reopen_method,
):
    from app.schemas.position import PositionUpdate
    from app.services import position_service

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 1, 4, tzinfo=timezone.utc)

    monkeypatch.setattr(position_service, "datetime", Clock)
    test_position.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_position.headcount = 1
    test_position.status = PositionStatus.CLOSED
    test_resume.created_at = test_position.created_at
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    old_slot = sync_position_slots(db, test_position, assigned_at=test_position.created_at)[0]
    db.add(ResumeStatusEvent(
        tenant_id=test_position.tenant_id, resume_id=test_resume.id,
        new_status=ResumeStatus.INTERVIEW_PASSED.value, source="test",
        occurred_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    ))
    db.add(PositionEvent(
        tenant_id=test_position.tenant_id, position_id=test_position.id,
        event_type=PositionEventType.STATUS_CHANGED,
        old_value="published", new_value="closed",
        occurred_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    ))
    db.commit()
    old_score = calculate_overview(db, "2026-Q3", now=Clock.now(), use_settlement=False).people[0].positions[0]

    if reopen_method in {"update", "new_owner"}:
        position_service.update_position(db, test_position.id, PositionUpdate(
            status=PositionStatus.PUBLISHED, status_change_reason="新增招聘需求", priority=5,
            reopen_mode="new_cycle",
            **({"hiring_manager_id": test_admin.id, "owner_change_reason": "新轮次负责人"}
               if reopen_method == "new_owner" else {}),
        ), actor=test_admin)
    elif reopen_method == "batch":
        position_service.batch_update_position_status(
            db, [test_position.id], PositionStatus.PUBLISHED, reason="新增招聘需求", actor=test_admin,
            reopen_mode="new_cycle",
        )
    else:
        test_position.deleted_at = Clock.now() - timedelta(days=1)
        db.commit()
        position_service.restore_position(db, test_position.id, actor=test_admin, reason="恢复招聘需求", reopen_mode="new_cycle")
    slots = sync_position_slots(db, test_position)
    assert len(slots) == 1
    assert slots[0].id != old_slot.id
    assert slots[0].candidate_resume_id is None
    assert slots[0].assigned_at.replace(tzinfo=timezone.utc) == Clock.now()
    assert slots[0].round_started_at.replace(tzinfo=timezone.utc) == Clock.now()
    db.commit()

    overview = calculate_overview(db, "2026-Q3", now=Clock.now() + timedelta(days=2), use_settlement=False)
    by_owner = {person.user_id: person for person in overview.people}
    if reopen_method == "new_owner":
        previous = by_owner[test_user.id].positions[0]
        current = by_owner[test_admin.id].positions[0]
        assert by_owner[test_user.id].handoff_credits == []
    else:
        previous, current = overview.people[0].positions
    assert previous.recruitment_cycle == 1
    assert previous.position_status == "closed"
    assert previous.score == old_score.score
    assert previous.task_points == old_score.task_points
    assert current.recruitment_cycle == 2
    assert current.position_status == ("open" if reopen_method == "restore" else "published")
    assert current.priority == test_position.priority
    assert current.cycle_started_at == Clock.now()
    assert current.hc_count == 1
    assert current.slots[0].result_stage == "岗位Open"
    assert current.slots[0].candidate_name is None
    assert current.slots[0].actual_days == 3
    assert current.slots[0].effective_held_days == 3
    # Historical quarters must not acquire the new cycle.
    before = calculate_overview(db, "2026-Q3", now=datetime(2026, 7, 20, tzinfo=timezone.utc), use_settlement=False)
    assert len(before.people[0].positions) == 1
    assert before.people[0].positions[0].position_status == "closed"

    snapshot = overview.model_dump(mode="json")
    settlement = RecruitmentSettlement(
        tenant_id=test_position.tenant_id, period="2026-Q3", version=1,
        snapshot=snapshot,
    )
    db.add(settlement)
    test_position.status = PositionStatus.PAUSED
    db.commit()
    settled = calculate_overview(db, "2026-Q3")
    cycle_statuses = {
        row.recruitment_cycle: row.position_status
        for person in settled.people for row in person.positions
    }
    assert cycle_statuses == {1: "closed", 2: "paused"}
    db.refresh(settlement)
    assert settlement.snapshot == snapshot


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


@pytest.mark.parametrize("replacement_status,expected_names,expected_coefficients", [
    (ResumeStatus.INTERVIEW_PASSED, {"原候选人1", "原候选人2"}, [0.8, 0.8]),
    (ResumeStatus.OFFER_PENDING, {"新候选人", "原候选人1"}, [0.8, 0.8]),
    (ResumeStatus.OFFER_ACCEPTED, {"新候选人", "原候选人1"}, [0.8, 0.9]),
])
def test_rejected_offers_keep_two_hc_milestones_until_replacements_reach_offer(
    db, test_position, test_user, replacement_status, expected_names, expected_coefficients,
):
    started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    sent_at = datetime(2026, 7, 5, tzinfo=timezone.utc)
    test_position.created_at = started_at
    sync_position_slots(db, test_position, assigned_at=started_at)
    for index, (name, status) in enumerate([
        ("原候选人1", ResumeStatus.OFFER_REJECTED),
        ("原候选人2", ResumeStatus.OFFER_REJECTED),
        ("新候选人", replacement_status),
        ("另一位备选", ResumeStatus.INTERVIEW_PASSED),
    ]):
        resume = Resume(
            tenant_id=test_position.tenant_id, position_id=test_position.id,
            candidate_name=name, email=f"candidate{index}@example.com",
            file_path="/test.pdf", status=status, created_at=started_at,
        )
        db.add(resume)
        db.flush()
        if status == ResumeStatus.OFFER_REJECTED:
            db.add_all([
                Offer(
                    tenant_id=test_position.tenant_id, position_id=test_position.id,
                    resume_id=resume.id, candidate_name=name,
                    candidate_email=resume.email, position_title=test_position.title,
                    status=OfferStatus.REJECTED, sent_at=sent_at + timedelta(hours=index),
                    rejected_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
                ),
                ResumeStatusEvent(
                    tenant_id=test_position.tenant_id, resume_id=resume.id,
                    old_status=ResumeStatus.OFFER_PENDING.value,
                    new_status=status.value, source="test",
                    occurred_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
                ),
            ])
    db.commit()

    person = calculate_overview(
        db, "2026-Q3", user=test_user,
        now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc), use_settlement=False,
    ).people[0]
    slots = person.positions[0].slots

    assert len(slots) == 2
    assert {slot.candidate_name for slot in slots} == expected_names
    assert sorted(slot.result_coefficient for slot in slots) == expected_coefficients
    for slot in slots:
        retained = slot.candidate_name.startswith("原候选人")
        assert slot.retained_after_offer_rejection is retained
        if retained:
            assert slot.result_stage == "Offer已发出"
        assert slot.score == pytest.approx(slot.task_points * slot.time_coefficient * slot.result_coefficient)
    assert person.score == pytest.approx(sum(slot.score for slot in slots))
    assert person.onboarded_count == 0
    assert db.query(RecruitmentHcSlot).filter(
        RecruitmentHcSlot.candidate_resume_id.isnot(None),
    ).count() == 0


def test_rejected_offer_retention_uses_sent_event_without_offer_record(db, test_resume):
    sent_at = datetime(2026, 7, 5, tzinfo=timezone.utc)
    test_resume.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_resume.status = ResumeStatus.OFFER_REJECTED
    db.add(ResumeStatusEvent(
        tenant_id=test_resume.tenant_id, resume_id=test_resume.id,
        old_status=ResumeStatus.INTERVIEW_PASSED.value,
        new_status=ResumeStatus.OFFER_PENDING.value, source="test", occurred_at=sent_at,
    ))
    db.commit()

    assert _result_stage(db, test_resume) == ("offer_pending", sent_at)


def test_historical_offer_replacement_uses_rejection_as_of_cutoff(
    db, test_position, test_resume,
):
    test_resume.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    test_resume.status = ResumeStatus.OFFER_REJECTED
    another = Resume(
        tenant_id=test_position.tenant_id, position_id=test_position.id,
        candidate_name="替补", email="replacement@example.com", file_path="/test.pdf",
        status=ResumeStatus.OFFER_PENDING,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    db.add(another)
    db.flush()
    for resume, day in [(test_resume, 5), (another, 6)]:
        db.add(ResumeStatusEvent(
            tenant_id=resume.tenant_id, resume_id=resume.id,
            old_status=ResumeStatus.INTERVIEW_PASSED.value,
            new_status=ResumeStatus.OFFER_PENDING.value, source="test",
            occurred_at=datetime(2026, 7, day, tzinfo=timezone.utc),
        ))
    db.add(ResumeStatusEvent(
        tenant_id=test_resume.tenant_id, resume_id=test_resume.id,
        old_status=ResumeStatus.OFFER_PENDING.value,
        new_status=ResumeStatus.OFFER_REJECTED.value, source="test",
        occurred_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    ))
    db.commit()
    coefficients = get_config(db, "2026-Q3").result_coefficients

    before = _candidate_allocations_at(
        db, [test_position], coefficients, datetime(2026, 7, 7, tzinfo=timezone.utc),
    )[test_position.id]
    after = _candidate_allocations_at(
        db, [test_position], coefficients, datetime(2026, 7, 9, tzinfo=timezone.utc),
    )[test_position.id]

    assert [row[0].id for row in before] == [test_resume.id, another.id]
    assert [row[0].id for row in after] == [another.id, test_resume.id]
    assert {row[1] for row in after} == {"offer_pending"}


@pytest.mark.parametrize("status", [ResumeStatus.REJECTED, ResumeStatus.INTERVIEW_FAILED])
def test_other_rejections_remain_excluded(db, test_position, test_resume, status):
    test_resume.status = status
    db.commit()
    assert not _candidate_allocations(
        db, [test_position], get_config(db, "2026-Q3").result_coefficients,
    ).get(test_position.id)


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
    test_position.headcount = 1
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
    db.refresh(test_position)
    assert test_position.status == PositionStatus.CLOSED
    event = db.query(PositionEvent).filter_by(
        position_id=test_position.id, event_type=PositionEventType.STATUS_CHANGED,
    ).one()
    assert event.new_value == "closed"
    assert event.reason == "本轮HC已全部确认入职，自动关闭岗位"


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
