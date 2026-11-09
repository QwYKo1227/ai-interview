from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.models import Position, Resume, ResumeStatus, ResumeStatusEvent, User, UserRole
from app.models.recruitment_quality import QualityAction, QualityBinding
from app.schemas.recruitment_quality import ActionRequest, PolicyRequest, QualityRules
from app.services import recruitment_quality_service as service
from app.services.recruitment_quality_engine import build_candidate_nodes, first_offer_sent, utc
from app.services.recruitment_workdays import add_workdays


def at(day, hour=1):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


@pytest.fixture
def flow():
    position = NS(id=uuid4(), title="工程师", hiring_manager_id=uuid4(), hiring_manager_history=[])
    resume = NS(id=uuid4(), candidate_name="候选人", status="pending_screening", manual_screening_decision=False)
    binding = NS(id=uuid4(), started_at=at(2), position_id=position.id, resume_id=resume.id)
    policy = NS(id=uuid4(), position_id=None, version=1, name="标准流程", created_at=at(1), rules=QualityRules().model_dump())
    def report(now=at(2), actions=None, interviews=None, reviews=None, offers=None, events=None, policies=None):
        return build_candidate_nodes(binding, position, resume, policies or [policy], actions or [],
                                     interviews or [], reviews or [], offers or [], events or [], now)
    return NS(position=position, resume=resume, binding=binding, policy=policy, report=report)


def action(when, new, old="pending_screening"):
    return NS(id=uuid4(), kind="transition", node_key="screening", occurred_at=when,
              actor_id=uuid4(), reason="状态流转", details={"old_status": old, "new_status": new})


def interview(created=None, decided=None, result="passed", round=1, **kw):
    data = dict(id=uuid4(), created_at=created or at(2, 2), round=round,
                interview_time=at(2, 3), interview_end_time=at(2, 4),
                interview_type="onsite", interview_location="会议室", meeting_link=None,
                interviewer_id=uuid4(), panel_members=["interviewer"], cancelled_at=None,
                panels=[NS(human_review_submitted_at=at(2, 5))], ended_at=at(2, 4),
                final_decision_at=decided, result=result,
                decision_history=[{"action": "confirmed", "result": result, "at": decided.isoformat()}] if decided else [])
    data.update(kw)
    return NS(**data)


def offer(**kw):
    data = dict(id=uuid4(), created_at=at(2, 6), sent_at=None, accepted_at=None, rejected_at=None,
                valid_until=at(10), status="draft", actual_onboarded_at=None,
                onboarding_recorded_at=None, onboard_date=None)
    data.update(kw)
    return NS(**data)


def node(nodes, key):
    return next(n for n in nodes if n["key"] == key)


def destination(row):
    url = urlparse(row["href"])
    return url.path, {key: values[0] for key, values in parse_qs(url.query).items()}


def test_screening_links_to_its_decision_then_the_outstanding_schedule(flow):
    path, query = destination(node(flow.report(), "screening"))
    assert path == f"/resumes/{flow.resume.id}"
    assert query["action"] == "hr-decision"
    flow.resume.status = "pending_interview"
    path, query = destination(node(flow.report(now=at(5), actions=[action(at(2, 2), "pending_interview")]), "screening"))
    assert path == "/interviews"
    assert query == {"candidate": str(flow.resume.id), "position": str(flow.position.id), "action": "schedule"}


def test_department_links_to_assignment_and_its_hr_decision(flow):
    flow.resume.status = "pending_dept_review"
    rows = flow.report(actions=[action(at(2), "pending_dept_review")])
    assert destination(node(rows, "screening"))[1]["action"] == "assign-reviewers"
    flow.resume.status = "pending_hr_decision"
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2), is_completed=True, completed_at=at(3))]
    rows = flow.report(now=at(4), actions=[action(at(2), "pending_dept_review")], reviews=reviews)
    path, query = destination(node(rows, "department"))
    assert path == f"/resumes/{flow.resume.id}"
    assert query["section"] == "department"
    assert query["action"] == "hr-decision"


def test_interview_links_to_result_or_its_outstanding_next_step(flow):
    i = interview(result="pending")
    rows = flow.report(now=at(3), interviews=[i])
    assert node(rows, f"interview:{i.id}")["href"] == f"/interviews/{i.id}/result"
    i = interview(decided=at(2, 6), result="next_round")
    flow.resume.status = "pending_next_interview"
    rows = flow.report(now=at(5), interviews=[i])
    assert destination(node(rows, f"interview:{i.id}"))[1]["action"] == "schedule"
    i = interview(decided=at(2, 6))
    flow.resume.status = "interview_passed"
    rows = flow.report(now=at(5), interviews=[i])
    assert destination(node(rows, f"interview:{i.id}"))[1]["action"] == "create"
    draft = offer()
    rows = flow.report(now=at(5), interviews=[i], offers=[draft])
    path, query = destination(node(rows, f"interview:{i.id}"))
    assert path == "/offers"
    assert query["offer_id"] == str(draft.id)
    assert query["action"] == "send"


def test_attendance_and_cancellation_link_to_the_correct_interview_handling(flow):
    i = interview(ended_at=None, panels=[], result="pending")
    rows = flow.report(now=at(5), interviews=[i])
    path, query = destination(node(rows, f"attendance:{i.id}"))
    assert path == "/interviews"
    assert query["interview_id"] == str(i.id)
    assert query["action"] == "edit"
    i.cancelled_at = at(3)
    rows = flow.report(now=at(5), interviews=[i])
    assert destination(node(rows, f"cancel:{i.id}"))[1]["action"] == "schedule"


def test_offer_exceptions_and_onboarding_keep_the_exact_offer_id(flow):
    o = offer(status="accepted", sent_at=at(2), accepted_at=at(3), onboard_date=at(4), valid_until=at(3))
    flow.resume.status = "offer_accepted"
    rows = flow.report(now=at(6), offers=[o])
    path, query = destination(node(rows, f"onboarding:{o.id}"))
    assert path == "/offers"
    assert query["offer_id"] == str(o.id)
    assert query["action"] == "onboarding"
    o = offer(status="sent", sent_at=at(2), valid_until=at(3))
    rows = flow.report(now=at(6), offers=[o])
    assert destination(node(rows, f"offer_expiry:{o.id}"))[1]["offer_id"] == str(o.id)


