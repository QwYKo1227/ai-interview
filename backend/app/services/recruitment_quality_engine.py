"""Reconstruct stage obligations from business evidence, never from current fields alone."""
from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from types import SimpleNamespace

from app.schemas.recruitment_quality import QualityRules
from app.services.recruitment_quality_links import business_href
from app.services.recruitment_workdays import COMPANY_TZ, add_workdays

EARLY = {"pending_screening", "pending_review", "auto_rejected_pending_review"}
TERMINAL = {"rejected", "interview_failed", "offer_rejected", "completed", "departed"}
SCREEN_RESULTS = {"pending_dept_review", "pending_interview", "rejected", "waitlist"}


def utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def val(value):
    return getattr(value, "value", value)


def day_end(value):
    return datetime.combine(utc(value).astimezone(COMPANY_TZ).date(), time.max, COMPANY_TZ).astimezone(timezone.utc)


def policy_at(policies, position_id, at):
    available = [p for p in policies if utc(p.created_at) <= at]
    # Historical applications use the earliest published rules when there was
    # no policy at the event time. No historical operation timestamp is invented.
    if not available:
        available = [policies[0]]
    return next((p for p in reversed(available) if p.position_id == position_id),
                next(p for p in reversed(available) if p.position_id is None))


def owner_at(position, at):
    history = sorted(position.hiring_manager_history or [], key=lambda h: utc(h["changed_at"]))
    owner = position.hiring_manager_id
    for item in reversed(history):
        if utc(item["changed_at"]) > at:
            owner = UUID(item["old_owner_id"]) if item.get("old_owner_id") else None
    return owner


def valid_schedule(interview):
    location = (bool((interview.interview_location or "").strip()) if interview.interview_type == "onsite"
                else (interview.meeting_link or "").startswith(("https://", "http://")) if interview.interview_type == "video"
                else True)
    return bool(interview.interview_time and interview.interview_end_time
                and utc(interview.interview_end_time) > utc(interview.interview_time)
                and (interview.panel_members or interview.panels or interview.interviewer_id) and location)


