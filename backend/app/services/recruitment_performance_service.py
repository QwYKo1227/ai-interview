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
    PositionStatus,
    RecruitmentHcSlot,
    RecruitmentPause,
    RecruitmentPerformanceConfig,
    RecruitmentSettlement,
    Resume,
    ResumeStatus,
    ResumeStatusEvent,
    User,
)
from app.schemas.recruitment_performance import (
    DEFAULT_RESULT_COEFFICIENTS,
    DEFAULT_TARGET_DAYS,
    DEFAULT_TIME_COEFFICIENTS,
    HandoffCredit,
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
    ResumeStatus.DEPARTED,
}
HANDOFF_CREDIT_STATUSES = {
    ResumeStatus.INTERVIEW_PASSED.value,
    ResumeStatus.OFFER_PENDING.value,
    ResumeStatus.OFFER_ACCEPTED.value,
    ResumeStatus.ONBOARDING.value,
    ResumeStatus.COMPLETED.value,
}
HANDOFF_CREDIT_STAGES = {
    "interview_passed",
    "offer_pending",
    "offer_accepted",
    "onboarded",
}
PLACEHOLDER_CANDIDATE_EMAILS = {
    "-",
    "n/a",
    "na",
    "unknown",
    "暂无",
    "无",
    "未知",
}
HISTORICAL_HC_STATUSES = {"released"}
DEPARTED_HC_STATUSES = {"released", "departed_retained"}


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


def _starts_new_recruitment_cycle(event: PositionEvent) -> bool:
    metadata = event.event_metadata or {}
    # Only explicit new-demand events written under the rollout policy create
    # cycles. Every pre-rollout reopen, including earlier feature variants,
    # continues the original cycle without backfilling historical markers.
    return (
        metadata.get("reopen_mode") == "new_cycle"
        and metadata.get("recruitment_cycle_policy_version") == 1
    )


def _is_reopen_event(event: PositionEvent) -> bool:
    return (event.old_value or "").lower() in {"closed", "cancelled", "deleted"} and (
        event.new_value or "").lower() in {"open", "published"}


def position_reopen_events(db: Session, position: Position) -> list[PositionEvent]:
    return [event for event in db.query(PositionEvent).filter(
        PositionEvent.position_id == position.id,
        PositionEvent.event_type.in_([PositionEventType.STATUS_CHANGED, PositionEventType.RESTORED]),
    ).order_by(PositionEvent.occurred_at, PositionEvent.id).all()
        if _is_reopen_event(event) and _starts_new_recruitment_cycle(event)]