def test_historical_interview_does_not_launch_current_flow_arrangements(flow):
    i = interview(decided=at(2, 6), result="next_round")
    transfer = NS(kind="transferred", node_key="process", occurred_at=at(4), actor_id=None, reason="转岗", details={})
    rows = flow.report(now=at(5), interviews=[i], actions=[transfer])
    assert node(rows, f"interview:{i.id}")["href"] == f"/interviews/{i.id}/result"


def test_workdays_keep_beijing_clock_and_count_makeup_saturday():
    assert add_workdays(at(6), 2) == at(10)
    friday = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
    assert add_workdays(friday, 1) == friday + timedelta(days=1)
    before_holiday = datetime(2026, 9, 30, 1, tzinfo=timezone.utc)
    assert add_workdays(before_holiday, 2) == datetime(2026, 10, 9, 1, tzinfo=timezone.utc)


def test_pending_candidate_has_no_artificial_intake_or_position_points(flow):
    rows = flow.report()
    assert [n["key"] for n in rows] == ["screening"]
    assert service.metrics(rows)["process_rate"] is None
    assert not rows[0]["eligible"]


def test_timely_rejection_is_complete_without_later_steps(flow):
    flow.resume.status = "rejected"
    rows = flow.report(now=at(3), actions=[action(at(2, 2), "rejected")])
    assert service.metrics(rows)["process_rate"] == 100
    assert len(rows) == 1


def test_late_screening_never_recovers_after_backfill(flow):
    flow.resume.status = "rejected"
    screen = node(flow.report(now=at(9), actions=[action(at(6), "rejected")]), "screening")
    assert screen["status"] == "late"
    assert screen["eligible"] and not screen["complete"]


def test_screening_progression_counts_even_when_result_was_timely(flow):
    screen = node(flow.report(now=at(5), actions=[action(at(2, 2), "pending_interview")]), "screening")
    assert screen["overdue"]
    assert not screen["complete"]
    # Arranging it late must not repair the score.
    screen = node(flow.report(now=at(6), actions=[action(at(2, 2), "pending_interview")],
                              interviews=[interview(created=at(5), ended_at=None, panels=[])]), "screening")
    assert screen["status"] == "late"


def test_offer_draft_does_not_finish_post_interview_progress(flow):
    i = interview(decided=at(2, 6))
    rows = flow.report(now=at(5), interviews=[i], offers=[offer()])
    n = node(rows, f"interview:{i.id}")
    assert n["overdue"]
    assert any("发送Offer" in f["label"] for f in n["fields"])


def test_late_offer_sending_remains_late(flow):
    i = interview(decided=at(2, 6))
    rows = flow.report(now=at(6), interviews=[i], offers=[offer(sent_at=at(5), status="sent")])
    assert node(rows, f"interview:{i.id}")["status"] == "late"


def test_first_offer_sent_is_preserved_across_resending():
    o = offer(sent_at=at(6))
    event = NS(source="offer_sent", source_id=o.id, occurred_at=at(3))
    assert first_offer_sent([o], [event], []) == at(3)
    assert first_offer_sent([o], [event], [], at(5)) is None


def test_waitlist_pauses_then_grants_a_complete_new_term(flow):
    actions = [action(at(2, 2), "pending_interview"), action(at(3), "waitlist", "pending_interview")]
    n = node(flow.report(now=at(9), actions=actions), "screening")
    assert n["paused"] and not n["overdue"]
    actions.append(action(at(9), "pending_interview", "waitlist"))
    n = node(flow.report(now=at(10), actions=actions), "screening")
    assert not n["paused"] and not n["overdue"]
    assert n["due_at"] == at(11)
    assert node(flow.report(now=at(12), actions=actions), "screening")["overdue"]


def test_waitlist_cannot_clear_an_existing_miss(flow):
    actions = [action(at(2, 2), "pending_interview"), action(at(5), "waitlist", "pending_interview"),
               action(at(9), "pending_interview", "waitlist")]
    n = node(flow.report(now=at(10), actions=actions), "screening")
    assert n["overdue"] and n["eligible"]


def test_all_reviewers_ready_then_hr_decision_then_interview_arrangement(flow):
    actions = [action(at(2, 2), "pending_dept_review"),
               action(at(3), "pending_hr_decision", "pending_dept_review"),
               action(at(3, 2), "pending_interview", "pending_hr_decision")]
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2, 2),
                  is_completed=True, completed_at=at(3))]
    rows = flow.report(now=at(6), actions=actions, reviews=reviews)
    assert node(rows, "department")["overdue"]
    assert service.metrics(rows)["required_nodes"] == 2


def test_waiting_for_reviewers_is_unscored_with_or_without_notes(flow):
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=False, completed_at=None) for _ in range(3)]
    logs = [NS(id=uuid4(), kind="follow_up", node_key="department", occurred_at=at(day),
               actor_id=None, reason="已催办", details={}) for day in (4, 6)]
    n = node(flow.report(now=at(9), actions=logs, reviews=reviews), "department")
    assert not n["overdue"]
    assert len([r for r in flow.report(now=at(9), reviews=reviews) if r["stage"] == "department"]) == 1
    without_notes = node(flow.report(now=at(9), reviews=reviews), "department")
    assert not without_notes["overdue"] and not without_notes["eligible"]
    assert without_notes["due_at"] is None
    assert service.metrics([n]) == service.metrics([without_notes])


def test_multiround_requires_next_round_not_any_old_schedule(flow):
    i = interview(decided=at(2, 6), result="next_round")
    old = interview(created=at(2, 2), ended_at=None, panels=[])
    n = node(flow.report(now=at(5), interviews=[i, old]), f"interview:{i.id}")
    assert n["overdue"]
    next_round = interview(created=at(3), round=2, ended_at=None, panels=[])
    n = node(flow.report(now=at(4), interviews=[i, next_round]), f"interview:{i.id}")
    assert n["complete"]