class CandidateFlow:
    def __init__(self, binding, position, resume, policies, actions, events, now):
        self.binding, self.position, self.resume = binding, position, resume
        self.policies, self.actions, self.now = policies, sorted(actions, key=lambda a: utc(a.occurred_at)), now
        self.start = utc(binding.started_at)
        transferred = next((utc(a.occurred_at) for a in self.actions if a.kind == "transferred"), None)
        self.transitions = [{"at": utc(a.occurred_at), "actor_id": a.actor_id, **a.details}
                            for a in self.actions if a.kind == "transition" and (not transferred or utc(a.occurred_at) <= transferred)]
        # Prefer actual operation audits over status events with backdated
        # business dates (notably interview-end and onboarding-date events).
        for e in events:
            if e.source in {"interview", "onboarding_confirmation"}:
                continue
            if not any(t["new_status"] == e.new_status and abs((t["at"] - utc(e.occurred_at)).total_seconds()) < 2
                       for t in self.transitions):
                self.transitions.append({"at": utc(e.occurred_at), "actor_id": e.actor_id,
                                         "old_status": e.old_status, "new_status": e.new_status})
        self.transitions = sorted([t for t in self.transitions if self.start <= t["at"] <= min(now, transferred or now)], key=lambda t: t["at"])
        self.cutoff = transferred
        self.ends = [t["at"] for t in self.transitions if t["new_status"] in TERMINAL - {"completed", "departed"}]
        if transferred:
            self.ends.append(transferred)
        self.pauses = []
        pause = None
        for t in self.transitions:
            if t["new_status"] == "waitlist" and pause is None:
                pause = t["at"]
            elif t["new_status"] != "waitlist" and pause is not None:
                self.pauses.append((pause, t["at"]))
                pause = None
        if pause is not None:
            self.pauses.append((pause, None))
        if val(resume.status) == "waitlist" and not self.pauses:
            # A legacy waitlist without entry time cannot establish past
            # lateness; current outstanding work is nevertheless paused.
            self.pauses.append((self.start, None))
        self.groups = {}

    def transition(self, old=None, new=None, after=None):
        return next((t for t in self.transitions
                     if (old is None or t.get("old_status") in old)
                     and (new is None or t["new_status"] in new)
                     and (after is None or t["at"] >= after)), None)

    def actions_for(self, key, kind):
        return [a for a in self.actions if a.node_key == key and a.kind == kind]

    def requirement(self, key, stage, label, item, start, done, rule, *, unknown=False, stop_on_end=False, stop_at=None):
        group = self.groups.setdefault(key, {"stage": stage, "label": label, "requirements": []})
        start, done = utc(start), utc(done)
        if done and done > self.now:
            done = None
        if start is None:
            group["requirements"].append({"label": item, "rule": rule, "unknown": True, "done": done, "eligible": False})
            return
        if stop_at is not None and stop_at < start and (done is None or done >= stop_at):
            return
        policy = policy_at(self.policies, self.position.id, start)
        rule_days = getattr(QualityRules.model_validate(policy.rules), rule)
        due = failure_due = None
        calendar_error = None
        try:
            due = add_workdays(start, rule_days)
        except NotImplementedError as exc:
            calendar_error = str(exc)
        paused = False
        end_at = min(done or self.now, self.now)
        # Entering waitlist pauses unfinished work. Leaving it grants a full
        # new term, but a miss before entering waitlist stays a miss.
        if due is not None:
            for begin, end in self.pauses:
                if begin < start and end is not None and end <= start:
                    continue
                if begin >= end_at:
                    continue
                if begin > due:
                    failure_due = failure_due or due
                if end is None or end > end_at:
                    paused = True
                    break
                start = end
                policy = policy_at(self.policies, self.position.id, start)
                try:
                    due = add_workdays(start, getattr(QualityRules.model_validate(policy.rules), rule))
                except NotImplementedError as exc:
                    calendar_error, due = str(exc), None
                    break
        stops = [t for t in self.ends if stop_on_end and start <= t <= end_at]
        if self.cutoff is not None and start <= self.cutoff <= end_at:
            stops.append(self.cutoff)
        if stop_at is not None and start <= stop_at <= end_at:
            stops.append(stop_at)
        stopped = min(stops, default=None)
        if stopped is not None:
            if due is not None and stopped > due:
                failure_due = failure_due or due
            elif failure_due is None:
                return  # A timely valid termination cancels future progression.
        if due is not None and not paused and end_at > due:
            failure_due = failure_due or due
        known = not unknown and not calendar_error
        late = known and failure_due is not None
        eligible = known and (late or (done is not None and done <= self.now))
        group["requirements"].append({"label": item, "rule": rule, "start": start, "done": done, "due": due,
                                      "failure_due": failure_due, "policy": policy, "paused": paused,
                                      "unknown": not known, "calendar_error": calendar_error,
                                      "late": late, "eligible": eligible, "stopped": stopped is not None})

    def waiting(self, key, stage, label, item, start, end):
        """Show business waiting periods without deadlines or scoring points."""
        start, end = utc(start), utc(end)
        if start is None or start > self.now:
            return
        end = end if end and end <= self.now else None
        stopped = min((t for t in self.ends if t >= start), default=None)
        done = min((t for t in (end, stopped) if t), default=None)
        group = self.groups.setdefault(key, {"stage": stage, "label": label, "requirements": []})
        group["requirements"].append({
            "label": item, "rule": None, "start": start, "done": done,
            "unknown": False, "informational": True,
            "paused": done is None and any(begin <= self.now and finish is None for begin, finish in self.pauses),
        })

    def nodes(self):
        result = []
        for key, group in self.groups.items():
            reqs = group["requirements"]
            if not reqs:
                continue
            late = [r for r in reqs if r.get("late")]
            unknown = any(r["unknown"] for r in reqs)
            pending = [r for r in reqs if not r.get("done") and not r.get("stopped")
                       and not r.get("business_completed") and not r.get("business_stopped")]
            paused = any(r.get("paused") for r in pending)
            complete = not late and not unknown and not pending
            eligible = bool(late or (complete and any(not r.get("informational") and not r.get("business_stopped") for r in reqs)))
            status = "late" if late and not pending else "missing" if late else "unknown" if unknown else "paused" if paused else "complete" if complete else "pending"
            failure_due = min((r["failure_due"] for r in late), default=None)
            due = failure_due or min((r["due"] for r in pending if r.get("due")), default=None)
            # A completed node freezes on completion; an overdue node freezes
            # on the first missed deadline; open work follows the current HR.
            frozen_at = failure_due or (max((r["done"] for r in reqs if r.get("done")), default=self.now) if complete else self.now)
            owner = owner_at(self.position, frozen_at)
            policy = next((r["policy"] for r in reqs if r.get("policy")), self.policies[0])
            evidence = []
            fields = []
            for r in reqs:
                valid = bool(r.get("done") and not r.get("late") and not r["unknown"])
                detail = "已完成（缺少时间记录）" if r.get("business_completed") else "已终止" if r.get("business_stopped") else "缺少可追溯时间" if r["unknown"] else "逾期" if r.get("late") else "已完成" if valid and r.get("informational") else "按期完成" if valid else "备选暂停" if r.get("paused") else "等待办理"
                fields.append({"label": r["label"], "valid": valid, "status": detail,
                               "started_at": r.get("start"), "completed_at": r.get("done"), "due_at": r.get("due"),
                               "late_due_at": r.get("failure_due"),
                               "policy_version": r["policy"].version if r.get("policy") else None,
                               "business_completed": bool(r.get("business_completed")),
                               "business_stopped": bool(r.get("business_stopped"))})
                if r.get("calendar_error"):
                    evidence.append("该年度工作日历尚未覆盖，暂不据此判定逾期")
                if r.get("done"):
                    evidence.append(f'{r["label"]}：{r["done"].astimezone(COMPANY_TZ).strftime("%Y-%m-%d %H:%M")}')
            action_rows = [a for a in self.actions if a.node_key == key or a.kind == "transition"]
            result.append({"id": f"{self.binding.id}/{key}", "binding_id": self.binding.id, "key": key,
                           "position_id": self.position.id, "position_title": self.position.title,
                           "resume_id": self.resume.id, "candidate_name": self.resume.candidate_name or "姓名待补齐",
                           "owner_id": owner, "executor_id": self.position.hiring_manager_id, "stage": group["stage"], "label": group["label"],
                           "status": status, "eligible": eligible, "complete": complete,
                           "timeliness_status": "not_applicable" if all(r.get("informational") for r in reqs) and not unknown else status,
                           "business_status": group.get("business_status", "completed" if not pending else "pending"),
                           "business_result": group.get("business_result", ""),
                           "historical": self.start < utc(self.policies[0].created_at), "fields": fields,
                           "missing": list(dict.fromkeys(f["label"] for f in fields if not f["valid"])),
                           "due_at": due, "paused": paused, "overdue": bool(late),
                           "overdue_hours": round(max((self.now - failure_due).total_seconds(), 0) / 3600, 1) if failure_due else 0,
                           "href": "",
                           "policy_id": policy.id, "policy_name": policy.name, "policy_version": policy.version,
                           "evidence": list(dict.fromkeys(evidence)),
                           "actions": [{"kind": a.kind, "reason": a.reason, "actor_id": a.actor_id,
                                        "occurred_at": a.occurred_at, "details": a.details} for a in action_rows]})
        return result


