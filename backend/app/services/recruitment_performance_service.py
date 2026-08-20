from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Interview,
    InterviewStatus,
    Offer,
    OfferStatus,
    Position,
    PositionCategory,
    PositionEvent,
    PositionEventType,
    RecruitmentHcSlot,
    RecruitmentPause,
    RecruitmentPerformanceConfig,
    RecruitmentSettlement,
    Resume,
    ResumeStatus,
    ResumeStatusEvent,
    User,
    UserRole,
)
from app.schemas.recruitment_performance import (
    DEFAULT_RESULT_COEFFICIENTS,
    DEFAULT_TARGET_DAYS,
    DEFAULT_TIME_COEFFICIENTS,
    HcScore,
    PerformanceConfigPayload,
    PerformanceConfigResponse,
    PerformanceOverview,
    PerformancePeriodOptions,
    PersonScore,
    PositionScore,
)


COMPANY_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
RESULT_LABELS = {
    "onboarded": "已入职",
    "offer_accepted": "已接受Offer",
    "offer_pending": "Offer待确认",
    "interview_passed": "面试通过，进入录用决策",
    "business_interview_completed": "业务面完成",
    "hr_interview_completed": "HR面完成",
    "open": "岗位Open",
}
EXCLUDED_RESUME_STATUSES = {
    ResumeStatus.REJECTED,
    ResumeStatus.INTERVIEW_FAILED,
    ResumeStatus.OFFER_REJECTED,
}


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def current_period(today: Optional[date] = None) -> str:
    today = today or datetime.now(COMPANY_TZ).date()
    return f"{today.year}-Q{((today.month - 1) // 3) + 1}"


def available_periods(db: Session, *, today: Optional[date] = None) -> PerformancePeriodOptions:
    """Return the tenant's contiguous performance history through the current quarter."""
    today = today or datetime.now(COMPANY_TZ).date()
    current = current_period(today)
    current_year, current_quarter, _, _ = parse_period(current)
    current_index = current_year * 4 + current_quarter - 1
    supported_categories = [PositionCategory(value) for value in DEFAULT_TARGET_DAYS]
    earliest_position = (
        db.query(func.min(Position.created_at))
        .filter(
            Position.deleted_at.is_(None),
            Position.category.in_(supported_categories),
        )
        .scalar()
    )
    start_indices = [current_index]
    if earliest_position is not None:
        start_indices.append(
            earliest_position.year * 4 + ((earliest_position.month - 1) // 3) + 1 - 1
        )
    stored_periods = [
        period
        for (period,) in db.query(RecruitmentSettlement.period).distinct().all()
    ]
    stored_periods.extend(
        f"{year}-Q{quarter}"
        for year, quarter in db.query(
            RecruitmentPerformanceConfig.effective_year,
            RecruitmentPerformanceConfig.effective_quarter,
        ).distinct().all()
    )
    for period in stored_periods:
        try:
            year, quarter, _, _ = parse_period(period)
        except HTTPException:
            continue
        index = year * 4 + quarter - 1
        if index <= current_index:
            start_indices.append(index)
    first_supported_index = 2026 * 4
    start_index = max(first_supported_index, min(start_indices))
    periods = [
        f"{index // 4}-Q{(index % 4) + 1}"
        for index in range(start_index, current_index + 1)
    ]
    return PerformancePeriodOptions(periods=periods, default_period=periods[-1])


def parse_period(period: str) -> tuple[int, int, datetime, datetime]:
    try:
        year_text, quarter_text = period.upper().split("-Q")
        year, quarter = int(year_text), int(quarter_text)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="季度格式必须为 YYYY-Q1 至 YYYY-Q4") from exc
    if year < 2026 or quarter not in {1, 2, 3, 4}:
        raise HTTPException(status_code=422, detail="季度格式必须为 YYYY-Q1 至 YYYY-Q4")
    start_month = 1 + (quarter - 1) * 3
    start_local = datetime.combine(date(year, start_month, 1), time.min, COMPANY_TZ)
    if quarter == 4:
        next_local = datetime.combine(date(year + 1, 1, 1), time.min, COMPANY_TZ)
    else:
        next_local = datetime.combine(date(year, start_month + 3, 1), time.min, COMPANY_TZ)
    return year, quarter, start_local.astimezone(timezone.utc), next_local.astimezone(timezone.utc)


