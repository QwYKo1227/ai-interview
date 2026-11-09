"""Business facts for every current recruitment stage, independent of timing.

Completed flags and actual results establish completion even for legacy rows
without timestamps. They never supply invented operation times or on-time credit.
"""
from datetime import timezone

EARLY = {"pending_screening", "pending_review", "auto_rejected_pending_review"}
TERMINAL = {"rejected", "interview_failed", "offer_rejected", "completed", "departed"}
REVIEW_RESULTS = {"recommend": "推荐", "not_recommend": "不推荐", "pending": "待定"}
INTERVIEW_RESULTS = {"passed": "通过", "hired": "录用", "rejected": "不通过", "next_round": "进入下一轮", "waitlist": "备选"}
OFFER_RESULTS = {"draft": "草稿，待发送", "pending": "待发送", "sent": "等待候选人答复",
                 "accepted": "已接受", "rejected": "已拒绝", "withdrawn": "已撤回",
                 "expired": "已到期", "departed": "已入职后离职"}


def value(item):
    return getattr(item, "value", item)


def current_business_status(resume, reviews, interviews, offers):
    """Resolve stale intermediate labels from actual records; respect final HR outcomes."""
    status = value(resume.status)
    if status in TERMINAL | EARLY | {"waitlist"}:
        return status
    if offers and status in {"interview_passed", "offer_pending", "offer_accepted", "onboarding"}:
        offer = offers[-1]
        offer_status = value(offer.status)
        if getattr(offer, "departed_at", None) or offer_status == "departed":
            return "departed"
        if getattr(offer, "actual_onboarded_at", None):
            return "completed"
        if offer_status == "accepted":
            return "offer_accepted"
        if offer_status == "rejected":
            return "offer_rejected"
        if offer_status in {"sent", "expired"}:
            return "offer_pending"
    if interviews and status in {"pending_interview", "interview_scheduled", "interview_in_progress",
                                 "pending_interview_result", "pending_next_interview"}:
        interview = max(interviews, key=lambda i: (i.round or 1, i.created_at))
        if value(getattr(interview, "status", None)) == "cancelled" or getattr(interview, "cancelled_at", None):
            return "pending_next_interview" if (interview.round or 1) > 1 else "pending_interview"
        result = value(interview.result)
        if result in INTERVIEW_RESULTS:
            return {"passed": "interview_passed", "hired": "interview_passed", "rejected": "interview_failed",
                    "next_round": "pending_next_interview", "waitlist": "waitlist"}[result]
        if value(getattr(interview, "status", None)) == "completed" or getattr(interview, "ended_at", None):
            return "pending_interview_result"
    if status == "pending_dept_review" and reviews and all(r.is_completed for r in reviews):
        return "pending_hr_decision"
    return status