def sync_position_slots(db: Session, position: Position, *, assigned_at: Optional[datetime] = None) -> list[RecruitmentHcSlot]:
    slots = (
        db.query(RecruitmentHcSlot)
        .filter(RecruitmentHcSlot.position_id == position.id)
        .order_by(RecruitmentHcSlot.slot_number)
        .all()
    )
    next_slot_number = max((slot.slot_number for slot in slots), default=0) + 1
    reopen_events = position_reopen_events(db, position)
    cycle_start = _aware(reopen_events[-1].occurred_at) if reopen_events else None
    slots = [slot for slot in slots if cycle_start is None or _aware(slot.assigned_at) >= cycle_start]
    active = [
        slot for slot in slots
        if slot.status not in {"cancelled", *HISTORICAL_HC_STATUSES}
    ]
    desired = max(position.headcount or 1, 1)
    now = _aware(assigned_at) or datetime.now(timezone.utc)
    if cycle_start is not None:
        now = cycle_start if not slots else max(now, cycle_start)
    if len(active) < desired:
        for offset in range(desired - len(active)):
            slot = RecruitmentHcSlot(
                tenant_id=position.tenant_id,
                position_id=position.id,
                slot_number=next_slot_number + offset,
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


def start_position_recruitment_cycle(db: Session, position: Position, *, started_at: datetime) -> None:
    """Create fresh HC without changing previous cycles' candidate/score records."""
    # Flush the reopen event first: slot synchronization uses it as the boundary.
    db.flush()
    # Slot numbers remain unique across cycles, including replacement rounds.
    next_number = (db.query(func.max(RecruitmentHcSlot.slot_number)).filter(
        RecruitmentHcSlot.position_id == position.id,
    ).scalar() or 0) + 1
    for offset in range(max(position.headcount or 1, 1)):
        db.add(RecruitmentHcSlot(
            tenant_id=position.tenant_id, position_id=position.id,
            slot_number=next_number + offset, assigned_at=started_at,
            round_started_at=started_at,
        ))
    db.flush()


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


def _departed_result_stage(offer: Offer) -> tuple[str, datetime]:
    departed_at = _aware(offer.departed_at)
    onboarded_at = _aware(offer.actual_onboarded_at)
    onboarded_days = (
        departed_at.astimezone(COMPANY_TZ).date()
        - onboarded_at.astimezone(COMPANY_TZ).date()
    ).days
    if onboarded_days < 30:
        return "offer_accepted", _aware(offer.accepted_at) or onboarded_at
    return "onboarded", onboarded_at


def _result_stage(db: Session, resume: Resume) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    status = resume.status
    if status == ResumeStatus.OFFER_REJECTED:
        return "offer_pending", _offer_issued_at(db, resume, now)
    if status == ResumeStatus.DEPARTED:
        offer = (
            db.query(Offer)
            .filter(Offer.resume_id == resume.id, Offer.departed_at.isnot(None))
            .order_by(Offer.departed_at.desc())
            .first()
        )
        if offer is not None and offer.actual_onboarded_at is not None:
            return _departed_result_stage(offer)
        return "open", _aware(resume.created_at) or now
    if status == ResumeStatus.COMPLETED:
        offer = db.query(Offer).filter(Offer.resume_id == resume.id).order_by(Offer.updated_at.desc()).first()
        return "onboarded", _aware(getattr(offer, "actual_onboarded_at", None)) or _aware(resume.created_at) or now
    if status == ResumeStatus.OFFER_ACCEPTED:
        offer = db.query(Offer).filter(
            Offer.resume_id == resume.id,
            Offer.status.in_([OfferStatus.ACCEPTED, OfferStatus.DEPARTED]),
        ).order_by(Offer.accepted_at.desc()).first()
        return "offer_accepted", _aware(offer.accepted_at if offer else None) or now
    if status == ResumeStatus.OFFER_PENDING:
        offer = db.query(Offer).filter(Offer.resume_id == resume.id, Offer.status == OfferStatus.SENT).order_by(Offer.sent_at.desc()).first()
        return "offer_pending", _aware(offer.sent_at if offer else None) or now
    if status == ResumeStatus.INTERVIEW_PASSED:
        passed_at = (
            db.query(ResumeStatusEvent.occurred_at)
            .filter(
                ResumeStatusEvent.resume_id == resume.id,
                ResumeStatusEvent.new_status == ResumeStatus.INTERVIEW_PASSED.value,
            )
            .order_by(ResumeStatusEvent.occurred_at.desc())
            .limit(1)
            .scalar()
        )
        return "interview_passed", _aware(passed_at) or _aware(resume.created_at) or now
    active_interview_statuses = {
        ResumeStatus.PENDING_INTERVIEW,
        ResumeStatus.INTERVIEW_SCHEDULED,
        ResumeStatus.INTERVIEW_IN_PROGRESS,
        ResumeStatus.PENDING_INTERVIEW_RESULT,
        ResumeStatus.PENDING_NEXT_INTERVIEW,
    }
    interview = (
        db.query(Interview)
        .filter(Interview.resume_id == resume.id, Interview.status == InterviewStatus.COMPLETED)
        .order_by(Interview.ended_at.desc(), Interview.created_at.desc())
        .first()
    )
    # A completed interview is an achieved milestone. Legacy records can have
    # their current resume status reset to review after the interview, so use
    # the persisted interview lifecycle as the authoritative floor.
    if interview is not None:
        stage = "hr_interview_completed" if interview and interview.interview_category == "hr" else "business_interview_completed"
        return stage, _aware(interview.ended_at) or _aware(interview.created_at) or now
    if status in active_interview_statuses:
        return "open", _aware(resume.created_at) or now
    return "open", _aware(resume.created_at) or now


def _candidate_identity_key(resume: Resume) -> str:
    normalized_email = (resume.email or "").strip().lower()
    if not normalized_email or normalized_email in PLACEHOLDER_CANDIDATE_EMAILS:
        return f"resume:{resume.id}"
    return normalized_email


def _candidate_allocations(db: Session, positions: Iterable[Position], result_coefficients: dict) -> dict[UUID, list[tuple[Resume, str, datetime]]]:
    position_ids = [position.id for position in positions]
    if not position_ids:
        return {}
    resumes = db.query(Resume).filter(Resume.position_id.in_(position_ids)).all()
    departed_resume_ids = {
        resume_id for (resume_id,) in db.query(Offer.resume_id).filter(
            Offer.position_id.in_(position_ids),
            Offer.departed_at.isnot(None),
        ).all()
    }
    candidates = []
    for resume in resumes:
        if resume.status in EXCLUDED_RESUME_STATUSES or resume.id in departed_resume_ids:
            continue
        stage, achieved_at = _result_stage(db, resume)
        rank = float(result_coefficients.get(stage, 0))
        key = _candidate_identity_key(resume)
        candidates.append((key, rank, achieved_at, resume, stage))
    chosen = {}
    for item in sorted(candidates, key=lambda row: (
        -row[1], row[3].status == ResumeStatus.OFFER_REJECTED, row[2], str(row[3].id),
    )):
        chosen.setdefault(item[0], item)
    grouped = defaultdict(list)
    for _, _, achieved_at, resume, stage in chosen.values():
        grouped[resume.position_id].append((resume, stage, achieved_at))
    for items in grouped.values():
        items.sort(key=lambda row: (
            -float(result_coefficients.get(row[1], 0)),
            row[0].status == ResumeStatus.OFFER_REJECTED, row[2], str(row[0].id),
        ))
    return grouped


def _offer_issued_at(db: Session, resume: Resume, cutoff: datetime) -> datetime:
    """Keep the issued-Offer milestone after rejection, without acceptance credit."""
    sent_at = db.query(func.min(Offer.sent_at)).filter(
        Offer.resume_id == resume.id, Offer.sent_at <= cutoff,
    ).scalar()
    event_at = db.query(func.min(ResumeStatusEvent.occurred_at)).filter(
        ResumeStatusEvent.resume_id == resume.id,
        ResumeStatusEvent.new_status == ResumeStatus.OFFER_PENDING.value,
        ResumeStatusEvent.occurred_at <= cutoff,
    ).scalar()
    evidence = [_aware(value) for value in (sent_at, event_at) if value is not None]
    return min(evidence) if evidence else _aware(resume.created_at)


def _resume_status_at(
    db: Session,
    resume: Resume,
    cutoff: datetime,
) -> Optional[tuple[ResumeStatus, datetime]]:
    latest_occurred_at = (
        db.query(func.max(ResumeStatusEvent.occurred_at))
        .filter(
            ResumeStatusEvent.resume_id == resume.id,
            ResumeStatusEvent.occurred_at <= cutoff,
        )
        .scalar()
    )
    events = (
        db.query(ResumeStatusEvent)
        .filter(
            ResumeStatusEvent.resume_id == resume.id,
            ResumeStatusEvent.occurred_at == latest_occurred_at,
        )
        .all()
        if latest_occurred_at is not None
        else []
    )
    if not events:
        if _aware(resume.created_at) > cutoff:
            return None
        status = resume.status
        achieved_at = _aware(resume.created_at)
    else:
        # One lifecycle operation can persist several transitions with the same
        # timestamp. UUID ordering does not describe their causal order. The
        # terminal transition is the one whose new status is not consumed as
        # another transition's old status (for example in_progress -> pending
        # result -> passed).
        intermediate_statuses = {
            event.old_status for event in events if event.old_status
        }
        terminal_events = [
            event for event in events
            if event.new_status not in intermediate_statuses
        ]
        event = min(terminal_events or events, key=lambda item: str(item.id))
        try:
            status = ResumeStatus(event.new_status)
        except ValueError:
            return None
        achieved_at = _aware(event.occurred_at)
    return status, achieved_at


def _historical_result_stage(
    db: Session,
    resume: Resume,
    cutoff: datetime,
) -> Optional[tuple[str, datetime]]:
    # Onboarding is a business date (company midnight), while Offer decisions
    # have a precise timestamp. A same-day acceptance event can therefore sort
    # after onboarding. Use the actual lifecycle evidence before replaying
    # resume events, so confirmed hires retain their onboarding coefficient.
    onboarded_offer = (
        db.query(Offer)
        .filter(
            Offer.resume_id == resume.id,
            Offer.position_id == resume.position_id,
            Offer.actual_onboarded_at <= cutoff,
        )
        .order_by(Offer.actual_onboarded_at.desc())
        .first()
    )
    if onboarded_offer is not None:
        departed_at = _aware(onboarded_offer.departed_at)
        if departed_at is not None and departed_at <= cutoff:
            return _departed_result_stage(onboarded_offer)
        return "onboarded", _aware(onboarded_offer.actual_onboarded_at)
    historical_status = _resume_status_at(db, resume, cutoff)
    if historical_status is None:
        return None
    status, achieved_at = historical_status
    if status == ResumeStatus.OFFER_REJECTED:
        return "offer_pending", _offer_issued_at(db, resume, cutoff)
    if status == ResumeStatus.DEPARTED:
        offer = (
            db.query(Offer)
            .filter(
                Offer.resume_id == resume.id,
                Offer.departed_at.isnot(None),
                Offer.departed_at <= cutoff,
            )
            .order_by(Offer.departed_at.desc())
            .first()
        )
        if offer is None or offer.actual_onboarded_at is None:
            return None
        stage, achieved_at = _departed_result_stage(offer)
    elif status == ResumeStatus.COMPLETED:
        stage = "onboarded"
    elif status in {ResumeStatus.OFFER_ACCEPTED, ResumeStatus.ONBOARDING}:
        stage = "offer_accepted"
    elif status == ResumeStatus.OFFER_PENDING:
        stage = "offer_pending"
    elif status == ResumeStatus.INTERVIEW_PASSED:
        stage = "interview_passed"
    elif status in {ResumeStatus.PENDING_INTERVIEW_RESULT, ResumeStatus.PENDING_NEXT_INTERVIEW}:
        stage = "business_interview_completed"
    elif status in EXCLUDED_RESUME_STATUSES:
        return None
    else:
        stage = "open"
    if stage == "open":
        completed_at = func.coalesce(Interview.ended_at, Interview.created_at)
        interview = (
            db.query(Interview)
            .filter(
                Interview.resume_id == resume.id,
                Interview.status == InterviewStatus.COMPLETED,
                completed_at <= cutoff,
            )
            .order_by(completed_at.desc())
            .first()
        )
        if interview is not None:
            stage = (
                "hr_interview_completed"
                if interview.interview_category == "hr"
                else "business_interview_completed"
            )
            achieved_at = _aware(interview.ended_at) or _aware(interview.created_at)
    return stage, achieved_at


def _candidate_allocations_at(
    db: Session,
    positions: Iterable[Position],
    result_coefficients: dict,
    cutoff: datetime,
) -> dict[UUID, list[tuple[Resume, str, datetime]]]:
    position_ids = [position.id for position in positions]
    if not position_ids:
        return {}
    departed_resume_ids = {
        resume_id for (resume_id,) in db.query(Offer.resume_id).filter(
            Offer.position_id.in_(position_ids),
            Offer.departed_at.isnot(None),
            Offer.departed_at <= cutoff,
        ).all()
    }
    candidates = []
    rejected_resume_ids = set()
    for resume in db.query(Resume).filter(Resume.position_id.in_(position_ids)).all():
        if resume.id in departed_resume_ids:
            continue
        result = _historical_result_stage(db, resume, cutoff)
        if result is None:
            continue
        stage, achieved_at = result
        if stage == "offer_pending":
            historical_status = _resume_status_at(db, resume, cutoff)
            if historical_status and historical_status[0] == ResumeStatus.OFFER_REJECTED:
                rejected_resume_ids.add(resume.id)
        rank = float(result_coefficients.get(stage, 0))
        key = _candidate_identity_key(resume)
        candidates.append((key, rank, achieved_at, resume, stage))
    chosen = {}
    for item in sorted(candidates, key=lambda row: (
        -row[1], row[3].id in rejected_resume_ids, row[2], str(row[3].id),
    )):
        chosen.setdefault(item[0], item)
    grouped = defaultdict(list)
    for _, _, achieved_at, resume, stage in chosen.values():
        grouped[resume.position_id].append((resume, stage, achieved_at))
    for items in grouped.values():
        items.sort(key=lambda row: (
            -float(result_coefficients.get(row[1], 0)),
            row[0].id in rejected_resume_ids, row[2], str(row[0].id),
        ))
    return grouped


def _day_count(start: datetime, end: datetime) -> int:
    if end < start:
        return 0
    start_date = start.astimezone(COMPANY_TZ).date()
    end_date = end.astimezone(COMPANY_TZ).date()
    return (end_date - start_date).days + 1


def _approved_pauses(db: Session, slot_id: UUID) -> list[RecruitmentPause]:
    return db.query(RecruitmentPause).filter(RecruitmentPause.slot_id == slot_id, RecruitmentPause.status == "approved").all()


def _position_status_timeline(
    db: Session, position: Position, cutoff: datetime,
) -> tuple[str, list[tuple[datetime, datetime]], datetime]:
    """Reconstruct status and paused calendar days at the reporting cutoff."""
    events = (
        db.query(PositionEvent)
        .filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type.in_([
                PositionEventType.INITIAL_STATUS,
                PositionEventType.STATUS_BASELINE,
                PositionEventType.STATUS_CHANGED,
                PositionEventType.RESTORED,
            ]),
        )
        .order_by(PositionEvent.occurred_at, PositionEvent.id)
        .all()
    )
    # Legacy baselines store enum names in uppercase. With no baseline, the
    # first transition's old value describes the state before that transition.
    corrected_events = set()
    for index, event in enumerate(events):
        if not _is_reopen_event(event) or _starts_new_recruitment_cycle(event):
            continue
        # Keep the audit trail, but undo the accidental terminal transition
        # when replaying performance history. Correction does not stop clocks.
        for previous in reversed(events[:index]):
            if (previous.new_value or "").lower() in {"closed", "cancelled"}:
                corrected_events.add(previous.id)
                break
            if _is_reopen_event(previous):
                break
    events = [event for event in events if event.id not in corrected_events]
    status = str(getattr(position.status, "value", position.status)).lower()
    if events:
        status = (events[0].old_value or events[0].new_value or status).lower()
    status_since = _aware(position.created_at)
    paused_since = _aware(position.created_at) if status == PositionStatus.PAUSED.value else None
    pauses = []
    for event in events:
        occurred_at = _aware(event.occurred_at)
        if occurred_at > cutoff:
            break
        next_status = (event.new_value or status).lower()
        if status == PositionStatus.PAUSED.value and next_status != status:
            # The resume date counts as an active day; pause dates are deducted
            # through the preceding company calendar day.
            resume_day_start = datetime.combine(
                occurred_at.astimezone(COMPANY_TZ).date(), time.min, COMPANY_TZ,
            )
            pause_end = resume_day_start - timedelta(microseconds=1)
            if paused_since is not None and paused_since <= pause_end:
                pauses.append((paused_since, pause_end))
            paused_since = None
        elif next_status == PositionStatus.PAUSED.value and status != next_status:
            paused_since = occurred_at
        if next_status != status:
            status_since = occurred_at
        status = next_status
    if paused_since is not None and paused_since <= cutoff:
        pauses.append((paused_since, cutoff))
    return status, pauses, status_since