def test_historical_evidence_counts_and_missing_evidence_is_unknown(flow):
    flow.policy.created_at = at(9)
    flow.resume.status = "rejected"
    rows = flow.report(now=at(10), actions=[action(at(3), "rejected")])
    assert rows[0]["historical"]
    assert service.metrics(rows)["process_rate"] == 100
    flow.resume.manual_screening_decision = True
    rows = flow.report(now=at(10))
    assert rows[0]["status"] == "unknown"
    assert service.metrics(rows)["process_rate"] is None


def test_policy_versions_are_selected_at_each_obligation_start(flow):
    new = NS(**{**vars(flow.policy), "id": uuid4(), "version": 2, "created_at": at(3),
                "rules": QualityRules(offer_send_days=5, screening_days=10).model_dump()})
    i = interview(created=at(3), decided=at(4), panels=[], ended_at=at(3))
    rows = flow.report(now=at(5), policies=[flow.policy, new], interviews=[i])
    assert node(rows, "screening")["due_at"] == at(4)
    target = next(f for f in node(rows, f"interview:{i.id}")["fields"] if "发送Offer" in f["label"])
    assert target["due_at"] == at(11)


def test_handoff_preserves_complete_and_already_overdue_owners(flow):
    old, new = flow.position.hiring_manager_id, uuid4()
    flow.position.hiring_manager_id = new
    flow.position.hiring_manager_history = [{"old_owner_id": str(old), "new_owner_id": str(new), "changed_at": at(6).isoformat()}]
    complete = node(flow.report(now=at(9), actions=[action(at(3), "rejected")]), "screening")
    overdue = node(flow.report(now=at(9)), "screening")
    assert complete["owner_id"] == old
    assert overdue["owner_id"] == old
    flow.position.hiring_manager_history[0]["changed_at"] = at(3).isoformat()
    assert node(flow.report(now=at(9)), "screening")["owner_id"] == new


def test_future_offer_reply_deadline_does_not_count_as_completed(flow):
    o = offer(sent_at=at(2), status="sent")
    n = node(flow.report(now=at(3), offers=[o]), f"offer:{o.id}")
    assert not n["complete"] and not n["eligible"]


def test_onboarding_uses_registration_time_not_backdated_business_date(flow):
    o = offer(sent_at=at(2), accepted_at=at(3), onboard_date=at(4), actual_onboarded_at=at(4),
              onboarding_recorded_at=at(9), status="accepted")
    n = node(flow.report(now=at(10), offers=[o]), f"onboarding:{o.id}")
    assert n["status"] == "late"
    o.onboarding_recorded_at = None
    assert node(flow.report(now=at(10), offers=[o]), f"onboarding:{o.id}")["status"] == "unknown"


def test_unknown_calendar_year_is_not_guessed(flow):
    flow.binding.started_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    n = flow.report(now=datetime(2030, 2, 1, tzinfo=timezone.utc))[0]
    assert n["status"] == "unknown"
    assert not n["eligible"]


@pytest.mark.parametrize("recommendation,label", [("recommend", "推荐"), ("not_recommend", "不推荐"), ("pending", "待定")])
def test_completed_legacy_department_review_preserves_result_after_rejection(flow, recommendation, label):
    flow.resume.status = "rejected"
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=True, recommendation=recommendation, completed_at=None)]
    rows = flow.report(now=at(10), reviews=reviews)
    department = node(rows, "department")
    assert department["business_status"] == "completed"
    assert department["business_result"] == label
    assert department["status"] == "unknown"
    assert not department["eligible"] and not department["overdue"]
    assert any(f["business_completed"] and f["completed_at"] is None for f in department["fields"])
    assert all(n["business_status"] not in {"pending", "paused"} for n in rows)


@pytest.mark.parametrize("status,expected", [("pending_dept_review", "pending"), ("rejected", "terminated")])
def test_partial_department_reviews_wait_only_while_application_is_active(flow, status, expected):
    flow.resume.status = status
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=done, recommendation="recommend" if done else None, completed_at=None)
               for done in (True, False)]
    department = node(flow.report(now=at(10), reviews=reviews), "department")
    assert department["business_status"] == expected
    assert "1/2" in department["business_result"]
    assert not department["eligible"]


def test_completed_department_opinions_do_not_claim_hr_has_decided(flow):
    flow.resume.status = "pending_hr_decision"
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=True, recommendation="recommend", completed_at=None)]
    department = node(flow.report(now=at(10), reviews=reviews), "department")
    assert department["business_status"] == "completed"
    assert department["business_result"] == "推荐；待HR决策"
    assert not department["eligible"]
    assert department["_flow"]["status"] == "pending_hr_decision"


@pytest.mark.parametrize("status", ["pending_screening", "pending_review", "auto_rejected_pending_review"])
def test_early_ai_or_pending_states_are_not_final_manual_rejections(flow, status):
    flow.resume.status = status
    n = node(flow.report(now=at(3)), "screening")
    assert n["business_status"] == "pending"
    assert n["_flow"]["status"] == status


@pytest.mark.parametrize("result,expected", [
    ("passed", "interview_passed"), ("next_round", "pending_next_interview"), ("rejected", "interview_failed"),
])
def test_actual_final_interview_results_correct_stale_waiting_labels(flow, result, expected):
    flow.resume.status = "pending_interview_result"
    i = interview(result=result, status="completed", ended_at=None, panels=[])
    rows = flow.report(now=at(10), interviews=[i])
    assert rows[0]["_flow"]["status"] == expected
    assert node(rows, f"interview:{i.id}")["business_status"] == "completed"


def test_actual_interview_end_does_not_leave_recording_shown_in_progress(flow):
    flow.resume.status = "interview_in_progress"
    i = interview(result="pending", status="completed", ended_at=None, panels=[])
    rows = flow.report(now=at(10), interviews=[i])
    assert rows[0]["_flow"]["status"] == "pending_interview_result"
    assert node(rows, f"interview:{i.id}")["business_status"] == "pending"


@pytest.mark.parametrize("offer_status,expected", [("accepted", "offer_accepted"), ("rejected", "offer_rejected")])
def test_actual_offer_reply_corrects_stale_waiting_state_without_a_timestamp(flow, offer_status, expected):
    flow.resume.status = "offer_pending"
    rows = flow.report(now=at(10), offers=[offer(status=offer_status)])
    assert rows[0]["_flow"]["status"] == expected


