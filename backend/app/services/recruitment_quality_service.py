"""Process completeness: append-only evidence, versioned rules and HR reporting."""
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import selectinload

from app.models.models import DepartmentReview, Interview, Offer, OfferDecisionAudit, Position, Resume, ResumeStatusEvent, User
from app.models.recruitment_quality import QualityAction, QualityBinding, QualityPolicy
from app.models.tenant_models import Tenant
from app.schemas.recruitment_quality import QualityRules
from app.services.recruitment_access import is_admin, is_recruiter
from app.services.recruitment_quality_engine import build_candidate_nodes, utc, val, valid_schedule
from app.services.recruitment_workdays import COMPANY_TZ


def now_utc():
    return datetime.now(timezone.utc)


def subject(position_id, resume_id=None):
    return f"resume:{resume_id}:{position_id}" if resume_id else f"position:{position_id}"


def policies(db, tenant_id):
    return db.query(QualityPolicy).filter(QualityPolicy.tenant_id == tenant_id).order_by(QualityPolicy.version).all()


def config_response(db, user):
    rows = policies(db, user.tenant_id)
    owned = {p.id for p in db.query(Position).filter(Position.hiring_manager_id == user.id).all()} if not is_admin(user) else None
    return {"enabled": bool(rows), "rollout_at": rows[0].created_at if rows else None,
            "defaults": QualityRules().model_dump(),
            "policies": [{"id": p.id, "name": p.name, "version": p.version, "position_id": p.position_id,
                          "rules": QualityRules.model_validate(p.rules).model_dump(), "created_at": p.created_at}
                         for p in rows if p.position_id is None or owned is None or p.position_id in owned]}


def bind(db, position, resume, policy, *, started_at=None):
    key = subject(position.id, resume.id if resume else None)
    row = next((x for x in db.new if isinstance(x, QualityBinding) and x.tenant_id == position.tenant_id and x.subject_key == key), None)
    row = row or db.query(QualityBinding).filter(QualityBinding.tenant_id == position.tenant_id, QualityBinding.subject_key == key).first()
    if row:
        return row
    row = QualityBinding(id=uuid4(), tenant_id=position.tenant_id, subject_key=key, position_id=position.id, resume=resume,
                         resume_id=resume.id if resume else None, policy_id=policy.id,
                         started_at=utc(started_at or (resume.created_at if resume else position.created_at)) or now_utc())
    db.add(row)
    return row


def publish_policy(db, user, payload):
    db.query(Tenant).filter(Tenant.id == user.tenant_id).with_for_update().one()
    rows = policies(db, user.tenant_id)
    if payload.position_id:
        if not rows:
            raise HTTPException(409, "请先启用全局流程规则")
        if not db.query(Position).filter(Position.tenant_id == user.tenant_id, Position.id == payload.position_id, Position.deleted_at.is_(None)).first():
            raise HTTPException(404, "岗位不存在")
    row = QualityPolicy(id=uuid4(), tenant_id=user.tenant_id, position_id=payload.position_id,
                        version=rows[-1].version + 1 if rows else 1, name=payload.name,
                        rules=payload.rules.model_dump(), created_by=user.id, created_at=now_utc())
    db.add(row)
    db.flush()
    if not rows:
        for resume in db.query(Resume).join(Position, Resume.position_id == Position.id).filter(Position.deleted_at.is_(None)).all():
            bind(db, resume.position, resume, row)
    db.commit()
    return config_response(db, user)


def metrics(nodes):
    eligible = [n for n in nodes if n["eligible"]]
    completed = sum(n["complete"] for n in eligible)
    return {"completed_nodes": completed, "required_nodes": len(eligible),
            "process_rate": round(100 * completed / len(eligible), 1) if eligible else None,
            "overdue_count": sum(n["overdue"] for n in nodes),
            "missing_count": sum(n["status"] in {"missing", "late"} for n in nodes),
            "unknown_count": sum(n["status"] == "unknown" for n in nodes),
            "historical_count": len({n["binding_id"] for n in nodes if n["historical"]}),
            "business_completed_nodes": sum(n.get("business_status") == "completed" for n in nodes),
            "business_pending_nodes": sum(n.get("business_status") in {"pending", "paused"} for n in nodes),
            "business_terminated_nodes": sum(n.get("business_status") == "terminated" for n in nodes),
            "longest_overdue_hours": max((n["overdue_hours"] for n in nodes), default=0)}