def _deducted_days(
    pauses: list[tuple[datetime, Optional[datetime]]], start: datetime, end: datetime,
) -> int:
    # Merge calendar-day ranges so overlapping HC and position pauses are only
    # deducted once, including ranges that overlap on a single calendar day.
    ranges = []
    for pause_start, pause_end in pauses:
        clipped_start = max(pause_start, start)
        clipped_end = min(pause_end or end, end)
        if clipped_start <= clipped_end:
            ranges.append((
                clipped_start.astimezone(COMPANY_TZ).date(),
                clipped_end.astimezone(COMPANY_TZ).date(),
            ))
    total = 0
    last_end = None
    for first, last in sorted(ranges):
        if last_end is not None:
            first = max(first, last_end + timedelta(days=1))
        if first <= last:
            total += (last - first).days + 1
        last_end = max(last_end, last) if last_end is not None else last
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


def _next_company_day_start(value: datetime) -> datetime:
    local_date = _aware(value).astimezone(COMPANY_TZ).date() + timedelta(days=1)
    return datetime.combine(local_date, time.min, COMPANY_TZ).astimezone(timezone.utc)


def _owner_events(db: Session, position_id: UUID, cutoff: datetime) -> list[PositionEvent]:
    return (
        db.query(PositionEvent)
        .filter(
            PositionEvent.position_id == position_id,
            PositionEvent.event_type.in_([
                PositionEventType.INITIAL_OWNER,
                PositionEventType.OWNER_CHANGED,
            ]),
            PositionEvent.occurred_at <= cutoff,
        )
        .order_by(PositionEvent.occurred_at, PositionEvent.id)
        .all()
    )