def test_final_hr_rejection_is_not_overwritten_by_a_recommended_review_or_passed_interview(flow):
    flow.resume.status = "rejected"
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=True, recommendation="recommend", completed_at=None)]
    rows = flow.report(now=at(10), reviews=reviews, interviews=[interview(result="passed")])
    assert rows[0]["_flow"]["status"] == "rejected"
    assert node(rows, "department")["business_result"] == "推荐"
    assert all(n["business_status"] not in {"pending", "paused"} for n in rows)


@pytest.mark.parametrize("result,resume_status,label", [
    ("passed", "interview_passed", "通过"), ("next_round", "pending_next_interview", "进入下一轮"),
    ("rejected", "interview_failed", "不通过"), ("waitlist", "waitlist", "备选"),
])
def test_interview_decision_without_operation_times_is_completed_but_not_scored(flow, result, resume_status, label):
    flow.resume.status = resume_status
    i = interview(result=result, ended_at=None, panels=[], final_decision_at=None, decision_history=[], status="completed")
    rows = flow.report(now=at(10), interviews=[i])
    decision = node(rows, f"interview:{i.id}")
    assert decision["business_status"] == "completed"
    assert decision["business_result"] == label
    assert not decision["eligible"] and not decision["overdue"]
    assert all(not n["overdue"] for n in rows if n["key"].startswith("attendance:"))


def test_cancelled_interview_without_cancel_time_never_stays_in_progress(flow):
    flow.resume.status = "pending_interview"
    i = interview(result="pending", ended_at=None, panels=[], status="cancelled")
    decision = node(flow.report(now=at(10), interviews=[i]), f"interview:{i.id}")
    assert decision["business_status"] == "terminated"
    assert decision["business_result"] == "已取消"
    assert not decision["eligible"]


@pytest.mark.parametrize("status,expected", [
    ("draft", "pending"), ("sent", "pending"), ("accepted", "completed"),
    ("rejected", "completed"), ("withdrawn", "completed"), ("expired", "completed"),
])
def test_offer_status_is_authoritative_without_legacy_reply_times(flow, status, expected):
    flow.resume.status = "offer_pending"
    o = offer(status=status, sent_at=None, accepted_at=None, rejected_at=None)
    n = node(flow.report(now=at(10), offers=[o]), f"offer:{o.id}")
    assert n["business_status"] == expected
    assert not n["eligible"]


def test_expired_response_deadline_does_not_fabricate_an_offer_reply(flow):
    flow.resume.status = "offer_pending"
    o = offer(status="sent", sent_at=at(2), valid_until=at(3))
    n = node(flow.report(now=at(10), offers=[o]), f"offer:{o.id}")
    assert n["business_status"] == "pending"
    assert n["business_result"] == "已到期，待处理"


def test_actual_onboarding_without_registration_time_is_completed_with_unknown_timeliness(flow):
    flow.resume.status = "completed"
    o = offer(status="accepted", actual_onboarded_at=at(3), onboarding_recorded_at=None)
    n = node(flow.report(now=at(10), offers=[o]), f"onboarding:{o.id}")
    assert n["business_status"] == "completed" and n["business_result"] == "已入职"
    assert not n["eligible"] and n["status"] == "unknown"


@pytest.mark.parametrize("status,result", [("completed", "已入职"), ("departed", "已离职")])
def test_final_onboarding_state_is_not_treated_as_an_unfinished_registration_when_old_dates_are_missing(flow, status, result):
    flow.resume.status = status
    o = offer(status="accepted", accepted_at=at(3), onboard_date=at(4), actual_onboarded_at=None, onboarding_recorded_at=None)
    n = node(flow.report(now=at(10), offers=[o]), f"onboarding:{o.id}")
    assert n["business_status"] == "completed" and n["business_result"] == result
    assert not n["eligible"]


@pytest.mark.parametrize("status", ["rejected", "interview_failed", "offer_rejected", "completed", "departed"])
def test_all_terminal_outcomes_stop_unfinished_business_waits_without_inventing_dates(flow, status):
    flow.resume.status = status
    reviews = [NS(id=uuid4(), reviewed_position_id=flow.position.id, created_at=at(2),
                  is_completed=False, recommendation=None, completed_at=None)]
    rows = flow.report(now=at(10), reviews=reviews, offers=[offer(status="sent", sent_at=at(2))])
    assert all(n["business_status"] in {"completed", "terminated"} for n in rows)
    assert not any(n["business_status"] == "terminated" and n["overdue"] for n in rows)


def candidate(db, owner, when):
    p = Position(tenant_id=owner.tenant_id, title="工程师", description="岗位描述", hiring_manager_id=owner.id)
    db.info["quality_actor_id"] = owner.id
    db.add(p)
    db.commit()
    r = Resume(id=uuid4(), tenant_id=owner.tenant_id, position_id=p.id, candidate_name="候选人",
               status=ResumeStatus.PENDING_SCREENING, created_at=when)
    db.add(r)
    db.commit()
    return p, r


def test_api_configuration_defaults_and_tenant_permissions(client, db, test_admin, test_user, tenant_b, auth_headers, admin_auth_headers):
    assert client.post("/api/recruitment-quality/policies", json={}, headers=auth_headers).status_code == 403
    assert client.post("/api/recruitment-quality/policies", json={}, headers=admin_auth_headers).status_code == 200
    config = client.get("/api/recruitment-quality/config", headers=admin_auth_headers).json()
    assert config["defaults"]["offer_send_days"] == 2
    assert "coding_test_required" not in config["defaults"]
    other = Position(tenant_id=tenant_b.id, title="其他租户机密", description="岗位描述")
    db.add(other)
    db.commit()
    result = client.get("/api/recruitment-quality/overview", headers=admin_auth_headers)
    assert result.status_code == 200
    assert "其他租户机密" not in result.text
    assert "data_rate" not in result.json()["summary"]
    assert client.get("/api/recruitment-quality/overview?cohort=invalid", headers=auth_headers).status_code == 422