def overview(db, user, *, cohort="all", scope_owner=True, start_date=None, end_date=None):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    ps = policies(db, user.tenant_id)
    if not ps:
        return {"enabled": False, "as_of": now_utc(), "rollout_at": None, "summary": metrics([]), "people": [], "nodes": [], "positions": [], "flows": []}
    position_query = db.query(Position).filter(Position.tenant_id == user.tenant_id, Position.deleted_at.is_(None))
    if scope_owner and is_recruiter(user):
        position_query = position_query.filter(Position.hiring_manager_id == user.id)
    positions = {p.id: p for p in position_query.all()}
    bindings = db.query(QualityBinding).filter(QualityBinding.position_id.in_(list(positions)), QualityBinding.resume_id.isnot(None)).all() if positions else []
    ids = {b.resume_id for b in bindings}
    resumes = {r.id: r for r in db.query(Resume).filter(Resume.id.in_(ids)).all()} if ids else {}
    actions, interviews, reviews, offers, events = (defaultdict(list) for _ in range(5))
    if bindings:
        for a in db.query(QualityAction).filter(QualityAction.binding_id.in_([b.id for b in bindings])).all():
            actions[a.binding_id].append(a)
    if ids:
        for row in db.query(Interview).options(selectinload(Interview.panels)).filter(Interview.resume_id.in_(ids)).all():
            interviews[(row.resume_id, row.position_id)].append(row)
        for row in db.query(DepartmentReview).filter(DepartmentReview.resume_id.in_(ids)).all():
            reviews[row.resume_id].append(row)
        for row in db.query(Offer).filter(Offer.resume_id.in_(ids)).all():
            offers[(row.resume_id, row.position_id)].append(row)
        for row in db.query(ResumeStatusEvent).filter(ResumeStatusEvent.resume_id.in_(ids)).all():
            events[row.resume_id].append(row)
        offer_map = {o.id: o for group in offers.values() for o in group}
        binding_map = {(b.resume_id, b.position_id): b for b in bindings}
        if offer_map:
            from types import SimpleNamespace
            for audit in db.query(OfferDecisionAudit).filter(OfferDecisionAudit.offer_id.in_(list(offer_map))).all():
                offer = offer_map[audit.offer_id]
                binding = binding_map.get((offer.resume_id, offer.position_id))
                if binding:
                    actions[binding.id].append(SimpleNamespace(
                        id=audit.id, kind="offer_transition", node_key=f"offer:{offer.id}", actor_id=audit.actor_id,
                        reason=audit.correction_reason or "Offer答复记录", occurred_at=audit.created_at,
                        details={"offer_id": str(offer.id), "new_status": audit.new_status, "old_status": audit.previous_status}))
    now, nodes, flow_contexts = now_utc(), [], {}
    for b in bindings:
        r = resumes.get(b.resume_id)
        if r:
            nodes.extend(build_candidate_nodes(b, positions[b.position_id], r, ps, actions[b.id],
                                              interviews[(r.id, b.position_id)], reviews[r.id],
                                              offers[(r.id, b.position_id)], events[r.id], now, flow_contexts=flow_contexts))
    # Keep audit history in storage/the engine, but expose only the current
    # application round at its current position in this operational report.
    flow_contexts = {fid: context for fid, context in flow_contexts.items() if context["is_current"]}
    nodes = [n for n in nodes if n["flow_id"] in flow_contexts]
    if start_date or end_date:
        # Select entire application rounds so their stage evidence stays intact.
        flow_contexts = {fid: context for fid, context in flow_contexts.items()
                         if (not start_date or utc(context["started_at"]).astimezone(COMPANY_TZ).date() >= start_date)
                         and (not end_date or utc(context["started_at"]).astimezone(COMPANY_TZ).date() <= end_date)}
        nodes = [n for n in nodes if n["flow_id"] in flow_contexts]
    if scope_owner and is_recruiter(user):
        nodes = [n for n in nodes if positions[n["position_id"]].hiring_manager_id == user.id]
    elif scope_owner and not is_admin(user):
        nodes = [n for n in nodes if n["executor_id"] == user.id]
    if cohort != "all":
        nodes = [n for n in nodes if n["historical"] == (cohort == "historical")]
    users = {u.id: u.full_name or u.email for u in db.query(User).filter(User.tenant_id == user.tenant_id).all()}
    visible_ids = {n["flow_id"] for n in nodes}
    flows = {fid: {**context, "owner_name": users.get(context["owner_id"], "")}
             for fid, context in flow_contexts.items()
             if (fid in visible_ids or is_admin(user) or positions[context["position_id"]].hiring_manager_id == user.id)
             and (cohort == "all" or (utc(context["started_at"]) < utc(ps[0].created_at)) == (cohort == "historical"))}
    for n in nodes:
        n.pop("_flow")
    grouped = defaultdict(list)
    current_positions, current_candidates = defaultdict(set), defaultdict(set)
    for n in nodes:
        n["owner_name"] = users.get(n["owner_id"], "未分配负责人")
        n["executor_name"] = users.get(n["executor_id"], "待指派")
        for action in n["actions"]:
            action["actor_name"] = users.get(action["actor_id"], "系统处理")
        position = positions[n["position_id"]]
        current_owner = position.hiring_manager_id
        n["current_owner_id"] = current_owner
        n["current_owner_name"] = users.get(current_owner, "未分配负责人")
        # This report describes the candidates currently assigned to the HR.
        # Historical operation ownership remains in the underlying audit data.
        if not is_recruiter(user) or current_owner == user.id:
            grouped[current_owner].append(n)
        if not is_recruiter(user) or current_owner == user.id:
            current_positions[current_owner].add(position.id)
            resume = resumes[n["resume_id"]]
            if resume.position_id == position.id:
                current_candidates[current_owner].add(resume.id)
    people = []
    current_statuses = {flow["resume_id"]: flow["status"] for flow in flows.values()}
    for owner in set(grouped) | set(current_positions):
        if owner not in users:
            continue
        items = grouped[owner]
        people.append({
            "user_id": owner, "name": users[owner],
            "position_count": len({n["position_id"] for n in items} | current_positions[owner]),
            "candidate_count": len({n["resume_id"] for n in items} | current_candidates[owner]),
            "open_position_count": sum(val(positions[pid].status) not in {"closed", "cancelled"} for pid in current_positions[owner]),
            "active_candidate_count": sum(current_statuses.get(rid, val(resumes[rid].status)) not in {"rejected", "interview_failed", "offer_rejected", "completed", "departed", "waitlist"} for rid in current_candidates[owner]),
            **metrics(items),
        })
    people.sort(key=lambda p: (p["process_rate"] is None, p["process_rate"] or 0, p["name"]))
    visible = {flow["position_id"] for flow in flows.values()}
    scored_nodes = [n for items in grouped.values() for n in items]
    return {"enabled": True, "as_of": now, "rollout_at": ps[0].created_at, "summary": metrics(scored_nodes),
            "people": people, "nodes": nodes, "flows": list(flows.values()),
            "positions": [{"id": p.id, "title": p.title} for p in positions.values() if p.id in visible] if is_admin(user) or is_recruiter(user) else []}