def build_candidate_nodes(binding, position, resume, policies, actions, interviews, reviews, offers, events, now, *, flow_contexts=None):
    restarts = sorted({utc(a.occurred_at) for a in actions if a.kind == "transition"
                       and (a.details.get("process_restart")
                            or (a.details.get("old_status") in TERMINAL and a.details.get("new_status") in EARLY))
                       and utc(a.occurred_at) > utc(binding.started_at)})
    if not restarts:
        return build_cycle_nodes(binding, position, resume, policies, actions, interviews, reviews, offers, events, now, flow_contexts=flow_contexts)
    result = []
    starts = [utc(binding.started_at), *restarts]
    for index, start in enumerate(starts):
        if start > now:
            continue
        stop = starts[index + 1] if index + 1 < len(starts) else None
        cycle_actions = [a for a in actions if utc(a.occurred_at) >= start and (stop is None or utc(a.occurred_at) < stop)]
        prefix = f"cycle:{start.strftime('%Y%m%d%H%M%S%f')}/" if index else ""
        if prefix:
            cycle_actions = [SimpleNamespace(**{**vars(a), "node_key": a.node_key.removeprefix(prefix)})
                             if a.node_key.startswith(prefix) else a for a in cycle_actions]
        cycle_events = [e for e in events if utc(e.occurred_at) >= start and (stop is None or utc(e.occurred_at) < stop)]
        if stop:
            cycle_actions.append(SimpleNamespace(kind="transferred", occurred_at=stop, node_key="process", actor_id=None, reason="流程重新开始", details={}))
        cycle = SimpleNamespace(id=binding.id, started_at=start, position_id=position.id, resume_id=resume.id)
        rows = build_cycle_nodes(cycle, position, resume, policies, cycle_actions,
                                 [i for i in interviews if not stop or utc(i.created_at) < stop],
                                 [r for r in reviews if not stop or utc(r.created_at) < stop],
                                 [o for o in offers if not stop or utc(o.created_at) < stop], cycle_events, now, flow_contexts=flow_contexts)
        if index:
            for row in rows:
                row["key"] = prefix + row["key"]
                row["id"] = f'{binding.id}/{row["key"]}'
                row["label"] = f'第{index + 1}次流程 · {row["label"]}'
        result.extend(rows)
    return result