def test_real_orm_audits_initial_screening_waitlist_and_resume(db, test_admin, test_user, monkeypatch):
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, at(2))
    clock[0] = at(3)
    r.status = ResumeStatus.WAITLIST
    db.commit()
    clock[0] = at(9)
    assert any(a.details.get("new_status") == "waitlist" for a in db.query(QualityAction).all())
    r.status = ResumeStatus.PENDING_INTERVIEW
    db.commit()
    monkeypatch.setattr(service, "now_utc", lambda: at(10))
    n = node(service.overview(db, test_user)["nodes"], "screening")
    assert n["due_at"] == at(11)
    assert not n["overdue"]


def test_non_hr_cannot_write_notes_and_legacy_actions_are_rejected(db, test_admin, test_user, test_interviewer, monkeypatch):
    monkeypatch.setattr(service, "now_utc", lambda: at(2))
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, at(2))
    binding = db.query(QualityBinding).filter(QualityBinding.resume_id == r.id).one()
    with pytest.raises(HTTPException) as exc:
        service.record_action(db, test_interviewer, binding.id, "screening", ActionRequest(kind="note", reason="已联系"))
    assert exc.value.status_code == 403
    for kind in ("follow_up", "resolve", "waive"):
        with pytest.raises(ValidationError):
            ActionRequest(kind=kind, reason="直接补齐")


def test_legacy_rules_upgrade_ignores_coding_and_keeps_config_values():
    rules = QualityRules.model_validate({"screening_hours": 72, "department_review_hours": 48,
                                         "interview_review_hours": 24, "coding_test_required": True})
    assert rules.screening_days == 3
    assert rules.interview_decision_days == 1
    assert "coding_test_required" not in rules.model_dump()


def test_ai_waitlist_does_not_count_as_hr_screening(flow):
    automatic = action(at(2, 2), "waitlist")
    automatic.actor_id = None
    flow.resume.status = "waitlist"
    n = flow.report(now=at(10), actions=[automatic])[0]
    assert not n["complete"] and not n["eligible"]
    assert n["paused"]


def test_rejected_application_restored_to_screening_starts_a_new_cycle(flow):
    events = [action(at(3), "rejected"), action(at(5), "pending_review", "rejected"),
              action(at(5, 2), "pending_interview", "pending_review")]
    rows = flow.report(now=at(12), actions=events)
    assert len(rows) == 2
    assert rows[0]["complete"]
    assert rows[1]["key"].startswith("cycle:")
    assert rows[1]["overdue"]
    assert service.metrics(rows)["process_rate"] == 50


def test_late_offer_obligation_survives_correcting_interview_to_rejected(flow):
    i = interview(decided=at(2, 6), result="passed")
    i.decision_history.append({"action": "corrected", "from": "passed", "to": "rejected", "at": at(9).isoformat()})
    i.final_decision_at = at(9)
    i.result = "rejected"
    n = node(flow.report(now=at(10), interviews=[i]), f"interview:{i.id}")
    assert n["overdue"]
    assert n["status"] == "late"


def test_timely_correction_cancels_only_the_unexpired_branch(flow):
    i = interview(decided=at(2, 6), result="passed")
    i.decision_history.append({"action": "corrected", "from": "passed", "to": "rejected", "at": at(3).isoformat()})
    i.final_decision_at = at(3)
    i.result = "rejected"
    assert node(flow.report(now=at(10), interviews=[i]), f"interview:{i.id}")["complete"]


def test_offer_correction_does_not_extend_the_original_response_wait(flow):
    o = offer(sent_at=at(2), rejected_at=None, accepted_at=at(9), status="accepted", onboard_date=at(12))
    original = NS(id=uuid4(), kind="offer_transition", node_key=f"offer:{o.id}", occurred_at=at(3),
                  actor_id=uuid4(), reason="首次拒绝", details={"offer_id": str(o.id), "old_status": "sent", "new_status": "rejected"})
    n = node(flow.report(now=at(10), offers=[o], actions=[original]), f"offer:{o.id}")
    assert n["complete"]


def test_old_position_does_not_use_status_events_after_transfer(flow):
    events = [action(at(2, 2), "pending_interview"),
              NS(id=uuid4(), kind="transferred", node_key="process", occurred_at=at(3),
                 actor_id=None, reason="转岗", details={})]
    new_job_event = NS(source="hr", actor_id=uuid4(), occurred_at=at(5),
                       old_status="pending_screening", new_status="rejected")
    n = flow.report(now=at(10), actions=events, events=[new_job_event])[0]
    assert n["complete"]
    assert not any(a["occurred_at"] == at(5) for a in n["actions"])


def test_current_hr_can_note_work_whose_lateness_stays_with_previous_hr(db, test_admin, test_user, monkeypatch):
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    p, r = candidate(db, test_user, at(2))
    successor = User(id=uuid4(), tenant_id=test_user.tenant_id, email="successor@example.com", full_name="新HR",
                     role=UserRole.HR, hashed_password="unused")
    db.add(successor)
    db.commit()
    clock[0] = at(6)
    p.hiring_manager_id = successor.id
    db.commit()
    clock[0] = at(9)
    binding = db.query(QualityBinding).filter(QualityBinding.resume_id == r.id).one()
    result = service.record_action(db, successor, binding.id, "screening", ActionRequest(kind="note", reason="接手后已联系候选人"))
    assert result["id"]
    report = service.overview(db, successor)
    assert report["summary"]["required_nodes"] == 1
    assert report["nodes"][0]["owner_id"] == test_user.id
    assert report["nodes"][0]["executor_id"] == successor.id
    assert report["nodes"][0]["current_owner_id"] == successor.id
    assert report["nodes"][0]["current_owner_name"] == successor.full_name
    old_report = service.overview(db, test_user)
    assert old_report["people"] == old_report["nodes"] == old_report["flows"] == old_report["positions"] == []
    assert old_report["summary"]["required_nodes"] == 0
    assert report["people"][0]["user_id"] == successor.id
    assert report["people"][0]["open_position_count"] == 1
    assert report["people"][0]["active_candidate_count"] == 1


