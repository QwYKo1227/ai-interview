"""Resolve quality obligations to the existing business forms and records."""
from urllib.parse import urlencode


def business_href(key, stage, pending_rules, *, resume_id, position_id, interviews, offers, actionable):
    def link(path, **params):
        return f"{path}?{urlencode({k: str(v) for k, v in params.items() if v is not None})}"

    def schedule():
        return link("/interviews", candidate=resume_id, position=position_id, action="schedule" if actionable else None)

    def offer_link(offer_id=None, action=None):
        if offer_id is None:
            offer_id = offers[-1].id if offers else None
        return link("/offers", resume_id=resume_id, position_id=position_id,
                    offer_id=offer_id,
                    action=action if offer_id else "create" if actionable else None)

    if actionable:
        if "offer_send_days" in pending_rules:
            return offer_link(action="send")
        if pending_rules & {"interview_arrangement_days", "next_interview_days"}:
            return schedule()

    kind, _, resource_id = key.partition(":")
    if kind in {"interview", "attendance", "cancel"}:
        if kind == "cancel" and actionable:
            return schedule()
        interview = next((i for i in interviews if str(i.id) == resource_id), None)
        if kind == "attendance" or kind == "cancel":
            return link("/interviews", candidate=resume_id, position=position_id, interview_id=resource_id,
                        action="edit" if kind == "attendance" and actionable else None)
        status = getattr(interview, "status", None)
        ended = interview and (interview.ended_at or interview.final_decision_at
                               or getattr(status, "value", status) == "completed")
        return f"/interviews/{resource_id}/{'result' if ended else 'score'}"

    if stage in {"offer", "onboarding"} or kind.startswith("offer_"):
        offer_id = resource_id.split(":", 1)[0]
        action = "onboarding" if stage == "onboarding" and actionable else None
        return offer_link(offer_id, action)

    action = None
    if actionable:
        if "department_assignment_days" in pending_rules:
            action = "assign-reviewers"
        elif pending_rules & {"screening_days", "department_decision_days"}:
            action = "hr-decision"
    return link(f"/resumes/{resume_id}", section=stage, position_id=position_id, action=action)