def _owner_at(db: Session, position: Position, cutoff: datetime) -> Optional[UUID]:
    events = _owner_events(db, position.id, cutoff)
    raw_owner_id = events[-1].new_value if events else None
    if not raw_owner_id:
        next_transfer = db.query(PositionEvent).filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type == PositionEventType.OWNER_CHANGED,
            PositionEvent.occurred_at > cutoff,
        ).order_by(PositionEvent.occurred_at, PositionEvent.id).first()
        if next_transfer is None:
            return position.hiring_manager_id
        raw_owner_id = next_transfer.old_value
    try:
        return UUID(raw_owner_id)
    except (TypeError, ValueError):
        return None


def _owner_holding_start(
    db: Session,
    position: Position,
    owner_id: UUID,
    cutoff: datetime,
) -> Optional[datetime]:
    events = _owner_events(db, position.id, cutoff)
    matching_event = next(
        (event for event in reversed(events) if event.new_value == str(owner_id)),
        None,
    )
    if matching_event is None:
        return None
    occurred_at = _aware(matching_event.occurred_at)
    if matching_event.event_type == PositionEventType.OWNER_CHANGED:
        return _next_company_day_start(occurred_at)
    return occurred_at


def _owner_holding_intervals(
    db: Session,
    position: Position,
    owner_id: UUID,
    cutoff: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return every non-overlapping interval held by one owner through cutoff.

    The outgoing owner keeps the transfer calendar day. A new owner's interval
    begins on the next company day, matching the existing no-double-counting
    rule. When a position later returns to an earlier owner, their prior and
    resumed intervals are both retained instead of discarding the earlier work.
    """
    events = _owner_events(db, position.id, cutoff)
    cycle_starts = {_aware(event.occurred_at) for event in position_reopen_events(db, position)}
    if not events:
        if _owner_at(db, position, cutoff) != owner_id:
            return []
        return [(_aware(position.created_at), cutoff)]

    intervals = []
    active_owner = None
    active_start = None
    first_event = events[0]
    if first_event.event_type == PositionEventType.OWNER_CHANGED:
        try:
            active_owner = UUID(first_event.old_value) if first_event.old_value else None
        except (TypeError, ValueError):
            active_owner = None
        active_start = _aware(position.created_at)

    for event in events:
        occurred_at = _aware(event.occurred_at)
        if active_owner == owner_id and active_start is not None and active_start <= occurred_at:
            intervals.append((active_start, occurred_at))
        try:
            active_owner = UUID(event.new_value) if event.new_value else None
        except (TypeError, ValueError):
            active_owner = None
        active_start = (
            occurred_at
            if event.event_type == PositionEventType.INITIAL_OWNER or occurred_at in cycle_starts
            else _next_company_day_start(occurred_at)
        )

    if active_owner == owner_id and active_start is not None and active_start <= cutoff:
        intervals.append((active_start, cutoff))
    return intervals


def _score_position(
    db: Session,
    position: Position,
    candidates: list[tuple[Resume, str, datetime]],
    config: PerformanceConfigResponse,
    *,
    period_start: datetime,
    cutoff: datetime,
    holding_intervals: Optional[list[tuple[datetime, datetime]]],
    eligible_only: bool = False,
    cycle_start: Optional[datetime] = None,
    recruitment_cycle: int = 1,
    cycle_config: Optional[dict] = None,
) -> PositionScore:
    if cycle_start is None:
        prior_reopens = [event for event in position_reopen_events(db, position)
                         if _aware(event.occurred_at) <= cutoff]
        if prior_reopens:
            cycle_start = _aware(prior_reopens[-1].occurred_at)
            recruitment_cycle = len(prior_reopens) + 1
    category = (cycle_config or {}).get("category", getattr(position.category, "value", position.category))
    priority = (cycle_config or {}).get("priority", position.priority)
    target_days = int(config.target_days[category])
    position_status, position_pauses, status_since = _position_status_timeline(db, position, cutoff)
    cancelled = position_status == PositionStatus.CANCELLED.value
    if position_status in {PositionStatus.CLOSED.value, PositionStatus.CANCELLED.value}:
        # Retain the score earned at closure/cancellation, including its result stage
        # and time coefficient. Later days or candidate progress cannot add to it.
        cutoff = min(cutoff, status_since)
        candidates = _candidate_allocations_at(
            db, [position], config.result_coefficients, cutoff,
        ).get(position.id, [])
    slots = (
        db.query(RecruitmentHcSlot)
        .filter(RecruitmentHcSlot.position_id == position.id)
        .order_by(RecruitmentHcSlot.slot_number, RecruitmentHcSlot.recruitment_round)
        .all()
    )
    hc_scores = []
    visible_slots = [slot for slot in slots if _aware(slot.assigned_at) <= cutoff
                     and (cycle_start is None or _aware(slot.assigned_at) >= cycle_start)]
    if cycle_start is not None:
        previous_candidates = {slot.candidate_resume_id for slot in slots
                               if _aware(slot.assigned_at) < cycle_start and slot.candidate_resume_id}
        candidates = [candidate for candidate in candidates
                      if candidate[0].id not in previous_candidates
                      and _aware(candidate[0].created_at) >= cycle_start]
    fixed_resume_ids = {
        slot.candidate_resume_id for slot in visible_slots if slot.candidate_resume_id is not None
    }
    available_candidates = [candidate for candidate in candidates if candidate[0].id not in fixed_resume_ids]
    candidate_index = 0
    for slot in visible_slots:
        if slot.candidate_resume_id is not None:
            resume = db.query(Resume).filter(Resume.id == slot.candidate_resume_id).first()
            historical_result = _historical_result_stage(db, resume, cutoff) if resume else None
            stage = historical_result[0] if historical_result else "open"
        else:
            candidate = available_candidates[candidate_index] if candidate_index < len(available_candidates) else None
            candidate_index += 1 if candidate else 0
            resume, stage, _ = candidate if candidate else (None, "open", cutoff)
        if eligible_only and stage not in HANDOFF_CREDIT_STAGES:
            continue
        result_coefficient = float(config.result_coefficients[stage])
        historical_status = _resume_status_at(db, resume, cutoff) if resume and stage == "offer_pending" else None
        retained_after_offer_rejection = bool(
            historical_status and historical_status[0] == ResumeStatus.OFFER_REJECTED
        )
        offer = None
        if resume is not None:
            offer = db.query(Offer).filter(Offer.resume_id == resume.id).order_by(Offer.updated_at.desc()).first()
        departed_at = _aware(offer.departed_at) if offer else None
        departure_visible = departed_at is not None and departed_at <= cutoff
        status = slot.status
        if status in DEPARTED_HC_STATUSES and not departure_visible:
            status = "completed"
        if status in {"cancelled", "frozen"}:
            if eligible_only:
                continue
            hc_scores.append(HcScore(
                slot_id=slot.id, slot_number=slot.slot_number,
                recruitment_round=slot.recruitment_round, candidate_name=None,
                result_stage="已剔除", result_coefficient=0, target_days=target_days,
                actual_days=0, deducted_days=0, effective_held_days=0,
                time_coefficient=0, task_points=0, score=0, status=status,
            ))
            continue
        slot_start = max(_aware(slot.assigned_at), period_start)
        accepted_at = _aware(offer.accepted_at if offer else slot.accepted_at)
        onboarded_at = _aware(offer.actual_onboarded_at if offer else slot.completed_at)
        accepted_at = accepted_at if accepted_at is None or accepted_at <= cutoff else None
        onboarded_at = onboarded_at if onboarded_at is None or onboarded_at <= cutoff else None
        weight_end = min(value for value in [cutoff, accepted_at, onboarded_at] if value is not None)
        if weight_end < period_start:
            continue
        pauses = position_pauses + [
            (_aware(pause.start_at), _aware(pause.end_at))
            for pause in _approved_pauses(db, slot.id)
        ]
        score_intervals = holding_intervals
        if score_intervals is None:
            score_intervals = [(slot_start, weight_end)]
        deducted = 0
        effective_days = 0
        for held_start, held_end in score_intervals:
            interval_start = max(slot_start, held_start)
            interval_end = min(weight_end, held_end)
            if interval_start > interval_end:
                continue
            interval_deducted = _deducted_days(pauses, interval_start, interval_end)
            deducted += interval_deducted
            effective_days += max(
                0,
                _day_count(interval_start, interval_end) - interval_deducted,
            )
        slot_cycle_start = max(_aware(slot.round_started_at), period_start)
        slot_cycle_end = min(accepted_at or cutoff, cutoff)
        cycle_deducted = _deducted_days(pauses, slot_cycle_start, slot_cycle_end)
        actual_days = max(1, _day_count(slot_cycle_start, slot_cycle_end) - cycle_deducted)
        time_coefficient = _time_coefficient(actual_days, target_days, config.time_coefficients)
        earned_task_points = float(priority * effective_days)
        score = earned_task_points * time_coefficient * result_coefficient
        task_points = 0.0 if cancelled else earned_task_points
        hc_scores.append(HcScore(
            slot_id=slot.id,
            slot_number=slot.slot_number,
            recruitment_round=slot.recruitment_round,
            candidate_name=resume.candidate_name if resume else None,
            result_stage="Offer已发出" if retained_after_offer_rejection else RESULT_LABELS[stage],
            retained_after_offer_rejection=retained_after_offer_rejection,
            result_coefficient=result_coefficient,
            target_days=target_days,
            actual_days=actual_days,
            deducted_days=deducted,
            effective_held_days=effective_days,
            time_coefficient=time_coefficient,
            task_points=task_points,
            score=score,
            status=status,
            departed_at=departed_at if departure_visible else None,
            departure_released_hc=(
                offer.departure_released_hc if offer and departure_visible else None
            ),
        ))
    task_points = sum(item.task_points for item in hc_scores)
    score = sum(item.score for item in hc_scores)
    scorable = [item for item in hc_scores if item.status not in {"cancelled", "frozen"}]
    valid = [item for item in scorable if item.status not in HISTORICAL_HC_STATUSES]
    return PositionScore(
        position_id=position.id,
        recruitment_cycle=recruitment_cycle,
        cycle_started_at=cycle_start or _aware(position.created_at),
        title=position.title,
        category=category,
        priority=priority,
        hc_count=len(valid),
        onboarded_count=sum(item.status == "completed" for item in valid),
        current_employed_count=sum(item.status == "completed" for item in valid),
        cumulative_onboarded_count=sum(
            item.status == "completed" or item.departed_at is not None
            for item in hc_scores
        ),
        departed_count=sum(item.departed_at is not None for item in hc_scores),
        excluded_count=sum(item.status in {"cancelled", "frozen"} for item in hc_scores),
        task_points=task_points,
        score=score,
        achievement_rate=(score / task_points if task_points else None),
        highest_result_stage=max(scorable, key=lambda item: item.result_coefficient).result_stage if scorable else "无有效任务",
        slots=hc_scores,
    )


def _first_decision_milestone(
    db: Session,
    position: Position,
    cutoff: datetime,
) -> Optional[ResumeStatusEvent]:
    reopens = [event for event in position_reopen_events(db, position) if _aware(event.occurred_at) <= cutoff]
    cycle_start = _aware(reopens[-1].occurred_at) if reopens else _aware(position.created_at)
    return (
        db.query(ResumeStatusEvent)
        .join(Resume, Resume.id == ResumeStatusEvent.resume_id)
        .filter(
            Resume.position_id == position.id,
            ResumeStatusEvent.new_status.in_(HANDOFF_CREDIT_STATUSES),
            ResumeStatusEvent.occurred_at <= cutoff,
            Resume.created_at >= cycle_start,
            ResumeStatusEvent.occurred_at >= cycle_start,
        )
        .order_by(ResumeStatusEvent.occurred_at, ResumeStatusEvent.id)
        .first()
    )


def _credit_detail_for_transfer(
    db: Session,
    position: Position,
    *,
    transfer_at: datetime,
    old_owner_id: UUID,
) -> Optional[tuple[UUID, HandoffCredit]]:
    milestone = _first_decision_milestone(db, position, transfer_at)
    if milestone is None:
        return None
    milestone_at = _aware(milestone.occurred_at)
    recipient_id = _owner_at(db, position, milestone_at)
    if recipient_id != old_owner_id:
        return None
    prior_handoff = (
        db.query(PositionEvent)
        .filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type == PositionEventType.OWNER_CHANGED,
            PositionEvent.occurred_at >= milestone_at,
            PositionEvent.occurred_at < transfer_at,
        )
        .first()
    )
    if prior_handoff is not None:
        return None
    period = current_period(transfer_at.astimezone(COMPANY_TZ).date())
    _, _, period_start, _ = parse_period(period)
    config = get_config(db, period)
    category = getattr(position.category, "value", position.category)
    if category not in config.target_days:
        return None
    holding_intervals = _owner_holding_intervals(
        db,
        position,
        recipient_id,
        transfer_at,
    )
    allocations = _candidate_allocations_at(db, [position], config.result_coefficients, transfer_at)
    scored = _score_position(
        db,
        position,
        allocations.get(position.id, []),
        config,
        period_start=period_start,
        cutoff=transfer_at,
        holding_intervals=holding_intervals,
        eligible_only=True,
    )
    return recipient_id, HandoffCredit(
        position_id=position.id,
        position_title=position.title,
        transferred_at=transfer_at,
        milestone_at=milestone_at,
        task_points=scored.task_points,
        score=scored.score,
        slots=scored.slots,
    )


def build_handoff_credit_metadata(
    db: Session,
    position: Position,
    *,
    transfer_at: datetime,
    old_owner_id: Optional[UUID],
) -> Optional[dict]:
    if old_owner_id is None:
        return None
    sync_position_slots(db, position, assigned_at=_aware(position.created_at))
    db.flush()
    result = _credit_detail_for_transfer(
        db,
        position,
        transfer_at=transfer_at,
        old_owner_id=old_owner_id,
    )
    if result is None:
        return None
    recipient_id, detail = result
    return {
        "status": "awarded" if detail.slots else "evaluated_zero",
        "recipient_user_id": str(recipient_id),
        "period": current_period(transfer_at.astimezone(COMPANY_TZ).date()),
        "detail": detail.model_dump(mode="json"),
    }


def _handoff_credits_for_period(
    db: Session,
    positions: list[Position],
    period: str,
    period_start: datetime,
    cutoff: datetime,
) -> dict[UUID, list[HandoffCredit]]:
    positions_by_id = {position.id: position for position in positions}
    events = (
        db.query(PositionEvent)
        .filter(
            PositionEvent.position_id.in_(positions_by_id),
            PositionEvent.event_type == PositionEventType.OWNER_CHANGED,
            PositionEvent.occurred_at >= period_start,
            PositionEvent.occurred_at <= cutoff,
        )
        .order_by(PositionEvent.occurred_at, PositionEvent.id)
        .all()
    ) if positions_by_id else []
    result = defaultdict(list)
    for event in events:
        # A new cycle retains the previous owner's full position ledger.
        # Changing owner at that boundary must not add a second handoff award.
        if any(_aware(reopen.occurred_at) == _aware(event.occurred_at)
               for reopen in position_reopen_events(db, positions_by_id[event.position_id])):
            continue
        metadata = dict(event.event_metadata or {}).get("handoff_credit")
        recipient_id = None
        detail = None
        if metadata and metadata.get("period") == period:
            try:
                recipient_id = UUID(metadata["recipient_user_id"])
                detail = HandoffCredit.model_validate(metadata["detail"])
            except (KeyError, TypeError, ValueError):
                recipient_id = None
                detail = None
        if recipient_id is None:
            try:
                old_owner_id = UUID(event.old_value) if event.old_value else None
            except (TypeError, ValueError):
                old_owner_id = None
            if old_owner_id is not None:
                computed = _credit_detail_for_transfer(
                    db,
                    positions_by_id[event.position_id],
                    transfer_at=_aware(event.occurred_at),
                    old_owner_id=old_owner_id,
                )
                if computed is not None:
                    recipient_id, detail = computed
        # A handoff is only frozen while the milestone owner no longer owns the
        # position at the reporting cutoff. If the position is handed back,
        # their live position ledger resumes and the temporary handoff credit
        # must disappear instead of being counted twice.
        returned_to_recipient = (
            recipient_id is not None
            and _owner_at(db, positions_by_id[event.position_id], cutoff) == recipient_id
        )
        if (
            recipient_id is not None
            and detail is not None
            and detail.slots
            and not returned_to_recipient
        ):
            position_status, _, _ = _position_status_timeline(
                db, positions_by_id[event.position_id], cutoff,
            )
            if position_status == PositionStatus.CANCELLED.value:
                # Keep earned handoff scores in the numerator while removing
                # cancelled task points from the achievement-rate denominator.
                detail = detail.model_copy(deep=True)
                detail.task_points = 0
                for slot in detail.slots:
                    slot.task_points = 0
            result[recipient_id].append(detail)
    return result


def _with_position_cycle_statuses(db: Session, overview: PerformanceOverview) -> PerformanceOverview:
    # Enrich the response without changing scores or persisted settlement snapshots.
    rows = [row for person in overview.people for row in [*person.positions, *person.handoff_credits]]
    position_ids = {row.position_id for row in rows}
    positions = {
        position.id: position
        for position in db.query(Position).filter(Position.id.in_(position_ids)).all()
    } if position_ids else {}
    reopens = {position_id: position_reopen_events(db, position)
               for position_id, position in positions.items()}
    for row in rows:
        position = positions.get(row.position_id)
        row.position_status = getattr(position.status, "value", position.status) if position else None
        if isinstance(row, PositionScore) and row.recruitment_cycle <= len(reopens.get(row.position_id, [])):
            # Each reopen ends the preceding cycle. Only the latest cycle uses
            # the position's live status; historical rows keep their final state.
            boundary = reopens[row.position_id][row.recruitment_cycle - 1]
            row.position_status = _position_status_timeline(
                db, position, _aware(boundary.occurred_at) - timedelta(microseconds=1),
            )[0]
    return overview


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
        return _with_position_cycle_statuses(db, settled)

    positions = db.query(Position).filter(Position.deleted_at.is_(None)).all()
    for position in positions:
        sync_position_slots(db, position, assigned_at=now)
    db.flush()
    allocations = _candidate_allocations(db, positions, config.result_coefficients)
    person_positions = defaultdict(list)

    for position in positions:
        category = getattr(position.category, "value", position.category)
        if category not in config.target_days:
            continue
        reopens = position_reopen_events(db, position)
        starts = [None, *[_aware(event.occurred_at) for event in reopens]]
        for index, cycle_start in enumerate(starts):
            cycle_end = starts[index + 1] - timedelta(microseconds=1) if index + 1 < len(starts) else cutoff
            cycle_cutoff = min(cutoff, cycle_end)
            if cycle_cutoff < period_start or (cycle_start is not None and cycle_start > cycle_cutoff):
                continue
            owner_id = _owner_at(db, position, cycle_cutoff) if reopens else position.hiring_manager_id
            if owner_id is None or (user is not None and owner_id != user.id):
                continue
            candidates = (allocations.get(position.id, []) if cycle_cutoff == cutoff else
                          _candidate_allocations_at(db, [position], config.result_coefficients, cycle_cutoff).get(position.id, []))
            person_positions[owner_id].append(_score_position(
                db, position, candidates, config,
                period_start=period_start, cutoff=cycle_cutoff,
                holding_intervals=_owner_holding_intervals(db, position, owner_id, cycle_cutoff),
                cycle_start=cycle_start, recruitment_cycle=index + 1,
                cycle_config=(reopens[index].event_metadata or {}).get("previous_recruitment_config") if index < len(reopens) else None,
            ))

    person_credits = _handoff_credits_for_period(
        db,
        positions,
        period,
        period_start,
        cutoff,
    )
    relevant_user_ids = set(person_positions) | set(person_credits)
    if user is not None:
        relevant_user_ids &= {user.id}
    people = {
        person.id: person
        for person in db.query(User).filter(User.id.in_(relevant_user_ids)).all()
    } if relevant_user_ids else {}

    result_people = []
    for owner_id in sorted(relevant_user_ids, key=str):
        scores = person_positions.get(owner_id, [])
        credits = person_credits.get(owner_id, [])
        person = people.get(owner_id)
        if person is None:
            continue
        task_points = sum(item.task_points for item in scores) + sum(item.task_points for item in credits)
        score = sum(item.score for item in scores) + sum(item.score for item in credits)
        result_people.append(PersonScore(
            user_id=owner_id,
            name=person.full_name or person.email,
            email=person.email,
            is_active=person.is_active,
            hc_count=sum(item.hc_count for item in scores),
            excluded_count=sum(item.excluded_count for item in scores),
            onboarded_count=sum(item.onboarded_count for item in scores),
            current_employed_count=sum(item.current_employed_count for item in scores),
            cumulative_onboarded_count=sum(item.cumulative_onboarded_count for item in scores),
            departed_count=sum(item.departed_count for item in scores),
            task_points=task_points,
            score=score,
            achievement_rate=(score / task_points if task_points else None),
            positions=scores,
            handoff_credits=credits,
        ))
    result_people.sort(key=lambda person: person.name)
    return _with_position_cycle_statuses(db, PerformanceOverview(
        period=period,
        as_of=cutoff.astimezone(COMPANY_TZ).date(),
        status="trial" if period == "2026-Q3" else "live",
        people=result_people,
    ))


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