def test_current_work_counts_follow_handoff_without_moving_historical_quality(
    db, test_admin, test_user, monkeypatch,
):
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    position, resume = candidate(db, test_admin, at(2))
    clock[0] = at(6)
    position.hiring_manager_id = test_user.id
    db.commit()
    clock[0] = at(9)

    report = service.overview(db, test_admin)
    people = {p["user_id"]: p for p in report["people"]}
    assert test_admin.id not in people
    assert people[test_user.id]["open_position_count"] == 1
    assert people[test_user.id]["active_candidate_count"] == 1
    assert people[test_user.id]["required_nodes"] == 1
    assert people[test_user.id]["position_count"] == 1
    assert people[test_user.id]["candidate_count"] == 1
    screening = node(report["nodes"], "screening")
    assert screening["owner_id"] == test_admin.id
    assert screening["executor_id"] == test_user.id
    assert screening["current_owner_id"] == test_user.id
    assert all(f["is_current"] for f in report["flows"])

    # Each HR sees their own row, including a successor with no scored nodes.
    own_report = service.overview(db, test_user)
    assert [p["user_id"] for p in own_report["people"]] == [test_user.id]
    assert own_report["people"][0]["open_position_count"] == 1
    assert own_report["summary"]["required_nodes"] == 1
    assert service.overview(db, test_admin, start_date=at(10).date())["people"] == []

    # Closed positions and terminal candidates do not count as current work.
    from app.models.models import PositionStatus
    position.status = PositionStatus.CLOSED
    resume.status = ResumeStatus.REJECTED
    db.commit()
    people = {p["user_id"]: p for p in service.overview(db, test_admin)["people"]}
    assert test_admin.id not in people
    assert people[test_user.id]["open_position_count"] == 0
    assert people[test_user.id]["active_candidate_count"] == 0


def offer_action(o, when, status, old=None, **details):
    return NS(id=uuid4(), kind="offer_transition", node_key=f"offer:{o.id}", occurred_at=when,
              actor_id=None, reason="Offer状态流转",
              details={"offer_id": str(o.id), "old_status": old, "new_status": status, **details})


def test_withdrawing_offer_stops_its_feedback_wait(flow):
    o = offer(sent_at=at(2), status="withdrawn")
    actions = [offer_action(o, at(2), "sent"), offer_action(o, at(3), "withdrawn", "sent"),
               NS(id=uuid4(), kind="resolve", node_key=f"offer_exception:{o.id}:withdrawn", occurred_at=at(3, 2),
                  actor_id=None, reason="已关闭招聘流程", details={})]
    assert node(flow.report(now=at(10), offers=[o], actions=actions), f"offer:{o.id}")["complete"]


@pytest.mark.parametrize("withdraw_day,late", [(3, False), (6, True)])
def test_withdrawing_unsent_offer_stops_future_send_tasks_and_preserves_prior_lateness(flow, withdraw_day, late):
    flow.resume.status = "interview_passed"
    i = interview(decided=at(2, 6))
    o = offer(status="withdrawn")
    rows = flow.report(now=at(10), interviews=[i], offers=[o],
                       actions=[offer_action(o, at(withdraw_day), "withdrawn", "draft")])
    n = node(rows, f"interview:{i.id}")
    assert n["business_status"] == "completed"
    assert n["overdue"] == late
    assert any(f["business_stopped"] and "发送Offer" in f["label"] for f in n["fields"])


def test_resent_offer_waits_without_periodic_followup_scoring(flow):
    o = offer(sent_at=at(5, 2), status="sent", valid_until=at(16))
    actions = [offer_action(o, at(2), "sent"), offer_action(o, at(3), "rejected", "sent"),
               offer_action(o, at(5), "pending", "rejected"), offer_action(o, at(5, 2), "sent", "pending")]
    n = node(flow.report(now=at(12), offers=[o], actions=actions), f"offer:{o.id}")
    assert not n["overdue"] and not n["eligible"]
    assert any(f["started_at"] == at(5, 2) for f in n["fields"])


@pytest.mark.parametrize("kind", ["note", "follow_up", "resolve", "waive"])
def test_text_records_do_not_complete_or_reschedule_business_obligations(flow, kind):
    i = interview(ended_at=None, panels=[], result="pending")
    o = offer(status="accepted", sent_at=at(2), accepted_at=at(3), onboard_date=at(4), valid_until=at(2, 12))
    rows = flow.report(now=at(10), interviews=[i], offers=[o])
    keys = [f"attendance:{i.id}", f"offer_expiry:{o.id}", f"onboarding:{o.id}"]
    records = [NS(id=uuid4(), kind=kind, node_key=key, occurred_at=at(5), actor_id=None,
                  reason="已经处理", details={}) for key in keys]
    updated = flow.report(now=at(10), interviews=[i], offers=[o], actions=records)
    assert service.metrics(rows) == service.metrics(updated)
    for key in keys:
        before, after = node(rows, key), node(updated, key)
        assert before["fields"] == after["fields"]
        assert before["status"] == after["status"]
        assert after["actions"][0]["kind"] == kind


def test_late_interview_reschedule_preserves_the_previous_miss(flow):
    i = interview(ended_at=None, panels=[], interview_time=at(12), interview_end_time=at(12, 2))
    changed = NS(id=uuid4(), kind="rescheduled", node_key=f"interview:{i.id}", occurred_at=at(6),
                 actor_id=None, reason="业务页面改期", details={
                     "old_interview_end_time": at(2, 4).isoformat(),
                     "interview_end_time": at(12, 2).isoformat(), "valid_schedule": True})
    n = node(flow.report(now=at(10), interviews=[i], actions=[changed]), f"attendance:{i.id}")
    assert n["status"] == "late" and n["overdue"]
    assert n["fields"][0]["completed_at"] == at(6)


def test_cancelled_interview_requires_actual_new_schedule(flow):
    i = interview(ended_at=None, panels=[], cancelled_at=at(3))
    key = f"cancel:{i.id}"
    record = NS(id=uuid4(), kind="resolve", node_key=key, occurred_at=at(3, 2),
                actor_id=None, reason="已沟通", details={})
    assert node(flow.report(now=at(9), interviews=[i], actions=[record]), key)["status"] == "missing"
    second = interview(created=at(6), round=2, ended_at=None, panels=[],
                       interview_time=at(12), interview_end_time=at(12, 2))
    assert node(flow.report(now=at(9), interviews=[i, second], actions=[record]), key)["status"] == "late"