def project_business_facts(flow, reviews, interviews, offers):
    """Annotate groups and reconcile timestamp-free completion for all stages."""
    if flow.cutoff is not None:
        return  # Historical rounds keep their own evidence, not today's status.
    status = flow.business_status
    terminal = status in TERMINAL

    def observe(key, stage, label, state, result=""):
        group = flow.groups.setdefault(key, {"stage": stage, "label": label, "requirements": []})
        if not group["requirements"]:
            group["requirements"].append({"label": label, "rule": None, "unknown": True, "informational": True,
                                          "business_completed": state == "completed"})
        group.update(business_status=state, business_result=result)
        return group

    def done_without_time(key, labels):
        for requirement in flow.groups.get(key, {}).get("requirements", []):
            if requirement["label"] in labels and requirement.get("done") is None:
                requirement.update(business_completed=True, unknown=True, late=False,
                                   eligible=False, failure_due=None, paused=False)

    screen_done = status not in EARLY | {"waitlist"} or (
        status == "waitlist" and bool(getattr(flow.resume, "manual_screening_decision", False) or reviews or interviews))
    if screen_done:
        result = "备选" if status == "waitlist" else "通过" if reviews or interviews or offers or not terminal else "已淘汰"
        observe("screening", "screening", "初筛", "completed", result)
        done_without_time("screening", {"及时提交初筛结果"})
    else:
        observe("screening", "screening", "初筛", "paused" if status == "waitlist" else "pending", "待提交初筛结论")

    if reviews:
        all_done = all(r.is_completed for r in reviews)
        results = list(dict.fromkeys(REVIEW_RESULTS.get(value(getattr(r, "recommendation", None)), "已提交")
                                     for r in reviews if r.is_completed))
        result = "、".join(results)
        if all_done:
            done_without_time("department", {"等待部门评审意见"})
            state = "completed"
            if status in {"pending_dept_review", "pending_hr_decision"}:
                result = f"{result}；待HR决策"
            else:
                done_without_time("department", {"评审交齐后及时提交HR决策"})
        else:
            state = "terminated" if terminal else "pending"
            result = f"已提交 {sum(bool(r.is_completed) for r in reviews)}/{len(reviews)} 份评审"
        observe("department", "department", "部门评审", state, result)

    for interview in interviews:
        key = f"interview:{interview.id}"
        label = f"第{interview.round or 1}轮面试"
        result = value(getattr(interview, "result", None))
        decision = result in INTERVIEW_RESULTS
        cancelled = bool(getattr(interview, "cancelled_at", None)) or value(getattr(interview, "status", None)) == "cancelled"
        ended = bool(getattr(interview, "ended_at", None)) or value(getattr(interview, "status", None)) == "completed"
        if cancelled:
            observe(key, "interview", label, "terminated", "已取消")
        elif decision:
            observe(key, "interview", label, "completed", INTERVIEW_RESULTS[result])
            done_without_time(key, {"等待面试反馈", "及时提交面试最终决策"})
        elif key in flow.groups or ended:
            observe(key, "interview", label, "terminated" if terminal else "pending",
                    "面试已结束，待提交最终决策" if ended else "等待面试反馈")
        if ended or decision or cancelled:
            done_without_time(f"attendance:{interview.id}", {"及时更新面试进展或改期"})

    for offer in offers:
        key = f"offer:{offer.id}"
        offer_status = value(offer.status)
        replied = offer_status in {"accepted", "rejected", "withdrawn", "expired", "departed"}
        result = OFFER_RESULTS.get(offer_status, "等待候选人答复")
        deadline = getattr(offer, "valid_until", None)
        if deadline is not None and offer_status == "sent":
            deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline
            if deadline < flow.now:
                result = "已到期，待处理"
        observe(key, "offer", "Offer", "completed" if replied else "terminated" if terminal else "pending", result)
        if replied:
            done_without_time(key, {"等待Offer答复", "历史撤回时间无法核实"})
        if offer_status in {"accepted", "rejected", "withdrawn", "departed"}:
            done_without_time(f"offer_expiry:{offer.id}", {"到期后及时登记后续处理"})
        if getattr(offer, "actual_onboarded_at", None) or getattr(offer, "departed_at", None) or offer_status == "departed":
            onboard_key = f"onboarding:{offer.id}"
            observe(onboard_key, "onboarding", "入职结果登记", "completed",
                    "已离职" if offer_status == "departed" or getattr(offer, "departed_at", None) else "已入职")
            done_without_time(onboard_key, {"及时确认入职、调整入职日期或变更Offer状态"})

    if not offers and status in {"offer_accepted", "onboarding", "completed", "departed"}:
        observe("offer", "offer", "Offer", "completed", "已接受")
    if status in {"completed", "departed"}:
        key = f"onboarding:{offers[-1].id}" if offers else "onboarding"
        observe(key, "onboarding", "入职结果登记", "completed", "已离职" if status == "departed" else "已入职")
        done_without_time(key, {"及时确认入职、调整入职日期或变更Offer状态"})

    withdrawn = offers[-1] if offers and value(offers[-1].status) == "withdrawn" else None
    withdrawal_times = [a.occurred_at.replace(tzinfo=timezone.utc) if a.occurred_at.tzinfo is None else a.occurred_at
                        for a in flow.actions if withdrawn and a.kind == "offer_transition"
                        and a.node_key == f"offer:{withdrawn.id}" and a.details.get("new_status") == "withdrawn"]
    for group in flow.groups.values():
        if not group.get("business_status"):
            reqs = group["requirements"]
            finished = all(r.get("done") or r.get("business_completed") for r in reqs)
            group["business_status"] = "completed" if finished else "terminated" if terminal else "pending"
        if terminal and group["business_status"] in {"pending", "paused"}:
            group["business_status"] = "terminated"
        elif status == "waitlist" and group["business_status"] == "pending":
            group["business_status"] = "paused"
        for requirement in group["requirements"]:
            withdrawn_progression = withdrawn and group["stage"] == "interview" and "发送Offer" in requirement["label"]
            if terminal or group["business_status"] == "terminated" or withdrawn_progression:
                if not requirement.get("done") and not requirement.get("business_completed"):
                    requirement["business_stopped"] = True
                    # A terminal status proves work stopped, not when it stopped.
                    # Preserve timed termination evidence; don't count days up to
                    # today as lateness for an undated historical termination.
                    stop_times = withdrawal_times if withdrawn_progression and not terminal else flow.ends
                    if not stop_times:
                        requirement.update(unknown=True, late=False, eligible=False, failure_due=None, paused=False)
                    else:
                        stops = [at for at in stop_times if requirement.get("start") and at >= requirement["start"]]
                        stop = min(stops, default=None)
                        due = requirement.get("due")
                        if stop and due:
                            missed = min((date for date in (due, requirement.get("failure_due")) if date and date < stop), default=None)
                            late = bool(missed) and not requirement["unknown"]
                            requirement.update(stopped=True, late=late, eligible=late,
                                               failure_due=missed if late else None, paused=False)