def _default_config(year: int, quarter: int) -> PerformanceConfigResponse:
    return PerformanceConfigResponse(
        effective_year=year,
        effective_quarter=quarter,
        target_days=DEFAULT_TARGET_DAYS,
        time_coefficients=DEFAULT_TIME_COEFFICIENTS,
        result_coefficients=DEFAULT_RESULT_COEFFICIENTS,
    )


def get_config(db: Session, period: str) -> PerformanceConfigResponse:
    year, quarter, _, _ = parse_period(period)
    config = (
        db.query(RecruitmentPerformanceConfig)
        .filter(
            RecruitmentPerformanceConfig.effective_year == year,
            RecruitmentPerformanceConfig.effective_quarter == quarter,
        )
        .order_by(RecruitmentPerformanceConfig.version.desc())
        .first()
    )
    if config is None:
        return _default_config(year, quarter)
    return PerformanceConfigResponse(
        id=config.id,
        effective_year=year,
        effective_quarter=quarter,
        target_days=config.target_days,
        time_coefficients=config.time_coefficients,
        result_coefficients=config.result_coefficients,
        status=config.status,
        version=config.version,
        published_at=config.published_at,
    )


def publish_config(db: Session, actor: User, payload: PerformanceConfigPayload) -> PerformanceConfigResponse:
    period = f"{payload.effective_year}-Q{payload.effective_quarter}"
    _, _, period_start, _ = parse_period(period)
    if period_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="配置只能发布到尚未开始的季度")
    previous = (
        db.query(RecruitmentPerformanceConfig)
        .filter(
            RecruitmentPerformanceConfig.effective_year == payload.effective_year,
            RecruitmentPerformanceConfig.effective_quarter == payload.effective_quarter,
        )
        .order_by(RecruitmentPerformanceConfig.version.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    config = RecruitmentPerformanceConfig(
        tenant_id=actor.tenant_id,
        effective_year=payload.effective_year,
        effective_quarter=payload.effective_quarter,
        version=(previous.version + 1) if previous else 1,
        target_days=payload.target_days,
        time_coefficients=payload.time_coefficients,
        result_coefficients=payload.result_coefficients,
        status="published",
        created_by=actor.id,
        published_at=now,
        created_at=now,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return get_config(db, period)


def sync_position_slots(db: Session, position: Position, *, assigned_at: Optional[datetime] = None) -> list[RecruitmentHcSlot]:
    slots = (
        db.query(RecruitmentHcSlot)
        .filter(RecruitmentHcSlot.position_id == position.id)
        .order_by(RecruitmentHcSlot.slot_number)
        .all()
    )
    active = [slot for slot in slots if slot.status != "cancelled"]
    desired = max(position.headcount or 1, 1)
    now = _aware(assigned_at) or datetime.now(timezone.utc)
    if len(active) < desired:
        next_number = max((slot.slot_number for slot in slots), default=0) + 1
        for offset in range(desired - len(active)):
            slot = RecruitmentHcSlot(
                tenant_id=position.tenant_id,
                position_id=position.id,
                slot_number=next_number + offset,
                assigned_at=now,
                round_started_at=now,
            )
            db.add(slot)
            slots.append(slot)
        db.flush()
    elif len(active) > desired:
        cancellable = [slot for slot in reversed(active) if slot.completed_at is None]
        if len(cancellable) < len(active) - desired:
            raise HTTPException(status_code=409, detail="已入职HC不能通过减少Headcount删除")
        for slot in cancellable[: len(active) - desired]:
            slot.status = "cancelled"
            slot.status_reason = "岗位Headcount减少"
    return sorted(slots, key=lambda slot: slot.slot_number)


def record_resume_status_event(
    db: Session,
    resume: Resume,
    old_status,
    new_status,
    *,
    source: str,
    source_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
    reason: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> None:
    old_value = getattr(old_status, "value", old_status)
    new_value = getattr(new_status, "value", new_status)
    db.add(
        ResumeStatusEvent(
            tenant_id=resume.tenant_id,
            resume_id=resume.id,
            old_status=old_value,
            new_status=new_value,
            source=source,
            source_id=source_id,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
    )


def _result_stage(db: Session, resume: Resume) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    status = resume.status
    if status == ResumeStatus.COMPLETED:
        offer = db.query(Offer).filter(Offer.resume_id == resume.id).order_by(Offer.updated_at.desc()).first()
        return "onboarded", _aware(getattr(offer, "actual_onboarded_at", None)) or _aware(resume.created_at) or now
    if status == ResumeStatus.OFFER_ACCEPTED:
        offer = db.query(Offer).filter(Offer.resume_id == resume.id, Offer.status == OfferStatus.ACCEPTED).order_by(Offer.accepted_at.desc()).first()
        return "offer_accepted", _aware(offer.accepted_at if offer else None) or now
    if status == ResumeStatus.OFFER_PENDING:
        offer = db.query(Offer).filter(Offer.resume_id == resume.id, Offer.status == OfferStatus.SENT).order_by(Offer.sent_at.desc()).first()
        return "offer_pending", _aware(offer.sent_at if offer else None) or now
    if status == ResumeStatus.INTERVIEW_PASSED:
        return "interview_passed", now
    if status in {ResumeStatus.PENDING_INTERVIEW_RESULT, ResumeStatus.PENDING_NEXT_INTERVIEW}:
        interview = (
            db.query(Interview)
            .filter(Interview.resume_id == resume.id, Interview.status == InterviewStatus.COMPLETED)
            .order_by(Interview.ended_at.desc(), Interview.created_at.desc())
            .first()
        )
        stage = "hr_interview_completed" if interview and interview.interview_category == "hr" else "business_interview_completed"
        return stage, _aware(interview.ended_at if interview else None) or now
    return "open", _aware(resume.created_at) or now


def _candidate_allocations(db: Session, positions: Iterable[Position], result_coefficients: dict) -> dict[UUID, list[tuple[Resume, str, datetime]]]:
    position_ids = [position.id for position in positions]
    if not position_ids:
        return {}
    resumes = db.query(Resume).filter(Resume.position_id.in_(position_ids)).all()
    candidates = []
    for resume in resumes:
        if resume.status in EXCLUDED_RESUME_STATUSES:
            continue
        stage, achieved_at = _result_stage(db, resume)
        rank = float(result_coefficients.get(stage, 0))
        key = (resume.email or f"resume:{resume.id}").strip().lower()
        candidates.append((key, rank, achieved_at, resume, stage))
    chosen = {}
    for item in sorted(candidates, key=lambda row: (-row[1], row[2], str(row[3].id))):
        chosen.setdefault(item[0], item)
    grouped = defaultdict(list)
    for _, _, achieved_at, resume, stage in chosen.values():
        grouped[resume.position_id].append((resume, stage, achieved_at))
    for items in grouped.values():
        items.sort(key=lambda row: (-float(result_coefficients.get(row[1], 0)), row[2], str(row[0].id)))
    return grouped


def _day_count(start: datetime, end: datetime) -> int:
    if end < start:
        return 0
    start_date = start.astimezone(COMPANY_TZ).date()
    end_date = end.astimezone(COMPANY_TZ).date()
    return (end_date - start_date).days + 1


def _approved_pauses(db: Session, slot_id: UUID) -> list[RecruitmentPause]:
    return db.query(RecruitmentPause).filter(RecruitmentPause.slot_id == slot_id, RecruitmentPause.status == "approved").all()


def _deducted_days(pauses: list[RecruitmentPause], start: datetime, end: datetime) -> int:
    total = 0
    for pause in pauses:
        pause_start = max(_aware(pause.start_at), start)
        pause_end = min(_aware(pause.end_at) or end, end)
        total += _day_count(pause_start, pause_end)
    return total


def _time_coefficient(actual_days: int, target_days: int, coefficients: dict) -> float:
    ratio = actual_days / target_days if target_days else 0
    if ratio <= 0.8:
        key = "lte_80"
    elif ratio <= 0.9:
        key = "80_90"
    elif ratio <= 1:
        key = "90_100"
    elif ratio <= 1.1:
        key = "100_110"
    elif ratio <= 1.3:
        key = "110_130"
    elif ratio <= 1.5:
        key = "130_150"
    else:
        key = "gt_150"
    return float(coefficients[key])


def _owner_spans(db: Session, position: Position, start: datetime, end: datetime) -> list[tuple[UUID, datetime, datetime]]:
    events = (
        db.query(PositionEvent)
        .filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type.in_([PositionEventType.INITIAL_OWNER, PositionEventType.OWNER_CHANGED]),
            PositionEvent.occurred_at < end,
        )
        .order_by(PositionEvent.occurred_at, PositionEvent.id)
        .all()
    )
    owner = None
    cursor = start
    spans = []
    for event in events:
        event_at = _aware(event.occurred_at)
        if event_at <= start:
            owner = event.new_value
            continue
        if owner and event_at > cursor:
            spans.append((UUID(owner), cursor, min(event_at - timedelta(microseconds=1), end)))
        owner = event.new_value
        cursor = event_at
    owner = owner or (str(position.hiring_manager_id) if position.hiring_manager_id else None)
    if owner and cursor <= end:
        spans.append((UUID(owner), cursor, end))
    return spans


def calculate_overview(db: Session, period: str, *, user: Optional[User] = None, now: Optional[datetime] = None, use_settlement: bool = True) -> PerformanceOverview:
    year, quarter, period_start, period_next = parse_period(period)
    now = _aware(now) or datetime.now(timezone.utc)
    cutoff = min(now, period_next - timedelta(microseconds=1))
    config = get_config(db, period)
    latest_settlement = (
        db.query(RecruitmentSettlement)
        .filter(RecruitmentSettlement.period == period)
        .order_by(RecruitmentSettlement.version.desc())
        .first()
    )
    if use_settlement and latest_settlement is not None:
        settled = PerformanceOverview.model_validate(latest_settlement.snapshot)
        visible_user_ids = {
            user_id for (user_id,) in db.query(User.id).filter(User.id.in_([person.user_id for person in settled.people])).all()
        }
        settled.people = [person for person in settled.people if person.user_id in visible_user_ids]
        if user is not None:
            settled.people = [person for person in settled.people if person.user_id == user.id]
        return settled

    positions = db.query(Position).filter(Position.deleted_at.is_(None)).all()
    for position in positions:
        sync_position_slots(db, position, assigned_at=now)
    db.flush()
    allocations = _candidate_allocations(db, positions, config.result_coefficients)
    people = {person.id: person for person in db.query(User).filter(User.role.in_([UserRole.HR, UserRole.ADMIN])).all()}
    person_positions = defaultdict(list)

    for position in positions:
        category = getattr(position.category, "value", position.category)
        if category not in config.target_days:
            continue
        target_days = int(config.target_days[category])
        slots = db.query(RecruitmentHcSlot).filter(RecruitmentHcSlot.position_id == position.id).order_by(RecruitmentHcSlot.slot_number).all()
        candidates = allocations.get(position.id, [])
        spans = _owner_spans(db, position, period_start, cutoff)
        for owner_id, span_start, span_end in spans:
            if user is not None and owner_id != user.id:
                continue
            hc_scores = []
            for index, slot in enumerate(slots):
                candidate = candidates[index] if index < len(candidates) else None
                resume, stage, _ = candidate if candidate else (None, "open", cutoff)
                result_coefficient = float(config.result_coefficients[stage])
                status = slot.status
                if status in {"cancelled", "frozen"}:
                    hc_scores.append(HcScore(
                        slot_id=slot.id, slot_number=slot.slot_number, candidate_name=None,
                        result_stage="已剔除", result_coefficient=0, target_days=target_days,
                        actual_days=0, deducted_days=0, effective_held_days=0,
                        time_coefficient=0, task_points=0, score=0, status=status,
                    ))
                    continue
                slot_start = max(_aware(slot.assigned_at), span_start, period_start)
                slot_end = min(span_end, cutoff)
                offer = None
                if resume is not None:
                    offer = db.query(Offer).filter(Offer.resume_id == resume.id).order_by(Offer.updated_at.desc()).first()
                accepted_at = _aware(offer.accepted_at if offer and offer.status == OfferStatus.ACCEPTED else slot.accepted_at)
                onboarded_at = _aware(offer.actual_onboarded_at if offer else slot.completed_at)
                weight_end = min([value for value in [slot_end, accepted_at, onboarded_at] if value is not None])
                pauses = _approved_pauses(db, slot.id)
                deducted = _deducted_days(pauses, slot_start, weight_end) if slot_start <= weight_end else 0
                effective_days = max(0, _day_count(slot_start, weight_end) - deducted)
                cycle_start = max(_aware(slot.round_started_at), span_start)
                cycle_end = min(accepted_at or span_end, span_end, cutoff)
                cycle_deducted = _deducted_days(pauses, cycle_start, cycle_end)
                actual_days = max(1, _day_count(cycle_start, cycle_end) - cycle_deducted)
                time_coefficient = _time_coefficient(actual_days, target_days, config.time_coefficients)
                task_points = float(position.priority * effective_days)
                score = task_points * time_coefficient * result_coefficient
                hc_scores.append(HcScore(
                    slot_id=slot.id,
                    slot_number=slot.slot_number,
                    candidate_name=resume.candidate_name if resume else None,
                    result_stage=RESULT_LABELS[stage],
                    result_coefficient=result_coefficient,
                    target_days=target_days,
                    actual_days=actual_days,
                    deducted_days=deducted,
                    effective_held_days=effective_days,
                    time_coefficient=time_coefficient,
                    task_points=task_points,
                    score=score,
                    status="completed" if stage == "onboarded" else status,
                ))
            task_points = sum(item.task_points for item in hc_scores)
            score = sum(item.score for item in hc_scores)
            valid = [item for item in hc_scores if item.status not in {"cancelled", "frozen"}]
            person_positions[owner_id].append(PositionScore(
                position_id=position.id,
                title=position.title,
                category=category,
                priority=position.priority,
                hc_count=len(valid),
                onboarded_count=sum(item.status == "completed" for item in valid),
                excluded_count=len(hc_scores) - len(valid),
                task_points=task_points,
                score=score,
                achievement_rate=(score / task_points if task_points else None),
                highest_result_stage=max(valid, key=lambda item: item.result_coefficient).result_stage if valid else "无有效任务",
                slots=hc_scores,
            ))

    result_people = []
    for owner_id, scores in person_positions.items():
        person = people.get(owner_id)
        if person is None:
            continue
        task_points = sum(item.task_points for item in scores)
        score = sum(item.score for item in scores)
        result_people.append(PersonScore(
            user_id=owner_id,
            name=person.full_name or person.email,
            email=person.email,
            hc_count=sum(item.hc_count for item in scores),
            excluded_count=sum(item.excluded_count for item in scores),
            onboarded_count=sum(item.onboarded_count for item in scores),
            task_points=task_points,
            score=score,
            achievement_rate=(score / task_points if task_points else None),
            positions=scores,
        ))
    result_people.sort(key=lambda person: person.name)
    return PerformanceOverview(
        period=period,
        as_of=cutoff.astimezone(COMPANY_TZ).date(),
        status="trial" if period == "2026-Q3" else "live",
        people=result_people,
    )


def settle_period(db: Session, actor: User, period: str, reason: Optional[str] = None) -> PerformanceOverview:
    _, _, _, period_next = parse_period(period)
    now = datetime.now(timezone.utc)
    if period_next > now:
        raise HTTPException(status_code=409, detail="当前季度尚未结束，不能结算")
    previous = db.query(RecruitmentSettlement).filter(RecruitmentSettlement.period == period).order_by(RecruitmentSettlement.version.desc()).first()
    overview = calculate_overview(db, period, now=period_next - timedelta(microseconds=1), use_settlement=False)
    version = (previous.version + 1) if previous else 1
    overview.status = "settled"
    overview.settlement_version = version
    db.add(RecruitmentSettlement(
        tenant_id=actor.tenant_id,
        period=period,
        version=version,
        status="settled",
        snapshot=overview.model_dump(mode="json"),
        reason=reason,
        settled_by=actor.id,
    ))
    db.commit()
    return overview