@pytest.mark.parametrize("status", [ResumeStatus.WAITLIST, ResumeStatus.REJECTED])
def test_responsible_hr_can_append_notes_without_changing_paused_or_finished_flow(db, test_admin, test_user, monkeypatch, status):
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, at(2))
    clock[0] = at(3)
    r.status = status
    db.commit()
    before = service.overview(db, test_user)
    n = node(before["nodes"], "screening")
    result = service.record_action(db, test_user, n["binding_id"], n["key"],
                                   ActionRequest(kind="note", reason="补充沟通结果"))
    after = service.overview(db, test_user)
    record = db.query(QualityAction).filter(QualityAction.id == result["id"]).one()
    assert record.actor_id == test_user.id and record.reason == "补充沟通结果"
    assert r.status == status
    assert before["summary"] == after["summary"]
    assert n["fields"] == node(after["nodes"], "screening")["fields"]


def test_old_policy_followup_setting_is_ignored():
    rules = QualityRules.model_validate({"follow_up_days": 7, "exception_days": 3})
    assert "follow_up_days" not in rules.model_dump()
    assert rules.exception_days == 3


@pytest.mark.parametrize("completion", ["ended_at", "cancelled_at"])
def test_late_interview_business_result_keeps_the_attendance_miss(flow, completion):
    i = interview(ended_at=None, panels=[])
    setattr(i, completion, at(6))
    n = node(flow.report(now=at(9), interviews=[i]), f"attendance:{i.id}")
    assert n["status"] == "late" and n["overdue"]
    assert n["fields"][0]["completed_at"] == at(6)


def test_real_interview_reschedule_audits_original_end_after_session_expiry(db, test_admin, test_user, monkeypatch):
    from app.models.models import Interview, InterviewStatus
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, at(2))
    i = Interview(tenant_id=r.tenant_id, resume_id=r.id, position_id=r.position_id,
                  interviewer_id=test_user.id, interview_time=at(2, 3), interview_end_time=at(2, 4),
                  interview_type="onsite", interview_location="会议室", status=InterviewStatus.SCHEDULED)
    db.add(i)
    db.commit()
    iid = i.id
    db.expire_all()
    clock[0] = at(6)
    i.interview_time = at(12)
    i.interview_end_time = at(12, 2)
    db.commit()
    record = db.query(QualityAction).filter(QualityAction.kind == "rescheduled",
                                           QualityAction.node_key == f"interview:{iid}").one()
    assert utc(record.details["old_interview_end_time"]) == at(2, 4)
    assert record.details["valid_schedule"]
    n = node(service.overview(db, test_user)["nodes"], f"attendance:{iid}")
    assert n["status"] == "late"


def test_extending_offer_reply_date_does_not_clear_a_previous_expiry_miss(flow):
    o = offer(sent_at=at(2), status="sent", valid_until=at(16))
    change = NS(id=uuid4(), kind="offer_dates", node_key=f"offer:{o.id}", occurred_at=at(9),
                actor_id=None, reason="延长答复期限", details={"old_valid_until": at(4).isoformat(), "new_valid_until": at(16).isoformat()})
    rows = flow.report(now=at(10), offers=[o], actions=[offer_action(o, at(2), "sent"), change])
    assert node(rows, f"offer_expiry:{o.id}")["overdue"]


def test_moving_onboard_date_does_not_clear_a_previous_registration_miss(flow):
    o = offer(sent_at=at(2), status="accepted", accepted_at=at(3), onboard_date=at(16))
    change = NS(id=uuid4(), kind="offer_dates", node_key=f"offer:{o.id}", occurred_at=at(9),
                actor_id=None, reason="延期到岗", details={"old_onboard_date": at(4).isoformat(), "new_onboard_date": at(16).isoformat()})
    rows = flow.report(now=at(10), offers=[o], actions=[offer_action(o, at(3), "accepted", "sent"), change])
    assert node(rows, f"onboarding:{o.id}")["overdue"]


def test_timely_onboarding_date_change_does_not_create_a_false_miss(flow):
    o = offer(status="accepted", accepted_at=at(3), onboard_date=at(16))
    change = NS(id=uuid4(), kind="offer_dates", node_key=f"offer:{o.id}", occurred_at=at(3, 3),
                actor_id=None, reason="提前协商延期", details={"old_onboard_date": at(4).isoformat(), "new_onboard_date": at(16).isoformat()})
    n = node(flow.report(now=at(10), offers=[o], actions=[change]), f"onboarding:{o.id}")
    assert not n["overdue"] and not n["eligible"]


def test_acceptance_correction_preserves_old_onboarding_lateness(flow):
    o = offer(status="rejected", accepted_at=None, rejected_at=at(9), onboard_date=at(4))
    actions = [offer_action(o, at(3), "accepted", "sent"), offer_action(o, at(9), "rejected", "accepted")]
    rows = flow.report(now=at(10), offers=[o], actions=actions)
    assert node(rows, f"onboarding:{o.id}")["overdue"]


def test_return_to_position_with_unchanged_screening_status_creates_a_cycle(db, test_admin, test_user, monkeypatch):
    clock = [at(2)]
    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    service.publish_policy(db, test_admin, PolicyRequest())
    first, r = candidate(db, test_user, at(2))
    second = Position(tenant_id=test_user.tenant_id, title="另一个岗位", description="岗位描述", hiring_manager_id=test_user.id)
    db.add(second)
    db.commit()
    clock[0] = at(3)
    r.position_id = second.id
    db.commit()
    clock[0] = at(6)
    r.position_id = first.id
    db.commit()
    clock[0] = at(9)
    report = service.overview(db, test_user)
    rows = report["nodes"]
    restored = next(n for n in rows if n["position_id"] == first.id)
    assert restored["key"].startswith("cycle:")
    assert restored["due_at"] == at(10)
    assert not restored["overdue"]
    assert len(report["flows"]) == 1
    assert report["flows"][0]["is_current"]
    assert report["flows"][0]["position_id"] == first.id
    assert {p["id"] for p in report["positions"]} == {first.id}
    assert {n["flow_id"] for n in rows} == {report["flows"][0]["id"]}