def build_cycle_nodes(binding, position, resume, policies, actions, interviews, reviews, offers, events, now, *, flow_contexts=None):
    cutoff = min((utc(a.occurred_at) for a in actions if a.kind == "transferred"), default=None)
    if cutoff:
        actions = [a for a in actions if utc(a.occurred_at) <= cutoff]
        events = [e for e in events if utc(e.occurred_at) <= cutoff]
    flow = CandidateFlow(binding, position, resume, policies, actions, events, now)
    interviews = sorted([i for i in interviews if utc(i.created_at) >= flow.start], key=lambda i: utc(i.created_at))
    reviews = [r for r in reviews if r.reviewed_position_id in {None, position.id} and utc(r.created_at) >= flow.start]
    offers = sorted([o for o in offers if utc(o.created_at) >= flow.start], key=lambda o: utc(o.created_at))
    from app.services.recruitment_quality_state import current_business_status, project_business_facts
    flow.business_status = current_business_status(resume, reviews, interviews, offers)
    valid_interviews = [i for i in interviews if valid_schedule(i)]
    def scheduled_at(interview):
        return min((utc(a.occurred_at) for a in actions if a.kind == "schedule_saved"
                    and a.node_key == f"interview:{interview.id}"), default=utc(interview.created_at))
    screen = next((t for t in flow.transitions if t.get("old_status") in EARLY | {None}
                   and t["new_status"] in SCREEN_RESULTS and (t.get("actor_id") or t.get("manual_decision"))), None)
    # A restored legacy application can have state evidence without a timestamp.
    legacy_screen = screen is None and flow.start < utc(policies[0].created_at) and (
        resume.manual_screening_decision or bool(reviews or interviews or offers) or val(resume.status) not in EARLY | {"waitlist"})
    screen_at = screen["at"] if screen else None
    flow.requirement("screening", "screening", "初筛", "及时提交初筛结果", flow.start, screen_at,
                     "screening_days", unknown=legacy_screen)
    progressed = screen and screen["new_status"] not in {"rejected", "waitlist"}
    if progressed:
        required = (QualityRules.model_validate(policy_at(policies, position.id, screen_at).rules).department_review_required
                    or screen["new_status"] == "pending_dept_review" or bool(reviews))
        next_at = min((utc(r.created_at) for r in reviews), default=None) if required else next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) >= screen_at), None)
        flow.requirement("screening", "screening", "初筛",
                         "通过后及时指派部门评审" if required else "通过后及时安排首轮面试",
                         screen_at, next_at, "department_assignment_days" if required else "interview_arrangement_days", stop_on_end=True)
    elif screen and screen["new_status"] == "waitlist":
        recovered = flow.transition(old={"waitlist"}, after=screen_at)
        if recovered and recovered["new_status"] not in TERMINAL:
            required = (QualityRules.model_validate(policy_at(policies, position.id, recovered["at"]).rules).department_review_required
                        or recovered["new_status"] == "pending_dept_review" or bool(reviews))
            next_at = min((utc(r.created_at) for r in reviews if utc(r.created_at) >= recovered["at"]), default=None) if required else next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) >= recovered["at"]), None)
            flow.requirement("screening", "screening", "初筛", "备选恢复后及时推进", recovered["at"], next_at,
                             "department_assignment_days" if required else "interview_arrangement_days", stop_on_end=True)
    if reviews:
        label, key = "部门评审", "department"
        assigned = min(utc(r.created_at) for r in reviews)
        ready = max(utc(r.completed_at) for r in reviews) if all(r.is_completed and r.completed_at for r in reviews) else None
        decision = flow.transition(old={"pending_hr_decision", "pending_dept_review"}, new={"pending_interview", "rejected", "waitlist"}, after=ready) if ready else None
        flow.waiting(key, "department", label, "等待部门评审意见", assigned, ready)
        if ready:
            at = decision["at"] if decision else None
            flow.requirement(key, "department", label, "评审交齐后及时提交HR决策", ready, at, "department_decision_days",
                             unknown=decision is None and flow.start < utc(policies[0].created_at)
                             and val(resume.status) not in {"pending_dept_review", "pending_hr_decision", "waitlist"})
            if decision and decision["new_status"] == "pending_interview":
                arranged = next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) >= at), None)
                flow.requirement(key, "department", label, "通过后及时安排面试", at, arranged, "interview_arrangement_days", stop_on_end=True)
            elif decision and decision["new_status"] == "waitlist":
                recovered = flow.transition(old={"waitlist"}, after=at)
                if recovered and recovered["new_status"] not in TERMINAL:
                    arranged = next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) >= recovered["at"]), None)
                    flow.requirement(key, "department", label, "备选恢复后及时安排面试", recovered["at"], arranged, "interview_arrangement_days", stop_on_end=True)
    for interview in interviews:
        key, label = f"interview:{interview.id}", f"第{interview.round or 1}轮面试"
        history = [h for h in interview.decision_history or [] if h.get("action") in {"confirmed", "corrected"} and h.get("at")
                   and (flow.cutoff is None or utc(h["at"]) <= flow.cutoff)]
        history.sort(key=lambda h: utc(h["at"]))
        first_decision = utc(history[0]["at"]) if history else utc(interview.final_decision_at)
        if first_decision and flow.cutoff and first_decision > flow.cutoff:
            first_decision = None
        migrated = not history and any(h.get("action") == "migrated" for h in interview.decision_history or [])
        cancelled = utc(interview.cancelled_at)
        ended = utc(interview.ended_at)
        submitted = [utc(p.human_review_submitted_at) for p in interview.panels if p.human_review_submitted_at]
        expected = len(interview.panel_members or interview.panels or [])
        ready = max(submitted) if expected and len(submitted) >= expected else None
        # Preserve previous scheduled ends after rescheduling. Only actual
        # business operations may settle an attendance obligation.
        updates = flow.actions_for(key, "rescheduled")
        for update in updates:
            previous_end = utc(update.details.get("old_interview_end_time"))
            handled = utc(update.occurred_at)
            if previous_end and previous_end < handled:
                done = min((t for t in (ended, ready, first_decision, cancelled,
                                       handled if update.details.get("valid_schedule", True) else None) if t), default=None)
                if done is None or done > previous_end:
                    flow.requirement(f"attendance:{interview.id}", "exception", f"第{interview.round or 1}轮面试进展",
                                     "及时更新面试进展或改期", previous_end, done, "exception_days", stop_on_end=True)
        scheduled_end = utc(interview.interview_end_time)
        progress = [t for t in (ended, ready, first_decision, cancelled) if t]
        progress += [utc(a.occurred_at) for a in updates
                     if scheduled_end and utc(a.occurred_at) >= scheduled_end and a.details.get("valid_schedule", True)]
        progressed_at = min(progress, default=None)
        if scheduled_end and scheduled_end < now and (progressed_at is None or progressed_at > scheduled_end):
            flow.requirement(f"attendance:{interview.id}", "exception", f"第{interview.round or 1}轮面试进展",
                             "及时更新面试进展或改期", scheduled_end, progressed_at, "exception_days", stop_on_end=True)
        if cancelled:
            exkey = f"cancel:{interview.id}"
            next_at = next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) > cancelled), None)
            flow.requirement(exkey, "exception", f"第{interview.round or 1}轮面试取消处理", "取消后及时重新安排面试", cancelled,
                             next_at, "interview_arrangement_days", stop_on_end=True)
            continue
        if ended:
            flow.waiting(key, "interview", label, "等待面试反馈", ended, ready or first_decision)
        if ended or ready or first_decision:
            start = (max(x for x in (ended, ready) if x is not None) if ended or ready
                     else utc(interview.interview_end_time) if first_decision else None)
            if ready or first_decision:
                flow.requirement(key, "interview", label, "及时提交面试最终决策", start, first_decision,
                                 "interview_decision_days", unknown=migrated)
        if first_decision:
            branches = []
            for h in history:
                result = h.get("to") if h.get("action") == "corrected" else h.get("result")
                if result and (not branches or branches[-1][1] != result):
                    branches.append((utc(h["at"]), result))
            if not branches:
                branches = [(first_decision, val(interview.result))]
            for index, (trigger, decision_result) in enumerate(branches):
                superseded = branches[index + 1][0] if index + 1 < len(branches) else None
                if decision_result in {"passed", "hired"}:
                    sent = first_offer_sent(offers, events, actions, trigger)
                    if superseded and sent and sent >= superseded:
                        sent = None
                    flow.requirement(key, "interview", label, "面试通过后及时首次发送Offer", trigger, sent, "offer_send_days",
                                     stop_on_end=True, unknown=migrated, stop_at=superseded)
                elif decision_result == "next_round":
                    arranged = next((scheduled_at(i) for i in valid_interviews if (i.round or 1) > (interview.round or 1)
                                     and scheduled_at(i) >= trigger and (not superseded or scheduled_at(i) < superseded)), None)
                    flow.requirement(key, "interview", label, "及时安排下一轮面试", trigger, arranged, "next_interview_days",
                                     stop_on_end=True, unknown=migrated, stop_at=superseded)
            if branches[-1][1] == "waitlist":
                trigger = branches[-1][0]
                recovered = flow.transition(old={"waitlist"}, after=trigger)
                if recovered and recovered["new_status"] not in TERMINAL:
                    if recovered["new_status"] in {"interview_passed", "offer_pending"}:
                        done = first_offer_sent(offers, events, actions, recovered["at"])
                        rule, text = "offer_send_days", "备选恢复后及时发送Offer"
                    else:
                        done = next((scheduled_at(i) for i in valid_interviews if scheduled_at(i) >= recovered["at"]), None)
                        rule, text = "next_interview_days", "备选恢复后及时安排面试"
                    flow.requirement(key, "interview", label, text, recovered["at"], done, rule, stop_on_end=True)
    for offer in offers:
        key, label = f"offer:{offer.id}", "Offer"
        signals = [(t, s) for t, s in offer_signals(offer, actions, events) if flow.cutoff is None or t <= flow.cutoff]
        if val(offer.status) == "withdrawn" and not any(s == "withdrawn" for _, s in signals):
            flow.requirement(key, "offer", label, "历史撤回时间无法核实", None, None, "exception_days", unknown=True)
            continue
        sends = [t for t, s in signals if s == "sent"]
        for index, sent in enumerate(sends):
            next_send = sends[index + 1] if index + 1 < len(sends) else None
            ended = next((t for t, s in signals if t >= sent and s in {"accepted", "rejected", "withdrawn", "expired"}), None)
            boundary = min((t for t in (ended, next_send) if t), default=None)
            for begin, deadline, changed in date_versions(offer, actions, "valid_until", sent, boundary):
                end = min((t for t in (boundary, deadline, changed) if t), default=None)
                flow.waiting(key, "offer", label, "等待Offer答复", begin, end)
                if deadline and deadline < now and (boundary is None or deadline < boundary) and (changed is None or deadline < changed):
                    exkey = f"offer_expiry:{offer.id}"
                    handling = [t for t, s in signals if t >= deadline and s in {"withdrawn", "pending", "accepted", "rejected"}]
                    if changed:
                        handling.append(changed)
                    processed = min(handling, default=None)
                    flow.requirement(exkey, "exception", "Offer到期处理", "到期后及时登记后续处理",
                                     deadline, processed, "exception_days", stop_on_end=True)
        for at, status in signals:
            if status in {"withdrawn", "rejected"}:
                exkey = f"offer_exception:{offer.id}:{status}"
                # Withdrawal/rejection itself is a business outcome. Further
                # recruitment is optional; no free-text resolution is required.
                flow.waiting(exkey, "exception", "Offer异常处理",
                             "Offer已撤回" if status == "withdrawn" else "Offer已拒绝", at, at)
            elif status == "pending":
                previous = [s for t, s in signals if t < at]
                if previous and previous[-1] in {"expired", "withdrawn", "rejected", "accepted"}:
                    resent = next((t for t in sends if t > at), None)
                    flow.requirement(f"offer_reopen:{offer.id}:{at.isoformat()}", "offer", "Offer重新发送",
                                     "重新开启后及时发送Offer", at, resent, "offer_send_days", stop_on_end=True)
            elif status == "accepted":
                # Keep historical accepted intervals even if a later correction
                # clears accepted_at or changes the current Offer status.
                cancelled = next((t for t, s in signals if t > at and s in {"rejected", "withdrawn", "pending"}), None)
                for _, date, changed in date_versions(offer, actions, "onboard_date", at, cancelled):
                    onkey = f"onboarding:{offer.id}"
                    recorded = utc(offer.onboarding_recorded_at)
                    anchor = day_end(date) if date else None
                    done = min((t for t in (recorded, cancelled, changed)
                                if t and (t == recorded or (anchor and t >= anchor))), default=None)
                    stop = min((t for t in (cancelled, changed) if t), default=None)
                    flow.requirement(onkey, "onboarding", "入职结果登记", "及时确认入职、调整入职日期或变更Offer状态",
                                     anchor, done, "result_update_days", stop_at=stop,
                                     unknown=bool(offer.actual_onboarded_at and not recorded))
    project_business_facts(flow, reviews, interviews, offers)
    nodes = flow.nodes()
    is_current = flow.cutoff is None and getattr(resume, "position_id", position.id) == position.id
    flow_status = flow.business_status if is_current else (
        flow.transitions[-1]["new_status"] if flow.transitions else "historical")
    previous_status = next((t.get("old_status") for t in reversed(flow.transitions)
                            if t["new_status"] == flow_status and t.get("old_status")), None)
    department_required = any(n["stage"] == "department" for n in nodes)
    if flow_status in EARLY:
        department_required = department_required or QualityRules.model_validate(
            policy_at(policies, position.id, now).rules).department_review_required
    department_required = department_required or any(
        "指派部门评审" in field["label"] for n in nodes for field in n["fields"])
    context = {
        "id": f"{binding.id}/{flow.start.strftime('%Y%m%d%H%M%S%f')}",
        "binding_id": binding.id, "resume_id": resume.id, "position_id": position.id,
        "candidate_name": resume.candidate_name or "姓名待补齐",
        "position_title": position.title, "started_at": flow.start, "is_current": is_current,
        "status": flow_status, "previous_status": previous_status,
        "ended_at": flow.cutoff,
        "end_reason": next(("restart" if a.reason == "流程重新开始" else "transfer"
                            for a in actions if a.kind == "transferred"), None),
        "department_required": department_required, "owner_id": position.hiring_manager_id,
        "interviews": [{"id": i.id, "round": i.round or 1, "status": val(getattr(i, "status", None)),
                        "result": val(i.result), "scheduled_at": i.interview_time,
                        "ended_at": i.ended_at, "cancelled_at": i.cancelled_at}
                       for i in interviews if flow.cutoff is None or utc(i.created_at) <= flow.cutoff],
    }
    if flow_contexts is not None:
        flow_contexts[context["id"]] = context
    for row in nodes:
        pending_rules = {r["rule"] for r in flow.groups[row["key"]]["requirements"]
                         if not r.get("done") and not r.get("stopped")
                         and not r.get("business_completed") and not r.get("business_stopped")}
        row["href"] = business_href(
            row["key"], row["stage"], pending_rules, resume_id=resume.id, position_id=position.id,
            interviews=interviews, offers=offers,
            actionable=is_current and not row["paused"] and flow_status not in TERMINAL | {"waitlist"})
        row["flow_id"] = context["id"]
        row["_flow"] = context
    return nodes


