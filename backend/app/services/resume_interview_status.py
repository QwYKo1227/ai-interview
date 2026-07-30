"""Keep a resume's interview-stage status aligned with its interviews."""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.models import (
    Interview,
    InterviewResult,
    InterviewStatus,
    Resume,
    ResumeStatus,
    ScreeningResult,
)


INTERVIEW_STAGE_STATUSES = {
    ResumeStatus.PENDING_INTERVIEW,
    ResumeStatus.INTERVIEW_SCHEDULED,
    ResumeStatus.INTERVIEW_IN_PROGRESS,
    ResumeStatus.PENDING_INTERVIEW_RESULT,
    ResumeStatus.PENDING_NEXT_INTERVIEW,
    ResumeStatus.INTERVIEW_PASSED,
    ResumeStatus.INTERVIEW_FAILED,
}


FINAL_RESUME_STATUS = {
    InterviewResult.NEXT_ROUND: ResumeStatus.PENDING_NEXT_INTERVIEW,
    InterviewResult.PASSED: ResumeStatus.INTERVIEW_PASSED,
    InterviewResult.HIRED: ResumeStatus.INTERVIEW_PASSED,
    InterviewResult.REJECTED: ResumeStatus.INTERVIEW_FAILED,
}


def _resume(interview: Interview) -> Resume | None:
    return interview.resume


def set_resume_interview_status(interview: Interview, status: ResumeStatus) -> None:
    resume = _resume(interview)
    if resume is not None and resume.status in INTERVIEW_STAGE_STATUSES:
        resume.status = status


def mark_interview_scheduled(interview: Interview) -> None:
    set_resume_interview_status(interview, ResumeStatus.INTERVIEW_SCHEDULED)


def mark_interview_started(interview: Interview) -> None:
    set_resume_interview_status(interview, ResumeStatus.INTERVIEW_IN_PROGRESS)


def mark_interview_ended(interview: Interview) -> None:
    set_resume_interview_status(interview, ResumeStatus.PENDING_INTERVIEW_RESULT)


def mark_legacy_interview_ended(interview: Interview) -> None:
    """Close lifecycle fields when a legacy evaluation flow starts or completes."""
    now = datetime.now(timezone.utc)
    interview.lifecycle_state = "ended"
    interview.ended_at = interview.ended_at or now
    interview.notes_revealed_at = interview.notes_revealed_at or interview.ended_at
    mark_interview_ended(interview)
    for panel in interview.panels or []:
        panel.notes_frozen_at = panel.notes_frozen_at or interview.ended_at


def mark_legacy_interview_completed(interview: Interview) -> None:
    """Synchronize lifecycle and analysis fields after legacy evaluation."""
    interview.status = InterviewStatus.COMPLETED
    mark_legacy_interview_ended(interview)

    has_sealed_recording = (
        interview.recording_state == "sealed"
        and bool((interview.audio_records or {}).get("full_interview"))
    )
    if not has_sealed_recording and interview.ai_analysis_status in {
        "pending",
        "transcribing",
        "analyzing",
    }:
        interview.ai_analysis_status = "not_applicable"
        interview.ai_analysis_error = None
        if interview.asr_job_status == "pending":
            interview.asr_job_status = "not_applicable"
            interview.asr_job_next_poll_at = None


def apply_final_decision(interview: Interview) -> None:
    resume = _resume(interview)
    if resume is None or resume.status not in INTERVIEW_STAGE_STATUSES:
        return
    target = FINAL_RESUME_STATUS.get(interview.result)
    if target is not None:
        resume.status = target
    if interview.result in {InterviewResult.NEXT_ROUND, InterviewResult.PASSED, InterviewResult.HIRED}:
        resume.screening_result = ScreeningResult.PASSED
    elif interview.result == InterviewResult.REJECTED:
        resume.screening_result = ScreeningResult.REJECTED


def restore_after_cancellation(db: Session, interview: Interview) -> None:
    resume = _resume(interview)
    if resume is None or resume.status not in INTERVIEW_STAGE_STATUSES:
        return

    previous = (
        db.query(Interview)
        .filter(
            Interview.resume_id == interview.resume_id,
            Interview.id != interview.id,
            Interview.final_decision_at.isnot(None),
        )
        .order_by(Interview.round.desc(), Interview.created_at.desc())
        .first()
    )
    resume.status = (
        ResumeStatus.PENDING_NEXT_INTERVIEW
        if previous is not None and previous.result == InterviewResult.NEXT_ROUND
        else ResumeStatus.PENDING_INTERVIEW
    )