def test_public_offer_response_keeps_audit_in_the_atomic_bulk_update_path(db, test_admin, test_user):
    from app.models.models import Offer, OfferStatus
    from app.services.offer_service import confirm_offer_by_token
    from app.services.public_token_service import issue_public_token
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, datetime.now(timezone.utc))
    o = Offer(tenant_id=r.tenant_id, resume_id=r.id, position_id=r.position_id,
              candidate_name=r.candidate_name, candidate_email="candidate@example.com", position_title="工程师",
              status=OfferStatus.SENT, sent_at=datetime.utcnow(), valid_until=datetime.utcnow() + timedelta(days=2))
    db.add(o)
    db.commit()
    oid = o.id
    rid = r.id
    token = issue_public_token(db, r.tenant_id, "offer", oid, datetime.now(timezone.utc) + timedelta(days=1))
    db.expunge_all()
    result = confirm_offer_by_token(db, token, "reject", reason="个人安排变化")
    assert result["success"]
    record = db.query(QualityAction).filter(QualityAction.kind == "offer_transition",
                                           QualityAction.node_key == f"offer:{oid}").all()
    assert any(a.details["new_status"] == "rejected" and a.actor_id is None for a in record)
    assert db.query(ResumeStatusEvent).filter(ResumeStatusEvent.resume_id == rid,
                                            ResumeStatusEvent.source == "offer_public_response").count() == 1


def test_offer_date_changes_keep_the_old_value_even_after_session_expiry(db, test_admin, test_user):
    from app.models.models import Offer, OfferStatus
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, datetime.now(timezone.utc))
    original = datetime.utcnow() + timedelta(days=1)
    o = Offer(tenant_id=r.tenant_id, resume_id=r.id, position_id=r.position_id,
              candidate_name=r.candidate_name, candidate_email="candidate@example.com", position_title="工程师",
              status=OfferStatus.SENT, valid_until=original)
    db.add(o)
    db.commit()
    o.valid_until = original + timedelta(days=10)
    db.commit()
    record = db.query(QualityAction).filter(QualityAction.kind == "offer_dates").one()
    assert utc(record.details["old_valid_until"]) == utc(original)


def test_final_interview_decision_is_sufficient_without_individual_review_fields(flow):
    i = interview(decided=at(2, 6), ended_at=None, panels=[])
    o = offer(sent_at=at(3), status="sent")
    n = node(flow.report(now=at(4), interviews=[i], offers=[o]), f"interview:{i.id}")
    assert n["complete"]
    assert all(not item["label"].startswith("面试官") for item in n["fields"])


def test_flow_context_includes_scheduled_rounds_without_adding_scored_nodes(flow):
    first = interview(decided=at(2, 6), result="next_round")
    second = interview(created=at(3), round=2, panels=[], ended_at=None, result="pending",
                       interview_time=at(6), interview_end_time=at(6, 2))
    rows = flow.report(now=at(4), interviews=[first, second])
    assert all(n["flow_id"] == rows[0]["flow_id"] for n in rows)
    assert [i["round"] for i in rows[0]["_flow"]["interviews"]] == [1, 2]
    assert not any(n["key"] == f"interview:{second.id}" for n in rows)


def test_api_exposes_one_flow_context_per_application_without_internal_fields(client, db, test_admin, test_user, admin_auth_headers):
    service.publish_policy(db, test_admin, PolicyRequest())
    _, r = candidate(db, test_user, datetime.now(timezone.utc))
    response = client.get("/api/recruitment-quality/overview", headers=admin_auth_headers)
    assert response.status_code == 200
    data = response.json()
    context = next(f for f in data["flows"] if f["resume_id"] == str(r.id))
    assert context["is_current"]
    assert context["status"] == "pending_screening"
    rows = [n for n in data["nodes"] if n["resume_id"] == str(r.id)]
    assert all(n["flow_id"] == context["id"] and "_flow" not in n for n in rows)


def test_overview_date_range_filters_whole_flows_and_metrics_in_beijing_time(db, test_admin, test_user, monkeypatch):
    monkeypatch.setattr(service, "now_utc", lambda: at(1))
    service.publish_policy(db, test_admin, PolicyRequest())
    # Beijing Nov 2 starts at Nov 1 16:00 UTC and ends just before Nov 2 16:00.
    starts = [at(1, 15), at(1, 16), at(2, 15) + timedelta(minutes=59), at(2, 16)]
    resumes = [candidate(db, test_user, started)[1] for started in starts]
    monkeypatch.setattr(service, "now_utc", lambda: at(10))
    report = service.overview(db, test_admin, start_date=date(2026, 11, 2), end_date=date(2026, 11, 2))
    expected = {r.id for r in resumes[1:3]}
    assert {f["resume_id"] for f in report["flows"]} == expected
    assert {n["resume_id"] for n in report["nodes"]} == expected
    assert report["summary"]["required_nodes"] == 2
    assert report["people"][0]["candidate_count"] == 2
    assert report["people"][0]["required_nodes"] == 2
    assert len(service.overview(db, test_admin)["flows"]) == 4
    assert len(service.overview(db, test_admin, start_date=date(2026, 11, 3))["flows"]) == 1
    assert len(service.overview(db, test_admin, end_date=date(2026, 11, 1))["flows"]) == 1
    empty = service.overview(db, test_admin, cohort="historical", start_date=date(2026, 11, 2))
    assert empty["flows"] == empty["nodes"] == empty["people"] == []
    assert empty["summary"]["process_rate"] is None


@pytest.mark.parametrize("query", [
    "start_date=invalid", "end_date=2026-02-30",
    "start_date=2026-11-03&end_date=2026-11-02",
])
def test_overview_rejects_invalid_date_ranges(client, admin_auth_headers, query):
    assert client.get(f"/api/recruitment-quality/overview?{query}", headers=admin_auth_headers).status_code == 422


def test_unscored_transfer_keeps_flow_history_without_inventing_required_nodes(flow):
    end = NS(kind="transferred", occurred_at=at(3), node_key="process", actor_id=None, reason="简历转岗", details={})
    contexts = {}
    rows = build_candidate_nodes(flow.binding, flow.position, flow.resume, [flow.policy], [end],
                                 [], [], [], [], at(4), flow_contexts=contexts)
    assert rows == []
    context = next(iter(contexts.values()))
    assert context["ended_at"] == at(3)
    assert context["end_reason"] == "transfer"
    assert not context["is_current"]