def offer_signals(offer, actions, events):
    signals = [(utc(a.occurred_at), a.details["new_status"]) for a in actions
               if a.kind == "offer_transition" and a.node_key == f"offer:{offer.id}" and a.details.get("new_status")]
    signals += [(utc(e.occurred_at), "sent") for e in events if e.source == "offer_sent" and e.source_id == offer.id]
    for date, status in ((offer.sent_at, "sent"), (offer.accepted_at, "accepted"), (offer.rejected_at, "rejected")):
        if date and not any(s == status for _, s in signals):
            signals.append((utc(date), status))
    result = []
    for at, status in sorted(signals):
        if not any(s == status and abs((t - at).total_seconds()) < 2 for t, s in result):
            result.append((at, status))
    return result


def date_versions(offer, actions, field, start, end):
    changes = sorted([(utc(a.occurred_at), utc(a.details.get(f"old_{field}")), utc(a.details.get(f"new_{field}")))
                      for a in actions if a.node_key == f"offer:{offer.id}" and a.kind == "offer_dates"
                      and f"new_{field}" in a.details], key=lambda row: row[0])
    value = changes[0][1] if changes else utc(getattr(offer, field))
    for at, _, new in changes:
        if at <= start:
            value = new
    snapshots = [a for a in actions if a.kind == "offer_transition" and a.node_key == f"offer:{offer.id}"
                 and field in a.details and abs((utc(a.occurred_at) - start).total_seconds()) < 2]
    if snapshots:
        value = utc(snapshots[0].details[field])
    versions = [(start, value)]
    versions += [(at, new) for at, _, new in changes if at > start and (end is None or at < end)]
    return [(at, value, versions[index + 1][0] if index + 1 < len(versions) else None)
            for index, (at, value) in enumerate(versions)]


def first_offer_sent(offers, events, actions, after=None):
    ids = {str(o.id) for o in offers}
    times = [utc(e.occurred_at) for e in events if e.source == "offer_sent" and str(e.source_id) in ids]
    times += [utc(a.occurred_at) for a in actions if a.kind == "offer_transition"
              and a.details.get("offer_id") in ids and a.details.get("new_status") == "sent"]
    # sent_at is a valid legacy fallback, but may be overwritten on re-send.
    if not times:
        times = [utc(o.sent_at) for o in offers if o.sent_at]
    return min((t for t in times if after is None or t >= after), default=None)