def record_action(db, user, binding_id, node_key, payload):
    binding = db.query(QualityBinding).filter(QualityBinding.id == binding_id).first()
    if not binding:
        raise HTTPException(404, "流程节点不存在")
    position = db.query(Position).filter(Position.id == binding.position_id).with_for_update().one()
    if not is_admin(user) and (not is_recruiter(user) or position.hiring_manager_id != user.id):
        raise HTTPException(403, "仅当前招聘负责人或管理员可补充处理记录")
    node = next((n for n in overview(db, user, scope_owner=False)["nodes"] if n["binding_id"] == binding_id and n["key"] == node_key), None)
    if node is None:
        raise HTTPException(404, "流程节点不存在")
    action = QualityAction(id=uuid4(), tenant_id=user.tenant_id, binding=binding, node_key=node_key,
                           kind=payload.kind, actor_id=user.id, reason=payload.reason, details={}, occurred_at=now_utc())
    db.add(action)
    db.commit()
    return {"id": action.id}


def validate_public_review(db, resume, review, **values):
    # Business APIs validate inputs; this module measures stage outcomes only.
    return None


def guard_changes(db):
    """Capture actual operation times in the same transaction as legacy APIs."""
    business = [o for o in list(db.new) + list(db.dirty) if isinstance(o, (Position, Resume, Interview, Offer))]
    for tenant_id in {o.tenant_id for o in business if o.tenant_id is not None}:
        ps = policies(db, tenant_id)
        if not ps:
            continue
        for obj in business:
            if obj.tenant_id != tenant_id:
                continue
            state = inspect(obj)
            if isinstance(obj, Position):
                if not state.pending and state.attrs.hiring_manager_id.history.has_changes():
                    history = list(obj.hiring_manager_history or [])
                    old = state.attrs.hiring_manager_id.history.deleted
                    previous = str(old[0]) if old and old[0] else None
                    new = str(obj.hiring_manager_id) if obj.hiring_manager_id else None
                    if not history or history[-1].get("new_owner_id") != new:
                        history.append({"old_owner_id": previous, "new_owner_id": new, "changed_at": now_utc().isoformat()})
                        obj.hiring_manager_history = history
                continue
            resume = obj if isinstance(obj, Resume) else db.query(Resume).filter(Resume.id == obj.resume_id).first()
            if resume is None or resume.position_id is None:
                continue
            if resume.id is None:
                resume.id = uuid4()
            position_id = obj.position_id if isinstance(obj, (Offer, Interview)) else resume.position_id
            position = db.query(Position).filter(Position.id == position_id).first()
            if position is None:
                continue
            policy = next((p for p in reversed(ps) if p.position_id == position.id), next(p for p in reversed(ps) if p.position_id is None))
            transferred = isinstance(obj, Resume) and not state.pending and state.attrs.position_id.history.has_changes()
            if transferred:
                old_id = state.attrs.position_id.history.deleted
                old_binding = db.query(QualityBinding).filter(QualityBinding.subject_key == subject(old_id[0], resume.id)).first() if old_id else None
                if old_binding:
                    db.add(QualityAction(tenant_id=tenant_id, binding=old_binding, node_key="process", kind="transferred",
                                         actor_id=db.info.get("quality_actor_id"), reason="简历转岗", details={}, occurred_at=now_utc()))
            binding = bind(db, position, resume, policy, started_at=now_utc() if transferred else None)
            def audit(key, kind, details):
                db.add(QualityAction(tenant_id=tenant_id, binding=binding, node_key=key, kind=kind,
                                     actor_id=db.info.get("quality_actor_id"), reason="业务操作", details=details, occurred_at=now_utc()))
            if isinstance(obj, Resume) and (state.attrs.status.history.has_changes() or transferred):
                old = state.attrs.status.history.deleted
                audit("screening", "transition", {"old_status": val(old[0]) if old else None,
                                                  "new_status": val(obj.status), "manual_decision": bool(obj.manual_screening_decision),
                                                  "process_restart": transferred})
            if isinstance(obj, Offer) and (state.pending or state.attrs.status.history.has_changes()):
                if obj.id is None:
                    obj.id = uuid4()
                old = state.attrs.status.history.deleted
                audit(f"offer:{obj.id}", "offer_transition", {"old_status": val(old[0]) if old else None,
                      "new_status": val(obj.status), "offer_id": str(obj.id),
                      "valid_until": obj.valid_until.isoformat() if obj.valid_until else None,
                      "onboard_date": obj.onboard_date.isoformat() if obj.onboard_date else None})
            if isinstance(obj, Offer) and not state.pending:
                changes = {}
                for field in ("valid_until", "onboard_date"):
                    history = state.attrs[field].history
                    if history.has_changes():
                        old = history.deleted[0] if history.deleted else None
                        new = getattr(obj, field)
                        changes[f"old_{field}"] = old.isoformat() if old else None
                        changes[f"new_{field}"] = new.isoformat() if new else None
                if changes:
                    audit(f"offer:{obj.id}", "offer_dates", changes)
            if isinstance(obj, Interview) and not state.pending and any(
                state.attrs[field].history.has_changes() for field in ("interview_time", "interview_end_time")
            ):
                history = state.attrs.interview_end_time.history
                previous_end = history.deleted[0] if history.deleted else obj.interview_end_time
                audit(f"interview:{obj.id}", "rescheduled", {
                    "scheduled_at": obj.interview_time.isoformat() if obj.interview_time else None,
                    "old_interview_end_time": previous_end.isoformat() if previous_end else None,
                    "interview_end_time": obj.interview_end_time.isoformat() if obj.interview_end_time else None,
                    "valid_schedule": valid_schedule(obj),
                })
            if isinstance(obj, Interview) and valid_schedule(obj) and (
                state.pending or any(state.attrs[key].history.has_changes() for key in
                                     ("panel_members", "interview_time", "interview_end_time", "interview_location", "meeting_link"))
            ):
                if obj.id is None:
                    obj.id = uuid4()
                existing = db.query(QualityAction).filter(QualityAction.binding_id == binding.id,
                    QualityAction.node_key == f"interview:{obj.id}", QualityAction.kind == "schedule_saved").first()
                if existing is None:
                    audit(f"interview:{obj.id}", "schedule_saved", {"interview_id": str(obj.id)})
