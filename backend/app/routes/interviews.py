from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Response, File, UploadFile, Form, Query
from sqlalchemy.orm import Session
from app.core.tenant_dependencies import get_tenant_db
from app.config.tenant_session import tenant_session
from app.services.interview_service import (
    create_interview, get_interviews, get_interview, update_interview, update_interview_schedule, delete_interview,
    submit_interview_score, update_interview_questions, export_interview_result,
    submit_interview_panel_score, aggregate_panel_scores, start_interview, cancel_interview, get_submission_status,
    require_schedule_available,
)
from app.schemas.interview import (
    InterviewResponse, InterviewDetailResponse, InterviewCreate, InterviewUpdate,
    InterviewScore, InterviewPanelResponse, RecordingSessionResponse,
    RecordingSessionRequest, RealtimeTranscriptBatchRequest, EndInterviewRequest,
    ForceEndInterviewRequest, LiveNotesRequest,
    NoteSupplementRequest, HumanReviewRequest, FinalDecisionRequest,
    FinalDecisionCorrectionRequest, CancelInterviewResponse,
    ReviewerReplacementRequest, validate_interview_time_range,
    CorrectedTranscriptRequest, SpeakerLabelsRequest, InterviewScheduleUpdate,
    InterviewScheduleNotificationRequest,
)
from app.models.models import User, UserRole, Resume, Position, Interview, InterviewStatus, InterviewResult, InterviewPanel
from app.routes.auth import get_current_user
from app.core.security import check_roles

from typing import Annotated, List, Optional
from uuid import UUID
from datetime import datetime
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator
import logging
from html import escape
from app.core.observability import background_task_context
from app.services.interview_access import (
    require_interview_access,
    require_interview_assignment,
    require_assigned_interviewer,
)
from app.services.interview_lifecycle_service import (
    REMINDER_COOLDOWN_HOURS,
    SCORE_DIMENSIONS,
    add_note_supplement,
    analyze_sealed_recording,
    append_recording_chunk,
    begin_ending,
    force_end_interview,
    confirm_final_decision,
    correct_final_decision,
    confirm_recording,
    heartbeat_recording,
    panel_for_user,
    persist_realtime_transcript,
    reserve_recording,
    replace_reviewer,
    save_live_notes,
    seal_recording,
    submit_human_review,
    process_asr_job,
    as_utc,
    utcnow,
)
from app.services.audio_service import AsrServiceError, create_realtime_session, get_transcription_config
from app.services.resume_interview_status import (
    mark_legacy_interview_completed,
    mark_legacy_interview_ended,
)
from app.services.interview_schedule_notification import (
    issue_schedule_notification_token,
    validate_schedule_notification_token,
)

logger = logging.getLogger(__name__)

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

router = APIRouter(
    prefix="/interviews",
    tags=["interviews"]
)

class ConfirmResult(BaseModel):
    result: str

class CancelRequest(BaseModel):
    reason: str = None

class EmailSendRequest(BaseModel):
    subject: str
    content: str

class EmailPreviewRequest(BaseModel):
    resume_id: UUID
    position_id: UUID
    interview_time: datetime
    interview_end_time: datetime
    panel_members: List[UUID] = Field(default_factory=list)
    round: int = 1
    interview_type: str = 'onsite'
    interview_category: str = 'technical'
    interview_location: Optional[str] = None
    meeting_link: Optional[str] = None

    @model_validator(mode="after")
    def validate_scheduling_details(self):
        validate_interview_time_range(self.interview_time, self.interview_end_time)
        if self.interview_type == "onsite" and not (self.interview_location or "").strip():
            raise ValueError("现场面试必须填写面试地点")
        if self.interview_type == "video" and not (self.meeting_link or "").strip():
            raise ValueError("视频面试必须填写会议链接")
        return self

@router.post("/{interview_id}/panel-score", response_model=InterviewPanelResponse)
def submit_panel_score_route(
    interview_id: UUID, 
    score_data: InterviewScore, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    require_interview_assignment(db, interview_id, current_user)
    panel, all_submitted = submit_interview_panel_score(
        db,
        interview_id,
        current_user.id,
        score_data,
        actor=current_user,
    )
    
    if not panel:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    from app.models.models import Interview, InterviewPanel
    
    db_interview = db.query(Interview).get(interview_id)
    
    if all_submitted and db_interview:
        print(f"All panel members submitted. Triggering aggregation for interview {interview_id}")
        aggregate_panel_scores(db, interview_id, background_tasks)
        panel.interview_status = "analyzing"
    else:
        if db_interview:
            panel.interview_status = db_interview.status.value
             
    return panel

@router.post("/{interview_id}/aggregate", response_model=InterviewResponse)
def aggregate_scores_route(
    interview_id: UUID, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_interview_access(db, interview_id, current_user)
    db_interview = aggregate_panel_scores(db, interview_id, background_tasks)
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview or panels not found")
    return db_interview

@router.post(
    "/{interview_id}/confirm",
    response_model=InterviewResponse,
    dependencies=[Depends(check_roles([UserRole.ADMIN, UserRole.HR]))],
)
def confirm_interview_result_route(
    interview_id: UUID,
    confirm_data: ConfirmResult,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_interview_access(db, interview_id, current_user)
    return confirm_final_decision(db, interview, current_user, confirm_data.result)

@router.post("/{interview_id}/cancel", response_model=CancelInterviewResponse)
def cancel_interview_route(
    interview_id: UUID,
    reason: Annotated[str, Query(min_length=1, max_length=500)],
    notify: bool = True,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """
    取消面试。
    """
    try:
        current = require_interview_access(db, interview_id, current_user)
        if current.lifecycle_state != "scheduled":
            raise HTTPException(status_code=409, detail="只能取消尚未开始的面试")
        db_interview = cancel_interview(db, interview_id, reason)
        if not db_interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        notification = {"success": False, "errors": []}
        if notify:
            try:
                from app.services.mail_service import get_mail_service
                notification = get_mail_service(db).send_interview_cancellation_for_interview(db_interview)
            except Exception as error:
                logger.warning(
                    "Interview cancellation notification failed (%s)",
                    type(error).__name__,
                )
                notification = {"success": False, "errors": ["Notification delivery failed"]}
        return CancelInterviewResponse.model_validate(db_interview).model_copy(update={
            "notification_sent": bool(notification["success"]) if notify else False,
            "notification_errors": notification.get("errors", []),
        })
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Interview cancellation failed (%s)", type(error).__name__)
        raise HTTPException(status_code=400, detail="取消面试失败")

@router.get("/{interview_id}/submission-status")
def get_submission_status_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取面试评分提交状态。
    返回各面试官是否已提交评分。
    """
    require_interview_access(db, interview_id, current_user)
    status = get_submission_status(db, interview_id)
    if not status:
        raise HTTPException(status_code=404, detail="Interview not found")
    return status


def _recording_response(interview: Interview) -> RecordingSessionResponse:
    return RecordingSessionResponse(
        session_id=interview.recording_session_id,
        owner_id=interview.recording_owner_id,
        recording_state=interview.recording_state,
        lifecycle_state=interview.lifecycle_state,
        reservation_expires_at=interview.recording_reservation_expires_at,
        next_chunk_index=len(interview.recording_chunks or []),
    )


@router.post("/{interview_id}/recording/reserve", response_model=RecordingSessionResponse)
def reserve_recording_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_assigned_interviewer(db, interview_id, current_user)
    return _recording_response(reserve_recording(db, interview_id, current_user))


@router.post("/{interview_id}/recording/confirm", response_model=RecordingSessionResponse)
def confirm_recording_route(
    interview_id: UUID,
    payload: RecordingSessionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_assigned_interviewer(db, interview_id, current_user)
    return _recording_response(confirm_recording(db, interview_id, payload.session_id, current_user))


@router.post("/{interview_id}/recording/heartbeat", response_model=RecordingSessionResponse)
def heartbeat_recording_route(
    interview_id: UUID,
    payload: RecordingSessionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_assigned_interviewer(db, interview_id, current_user)
    return _recording_response(heartbeat_recording(db, interview_id, payload.session_id, current_user))


@router.post("/{interview_id}/recording/realtime-session")
def create_realtime_session_route(
    interview_id: UUID,
    payload: RecordingSessionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_assigned_interviewer(db, interview_id, current_user)
    if (
        interview.recording_state != "recording"
        or interview.recording_session_id != payload.session_id
        or interview.recording_owner_id != current_user.id
    ):
        raise HTTPException(status_code=409, detail="Active recording ownership is required")
    try:
        session = create_realtime_session(get_transcription_config(db))
    except AsrServiceError as error:
        logger.warning(
            "Realtime ASR session creation failed",
            extra={
                "interview_id": str(interview_id),
                "provider_status": error.status_code,
            },
        )
        raise HTTPException(status_code=503, detail="实时字幕服务暂不可用") from None
    return {
        "token": session["token"],
        "expires_at": session["expires_at"],
        "ws_path": "/asr-stream",
    }


@router.post("/{interview_id}/recording/realtime-transcript")
def persist_realtime_transcript_route(
    interview_id: UUID,
    payload: RealtimeTranscriptBatchRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_assigned_interviewer(db, interview_id, current_user)
    return persist_realtime_transcript(
        db,
        interview_id,
        payload.session_id,
        [segment.model_dump(exclude_none=True) for segment in payload.segments],
        current_user,
    )


@router.post("/{interview_id}/recording/chunks/{chunk_index}")
def upload_recording_chunk_route(
    interview_id: UUID,
    chunk_index: int,
    session_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_assigned_interviewer(db, interview_id, current_user)
    stored = save_upload_file(
        file,
        interview.tenant_id,
        "interview_audio",
        resource_type="interview_recording_chunk",
        resource_id=interview.id,
    )
    return append_recording_chunk(db, interview_id, session_id, chunk_index, stored, current_user)


@router.post("/{interview_id}/end", response_model=RecordingSessionResponse)
def end_interview_route(
    interview_id: UUID,
    payload: EndInterviewRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    return _recording_response(begin_ending(db, interview_id, payload.session_id, current_user, payload.reason))


@router.post(
    "/{interview_id}/force-end",
    response_model=InterviewResponse,
    dependencies=[Depends(check_roles([UserRole.ADMIN, UserRole.HR]))],
)
def force_end_interview_route(
    interview_id: UUID,
    payload: ForceEndInterviewRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    return force_end_interview(db, interview_id, current_user, payload.reason)


@router.post("/{interview_id}/recording/seal", response_model=InterviewResponse)
def seal_recording_route(
    interview_id: UUID,
    payload: RecordingSessionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    interview = seal_recording(db, interview_id, payload.session_id, current_user)
    background_tasks.add_task(process_asr_job, interview.tenant_id, interview.id)
    return interview


@router.post("/{interview_id}/analysis/retry", response_model=InterviewResponse)
def retry_analysis_route(
    interview_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    if interview.lifecycle_state != "ended" or not (interview.audio_records or {}).get("full_interview"):
        raise HTTPException(status_code=409, detail="A sealed recording is required")
    interview.ai_analysis_status = "pending"
    interview.ai_analysis_error = None
    interview.asr_job_id = None
    interview.asr_job_status = "pending"
    interview.asr_job_attempts = 0
    interview.asr_job_next_poll_at = utcnow()
    interview.asr_job_delete_pending = False
    history = list(interview.asr_job_history or [])
    history.append({"at": utcnow().isoformat(), "status": "manual_retry"})
    interview.asr_job_history = history
    db.commit()
    background_tasks.add_task(process_asr_job, interview.tenant_id, interview.id)
    return interview


@router.post("/{interview_id}/transcript/corrections", response_model=InterviewResponse)
def correct_transcript_route(
    interview_id: UUID,
    payload: CorrectedTranscriptRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    if interview.lifecycle_state != "ended":
        raise HTTPException(status_code=409, detail="Transcript can only be corrected after the interview")
    if not payload.segments:
        raise HTTPException(status_code=422, detail="At least one corrected segment is required")
    segments = [segment.model_dump() for segment in payload.segments]
    corrected = {
        "text": " ".join(segment["text"].strip() for segment in segments if segment["text"].strip()),
        "segments": segments,
        "corrected_by": str(current_user.id),
        "corrected_at": utcnow().isoformat(),
    }
    interview.transcripts = {
        **(interview.transcripts or {}),
        "corrected_full_interview_data": corrected,
    }
    interview.ai_analysis_status = "pending"
    interview.ai_analysis_error = None
    db.commit()
    background_tasks.add_task(analyze_sealed_recording, interview.tenant_id, interview.id, True)
    return interview


@router.post("/{interview_id}/transcript/speaker-labels", response_model=InterviewDetailResponse)
def label_transcript_speakers_route(
    interview_id: UUID,
    payload: SpeakerLabelsRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_interview_access(db, interview_id, current_user)
    if interview.lifecycle_state != "ended":
        raise HTTPException(status_code=409, detail="Speakers can only be labelled after the interview")

    labels = {speaker.strip(): label.strip() for speaker, label in payload.labels.items()}
    interview.transcripts = {
        **(interview.transcripts or {}),
        "speaker_labels": labels,
    }
    db.commit()
    return interview


@router.get("/{interview_id}/notes")
def interview_notes_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_interview_access(db, interview_id, current_user)
    if interview.lifecycle_state == "ended":
        return [
            {
                "interviewer_id": str(panel.interviewer_id),
                "interviewer_name": panel.interviewer_name,
                "notes": panel.live_notes or "",
                "supplements": panel.note_supplements or [],
                "frozen_at": panel.notes_frozen_at,
            }
            for panel in interview.panels or []
        ]
    panel = panel_for_user(db, interview, current_user)
    return [{"interviewer_id": str(panel.interviewer_id), "interviewer_name": panel.interviewer_name, "notes": panel.live_notes or "", "supplements": []}]


@router.put("/{interview_id}/notes")
def save_interview_notes_route(
    interview_id: UUID,
    payload: LiveNotesRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_assigned_interviewer(db, interview_id, current_user)
    panel = save_live_notes(db, interview, current_user, payload.notes)
    return {"notes": panel.live_notes or ""}


@router.post("/{interview_id}/notes/supplements")
def add_note_supplement_route(
    interview_id: UUID,
    payload: NoteSupplementRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_assigned_interviewer(db, interview_id, current_user)
    panel = add_note_supplement(db, interview, current_user, payload.content)
    return {"supplements": panel.note_supplements or []}


@router.post("/{interview_id}/human-review", response_model=InterviewPanelResponse)
def submit_human_review_route(
    interview_id: UUID,
    payload: HumanReviewRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    interview = require_assigned_interviewer(db, interview_id, current_user)
    return submit_human_review(db, interview, current_user, payload.scores, payload.comments, payload.recommendation)


@router.post("/{interview_id}/final-decision", response_model=InterviewResponse)
def final_decision_route(
    interview_id: UUID,
    payload: FinalDecisionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    return confirm_final_decision(db, interview, current_user, payload.decision)


@router.post("/{interview_id}/final-decision/correct", response_model=InterviewResponse)
def correct_final_decision_route(
    interview_id: UUID,
    payload: FinalDecisionCorrectionRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN])),
):
    interview = require_interview_access(db, interview_id, current_user)
    return correct_final_decision(db, interview, current_user, payload.decision, payload.reason)


@router.post("/{interview_id}/cancel-notification")
def retry_cancel_notification_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    if interview.lifecycle_state != "cancelled":
        raise HTTPException(status_code=409, detail="Interview is not cancelled")
    from app.services.mail_service import get_mail_service
    return get_mail_service(db).send_interview_cancellation_for_interview(interview)


@router.post("/{interview_id}/reviewers/replace", response_model=InterviewResponse)
def replace_reviewer_route(
    interview_id: UUID,
    payload: ReviewerReplacementRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    return replace_reviewer(
        db,
        interview,
        current_user,
        payload.old_interviewer_id,
        payload.new_interviewer_id,
    )


@router.post("/{interview_id}/review-reminders")
def send_review_reminders_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    import os
    from datetime import timedelta
    from app.services.mail_service import get_mail_service

    interview = require_interview_access(db, interview_id, current_user)
    now = utcnow()
    cooldown = now - timedelta(hours=REMINDER_COOLDOWN_HOURS)
    base_url = os.getenv("APP_BASE_URL", "https://interview.careray.com").rstrip("/")
    mail = get_mail_service(db)
    sent = []
    skipped = []
    required_ids = {str(value) for value in (interview.panel_members or [])}
    for panel in interview.panels or []:
        if str(panel.interviewer_id) not in required_ids:
            continue
        if panel.human_review_submitted_at is not None:
            continue
        if panel.human_review_reminder_sent_at and as_utc(panel.human_review_reminder_sent_at) > cooldown:
            skipped.append(str(panel.interviewer_id))
            continue
        recipient = db.query(User).filter(User.id == panel.interviewer_id).first()
        if recipient and mail.send_interview_review_reminder(recipient, interview, f"{base_url}/interviews/{interview.id}/result"):
            panel.human_review_reminder_sent_at = now
            sent.append(str(panel.interviewer_id))
    db.commit()
    return {"sent": sent, "cooldown_skipped": skipped}

@router.get("/{interview_id}/export")
def export_interview_route(
    interview_id: UUID,
    format: str = "markdown",
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    content = export_interview_result(db, interview_id, format)
    if not content:
        raise HTTPException(status_code=404, detail="Interview not found")
        
    return PlainTextResponse(content=content)

@router.put(
    "/{interview_id}/questions",
    response_model=InterviewResponse,
    dependencies=[Depends(check_roles([UserRole.ADMIN, UserRole.HR]))],
)
def update_questions_route(
    interview_id: UUID,
    questions: List[dict],
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    db_interview = update_interview_questions(db, interview_id, questions)
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return db_interview

@router.post("", response_model=InterviewResponse)
def create_interview_route(
    interview: InterviewCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    return create_interview(db, interview, background_tasks)

@router.get("", response_model=List[InterviewResponse])
def get_interviews_route(
    skip: int = 0, 
    limit: int = 100, 
    status: str = None,
    range_start: Optional[datetime] = Query(default=None, alias="start"),
    range_end: Optional[datetime] = Query(default=None, alias="end"),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    if range_start and range_end and as_utc(range_end) <= as_utc(range_start):
        raise HTTPException(status_code=422, detail="日期范围结束时间必须晚于开始时间")
    # Filter for interviewers: only see interviews where they are panel members
    if current_user.role == UserRole.INTERVIEWER:
        # We need to implement a filter in get_interviews or do it here
        # Since panel_members is a JSON list of UUIDs, it's tricky to query directly in all SQL dialects efficiently without specific JSON operators.
        # But we can fetch all and filter in python for now (assuming not huge volume) or use specific query.
        # Better: Update get_interviews service to handle filtering.
        from app.services.interview_service import get_interviews_for_interviewer
        interviews = get_interviews_for_interviewer(
            db,
            current_user.id,
            skip=0,
            limit=10000,
            range_start=range_start,
            range_end=range_end,
        )
        if status:
            interviews = [i for i in interviews if str(i.status) == status or getattr(i.status, "value", None) == status]
        return interviews[skip: skip + limit]
        
    return get_interviews(
        db,
        skip=skip,
        limit=limit,
        status=status,
        range_start=range_start,
        range_end=range_end,
    )

@router.post("/email-preview")
def preview_email_before_create(
    preview_data: EmailPreviewRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """在创建面试前预览邮件内容"""
    from app.services.mail_service import get_mail_service, format_interview_time_range
    from datetime import datetime

    # 获取简历和岗位信息
    resume = db.query(Resume).filter(Resume.id == preview_data.resume_id).first()
    position = db.query(Position).filter(Position.id == preview_data.position_id).first()

    if not resume or not position:
        raise HTTPException(status_code=404, detail="简历或岗位不存在")

    require_schedule_available(
        db,
        tenant_id=resume.tenant_id,
        resume_id=resume.id,
        panel_member_ids=list(preview_data.panel_members),
        start=preview_data.interview_time,
        end=preview_data.interview_end_time,
    )

    mail_service = get_mail_service(db)

    # 面试类型中文映射
    category_map = {
        "hr": "HR面",
        "technical": "技术面",
        "manager": "主管面",
        "ceo": "CEO面",
        "comprehensive": "综合面"
    }
    interview_category_text = category_map.get(preview_data.interview_category, "面试")

    # 面试形式中文映射
    type_map = {
        "onsite": "现场面试",
        "video": "视频面试",
        "phone": "电话面试"
    }
    interview_type_text = type_map.get(preview_data.interview_type, "现场面试")

    time_str = format_interview_time_range(
        preview_data.interview_time,
        preview_data.interview_end_time,
    )

    # 渲染邮件模板
    context = {
        "candidate_name": resume.candidate_name or "候选人",
        "position_title": position.title,
        "interview_time": time_str,
        "interview_round": preview_data.round,
        "interview_category": interview_category_text,
        "interview_type": interview_type_text,
        "interview_location": preview_data.interview_location,
        "meeting_link": preview_data.meeting_link,
        "contact_person": "HR",
        "contact_phone": "",
        "company_name": "公司"
    }

    html_content = mail_service._render_template("interview_invitation.html", context)
    subject = f"面试邀请 - {position.title} 岗位"

    return {
        "to_email": resume.email,
        "candidate_name": resume.candidate_name,
        "subject": subject,
        "content": html_content
    }

@router.get("/{interview_id}", response_model=InterviewDetailResponse)
def get_interview_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    return require_interview_access(db, interview_id, current_user)

@router.post("/{interview_id}/start", response_model=InterviewResponse)
def start_interview_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    开始面试，将状态从 SCHEDULED 改为 IN_PROGRESS。
    """
    require_interview_access(db, interview_id, current_user)
    db_interview = start_interview(db, interview_id)
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return db_interview

@router.put(
    "/{interview_id}",
    response_model=InterviewResponse,
    dependencies=[Depends(check_roles([UserRole.ADMIN, UserRole.HR]))],
)
def update_interview_route(
    interview_id: UUID,
    interview: InterviewUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_interview_access(db, interview_id, current_user)
    db_interview = update_interview(db, interview_id, interview)
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return db_interview


def _schedule_notification_html(
    *,
    heading: str,
    intro: str,
    interview: Interview,
    schedule: InterviewScheduleUpdate,
    interview_url: str | None = None,
) -> str:
    from app.services.mail_service import format_interview_time_range

    candidate_name = interview.resume.candidate_name if interview.resume else "候选人"
    position_title = interview.position.title if interview.position else "岗位"
    detail = ""
    if schedule.interview_type == "onsite":
        detail = f"<li><strong>面试地点：</strong>{escape(schedule.interview_location or '')}</li>"
    elif schedule.interview_type == "video":
        detail = f"<li><strong>会议链接：</strong>{escape(schedule.meeting_link or '')}</li>"
    type_text = {"onsite": "现场面试", "video": "视频面试", "phone": "电话面试"}[schedule.interview_type]
    interview_link = (
        '<p style="margin:24px 0">'
        f'<a href="{escape(interview_url, quote=True)}" '
        'style="display:inline-block;padding:10px 18px;border-radius:6px;'
        'background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600">进入面试</a></p>'
        if interview_url
        else ""
    )
    previous_range = format_interview_time_range(interview.interview_time, interview.interview_end_time)
    proposed_range = format_interview_time_range(schedule.interview_time, schedule.interview_end_time)
    time_detail = (
        f"<li><strong>原面试时间：</strong>{escape(previous_range)}</li>"
        f"<li><strong>新面试时间：</strong>{escape(proposed_range)}</li>"
        if previous_range != proposed_range
        else f"<li><strong>面试时间：</strong>{escape(proposed_range)}</li>"
    )
    return (
        '<div style="font-family:Arial,sans-serif;line-height:1.7;color:#1f2937">'
        f"<h2>{escape(heading)}</h2><p>{escape(intro)}</p><ul>"
        f"<li><strong>候选人：</strong>{escape(candidate_name or '候选人')}</li>"
        f"<li><strong>应聘岗位：</strong>{escape(position_title or '岗位')}</li>"
        f"<li><strong>面试轮次：</strong>第 {interview.round or 1} 轮</li>"
        f"{time_detail}"
        f"<li><strong>面试形式：</strong>{type_text}</li>{detail}</ul>"
        f"{interview_link}<p>如有疑问，请联系招聘负责人。</p></div>"
    )


@router.post("/{interview_id}/schedule-email-preview")
def preview_schedule_update_email(
    interview_id: UUID,
    schedule: InterviewScheduleUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if interview.lifecycle_state != "scheduled" or interview.status != InterviewStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="只能修改尚未开始的面试安排")

    proposed_ids = set(schedule.panel_members)
    old_ids = {UUID(str(value)) for value in (interview.panel_members or [])}
    relevant_ids = proposed_ids | old_ids
    users = db.query(User).filter(
        User.id.in_(relevant_ids),
        User.is_active == True,
        User.role.in_([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]),
    ).all()
    users_by_id = {user.id: user for user in users}
    if any(member_id not in users_by_id for member_id in proposed_ids):
        raise HTTPException(status_code=422, detail="面试官不存在、已停用或不可分配")

    require_schedule_available(
        db,
        tenant_id=interview.tenant_id,
        resume_id=interview.resume_id,
        panel_member_ids=list(schedule.panel_members),
        start=schedule.interview_time,
        end=schedule.interview_end_time,
        exclude_interview_id=interview.id,
    )

    previous_time = as_utc(interview.interview_time) if interview.interview_time else None
    previous_end_time = as_utc(interview.interview_end_time) if interview.interview_end_time else None
    proposed_time = as_utc(schedule.interview_time)
    proposed_end_time = as_utc(schedule.interview_end_time)
    schedule_changed = any([
        previous_time != proposed_time,
        previous_end_time != proposed_end_time,
        interview.interview_type != schedule.interview_type,
        (interview.interview_location or "") != (schedule.interview_location or ""),
        (interview.meeting_link or "") != (schedule.meeting_link or ""),
    ])
    current_recipient_ids = proposed_ids if schedule_changed else proposed_ids - old_ids
    removed_recipient_ids = old_ids - proposed_ids

    import os
    from app.services.system_config_service import get_system_config
    system_config = get_system_config(db)
    frontend_url = (
        (system_config.frontend_url if system_config else None)
        or os.getenv("APP_BASE_URL")
        or "https://interview.careray.com"
    ).rstrip("/")
    interview_url = f"{frontend_url}/interviews/{interview.id}/score"

    def recipients(ids):
        return [
            {
                "id": str(user.id),
                "name": user.full_name or user.email,
                "email": user.email,
            }
            for user in users
            if user.id in ids
        ]

    position_title = interview.position.title if interview.position else "岗位"
    return {
        "notification_token": issue_schedule_notification_token(
            interview,
            schedule,
            relevant_ids,
        ),
        "current": {
            "recipients": recipients(current_recipient_ids),
            "subject": f"面试安排更新 - {position_title}",
            "content": _schedule_notification_html(
                heading="面试安排更新",
                intro="您被安排参与以下面试，请查收最新安排。",
                interview=interview,
                schedule=schedule,
                interview_url=interview_url,
            ),
            "default_enabled": bool(current_recipient_ids),
        },
        "removed": {
            "recipients": recipients(removed_recipient_ids),
            "subject": f"面试安排变更 - {position_title}",
            "content": _schedule_notification_html(
                heading="面试安排变更",
                intro="您已不再参与以下面试，无需继续准备或出席。",
                interview=interview,
                schedule=schedule,
            ),
            "default_enabled": bool(removed_recipient_ids),
        },
    }


@router.put("/{interview_id}/schedule")
def update_interview_schedule_route(
    interview_id: UUID,
    schedule: InterviewScheduleUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    updated = update_interview_schedule(db, interview_id, schedule)
    if not updated:
        raise HTTPException(status_code=404, detail="Interview not found")
    return InterviewResponse.model_validate(updated)


@router.post("/{interview_id}/schedule-notifications")
def send_interview_schedule_notifications(
    interview_id: UUID,
    notification: InterviewScheduleNotificationRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    interview = require_interview_access(db, interview_id, current_user)
    validate_schedule_notification_token(
        notification.preview_token,
        interview,
        notification.recipient_ids,
    )
    recipients = db.query(User).filter(
        User.id.in_(notification.recipient_ids),
        User.is_active == True,
        User.role.in_([UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]),
    ).all()
    recipients_by_id = {user.id: user for user in recipients}
    from app.services.mail_service import get_mail_service
    mail_service = get_mail_service(db)
    sent = []
    failed = []
    for recipient_id in notification.recipient_ids:
        recipient = recipients_by_id.get(recipient_id)
        if recipient and recipient.email and mail_service._send_email(
            recipient.email,
            notification.subject.strip(),
            notification.content,
        ):
            sent.append(str(recipient_id))
        else:
            failed.append(str(recipient_id))
    return {"sent": sent, "failed": failed}

@router.post("/{interview_id}/score", response_model=InterviewResponse)
def submit_score_route(
    interview_id: UUID, 
    score_data: InterviewScore, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    require_interview_assignment(db, interview_id, current_user)
    db_interview = submit_interview_score(
        db,
        interview_id,
        current_user.id,
        score_data,
        background_tasks,
        actor=current_user,
    )
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return db_interview

from fastapi import UploadFile, File
from app.services.audio_service import get_transcription_config, transcribe_audio
from app.config.tenant_session import get_tenant_id
from app.utils.file_storage import (
    UPLOAD_ROOT, cleanup_new_file, commit_file_replacement, save_upload_file,
    stored_file_path, tenant_files_from_urls,
)

# ...

@router.post("/{interview_id}/audio/{question_index}")
def upload_audio_route(
    interview_id: UUID,
    question_index: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Upload, transcribe and atomically replace one question recording."""
    interview = require_interview_access(db, interview_id, current_user)
    from app.models.models import InterviewPanel
    panel = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview_id,
        InterviewPanel.interviewer_id == current_user.id
    ).first()
    record_owner = panel if panel is not None else interview
    tenant_id = get_tenant_id(db)
    old_files = tenant_files_from_urls(
        db, tenant_id, "interview", interview_id, "interview_audio",
        [(record_owner.audio_records or {}).get(question_index)],
    )
    stored = None
    try:
        stored = save_upload_file(
            file, tenant_id, "interview_audio",
            resource_type="interview", resource_id=interview_id,
        )
        db.add(stored)
        transcript_data = transcribe_audio(
            str(stored_file_path(stored)),
            config=get_transcription_config(db),
        )
        transcript = transcript_data.get("text", "") if isinstance(transcript_data, dict) else str(transcript_data)
        audio_records = dict(record_owner.audio_records or {})
        transcripts = dict(record_owner.transcripts or {})
        audio_records[question_index] = f"/api/files/{stored.id}"
        transcripts[question_index] = transcript
        record_owner.audio_records = audio_records
        record_owner.transcripts = transcripts
        commit_file_replacement(db, stored, old_files, root=UPLOAD_ROOT)
    except Exception:
        if stored is not None:
            cleanup_new_file(db, stored, root=UPLOAD_ROOT)
        else:
            db.rollback()
        logger.warning("Interview audio upload failed", extra={"resource_id": str(interview_id)})
        raise HTTPException(status_code=500, detail="Audio upload failed") from None
    db.refresh(record_owner)
    return {"transcript": transcript, "file_id": str(stored.id), "download_url": f"/api/files/{stored.id}"}

@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview_route(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN]))
):
    db_interview = delete_interview(db, interview_id)
    if not db_interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{interview_id}/email-preview")
def get_email_preview(
    interview_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """获取面试邀请邮件预览"""
    from app.services.mail_service import get_mail_service, format_interview_time_range

    interview = require_interview_access(db, interview_id, current_user)

    mail_service = get_mail_service(db)

    # 获取候选人信息
    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    position = db.query(Position).filter(Position.id == interview.position_id).first()

    if not resume or not position:
        raise HTTPException(status_code=404, detail="Resume or position not found")

    # 从 comments 中获取面试类型和地点信息
    comments = interview.comments or {}
    interview_type = comments.get("interview_type", "onsite")
    interview_category = comments.get("interview_category", "technical")
    interview_location = comments.get("interview_location")
    meeting_link = comments.get("meeting_link")

    # 面试类型中文映射
    category_map = {
        "hr": "HR面",
        "technical": "技术面",
        "manager": "主管面",
        "ceo": "CEO面",
        "comprehensive": "综合面"
    }
    interview_category_text = category_map.get(interview_category, "面试")

    # 面试形式中文映射
    type_map = {
        "onsite": "现场面试",
        "video": "视频面试",
        "phone": "电话面试"
    }
    interview_type_text = type_map.get(interview_type, "现场面试")

    # 格式化面试时间
    time_str = format_interview_time_range(interview.interview_time, interview.interview_end_time)

    # 渲染邮件模板
    context = {
        "candidate_name": resume.candidate_name or "候选人",
        "position_title": position.title,
        "interview_time": time_str,
        "interview_round": interview.round or 1,
        "interview_category": interview_category_text,
        "interview_type": interview_type_text,
        "interview_location": interview_location,
        "meeting_link": meeting_link,
        "contact_person": "HR",
        "contact_phone": "",
        "company_name": "公司"
    }

    html_content = mail_service._render_template("interview_invitation.html", context)
    subject = f"面试邀请 - {position.title} 岗位"

    return {
        "to_email": resume.email,
        "candidate_name": resume.candidate_name,
        "subject": subject,
        "content": html_content
    }


@router.post("/{interview_id}/send-email")
def send_interview_email(
    interview_id: UUID,
    email_data: EmailSendRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """发送面试邀请邮件"""
    from app.services.mail_service import get_mail_service

    interview = require_interview_access(db, interview_id, current_user)

    mail_service = get_mail_service(db)

    # 获取候选人邮箱
    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    if not resume or not resume.email:
        raise HTTPException(status_code=400, detail="候选人邮箱为空")

    # 发送邮件
    success = mail_service._send_email(
        to_email=resume.email,
        subject=email_data.subject,
        html_content=email_data.content
    )

    if success:
        return {"message": "邮件发送成功"}
    else:
        raise HTTPException(status_code=500, detail="邮件发送失败")


class DirectEvaluationRequest(BaseModel):
    evaluation: str
    suggestion: Optional[str] = None
    score: int = 5
    transcript: Optional[str] = None  # 可选的录音转写内容


@router.post("/{interview_id}/full-audio")
def upload_full_interview_audio(
    interview_id: UUID,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """上传整场面试录音并进行AI分析"""
    from app.services.audio_service import (
        format_transcript_for_display,
        get_transcription_config,
        transcribe_audio,
    )

    interview = require_interview_access(db, interview_id, current_user)

    tenant_id = get_tenant_id(db)
    old_files = tenant_files_from_urls(
        db, tenant_id, "interview", interview_id, "interview_audio",
        [(interview.audio_records or {}).get("full_interview")],
    )
    stored = None
    try:
        stored = save_upload_file(
            file, tenant_id, "interview_audio",
            resource_type="interview", resource_id=interview_id,
        )
        db.add(stored)
        transcript_data = transcribe_audio(
            str(stored_file_path(stored)),
            config=get_transcription_config(db),
        )
        transcript_text = transcript_data.get("text", "")
        formatted_transcript = format_transcript_for_display(transcript_data)
        interview.audio_records = {"full_interview": f"/api/files/{stored.id}"}
        interview.transcripts = {
            **(interview.transcripts or {}),
            "full_interview": transcript_text,
            "full_interview_data": transcript_data,
        }
        commit_file_replacement(db, stored, old_files, root=UPLOAD_ROOT)
    except Exception:
        if stored is not None:
            cleanup_new_file(db, stored, root=UPLOAD_ROOT)
        else:
            db.rollback()
        logger.warning("Full interview audio upload failed", extra={"resource_id": str(interview_id)})
        raise HTTPException(status_code=500, detail="Audio upload failed") from None

    if transcript_text and background_tasks:
        background_tasks.add_task(
            generate_evaluation_from_transcript,
            interview.tenant_id,
            interview_id,
            transcript_text
        )

    return {
        "message": "上传成功",
        "transcript": transcript_text,
        "formatted_transcript": formatted_transcript,
        "segments": transcript_data.get("segments", [])
    }


@router.post("/{interview_id}/direct-evaluation")
def submit_direct_evaluation(
    interview_id: UUID,
    evaluation_data: DirectEvaluationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """直接提交面试评价（无需面试题），支持结合录音转写内容"""
    interview = require_interview_assignment(db, interview_id, current_user)

    transcripts = interview.transcripts or {}
    full_transcript_data = transcripts.get("full_interview", "")
    # 处理 transcript 可能是对象或字符串的情况
    if isinstance(full_transcript_data, dict):
        full_transcript = full_transcript_data.get("text", "")
    else:
        full_transcript = full_transcript_data or evaluation_data.transcript

    panel_members = interview.panel_members or []
    is_multi_interviewer = len(panel_members) > 1

    if is_multi_interviewer:
        panel = db.query(InterviewPanel).filter(
            InterviewPanel.interview_id == interview_id,
            InterviewPanel.interviewer_id == current_user.id
        ).first()

        if panel is None:
            panel = InterviewPanel(
                tenant_id=interview.tenant_id,
                interview_id=interview_id,
                interviewer_id=current_user.id,
            )
            db.add(panel)
        panel.scores = {"overall": evaluation_data.score}
        panel.comments = {"overall": evaluation_data.evaluation}
        panel.total_score = evaluation_data.score
        panel.is_submitted = True
        db.commit()
        db.refresh(panel)
        
        submitted_panels = db.query(InterviewPanel).filter(
            InterviewPanel.interview_id == interview_id,
            InterviewPanel.is_submitted == True
        ).all()
        
        submitted_ids = [str(p.interviewer_id) for p in submitted_panels]
        required_ids = [str(uid) for uid in panel_members]
        
        print(f"[Direct Eval] Submitted IDs: {submitted_ids}")
        print(f"[Direct Eval] Required IDs: {required_ids}")
        
        all_submitted = all(uid in submitted_ids for uid in required_ids)
        print(f"[Direct Eval] All submitted: {all_submitted}")
        
        if all_submitted:
            interview.status = InterviewStatus.ANALYZING
            interview.result = InterviewResult.PENDING
            mark_legacy_interview_ended(interview)
            
            all_evaluations = []
            for p in submitted_panels:
                interviewer_name = p.interviewer_user.full_name if p.interviewer_user else str(p.interviewer_id)
                all_evaluations.append(f"**{interviewer_name}**: {p.comments.get('overall', '')} (评分: {p.total_score})")
            
            combined_evaluation = "\n\n".join(all_evaluations)
            avg_score = sum(p.total_score or 0 for p in submitted_panels) // len(submitted_panels)
            
            interview.evaluation = combined_evaluation
            interview.suggestion = "综合多位面试官评价"
            interview.total_score = avg_score
            interview.scores = {"overall": avg_score}
            interview.comments = {"overall": combined_evaluation}
            
            db.commit()
            db.refresh(interview)
            
            if full_transcript:
                background_tasks.add_task(
                    generate_combined_evaluation,
                    interview.tenant_id,
                    interview_id,
                    full_transcript,
                    combined_evaluation,
                    "综合多位面试官评价",
                    avg_score
                )
            else:
                mark_legacy_interview_completed(interview)
                db.commit()
                db.refresh(interview)
        else:
            interview.result = InterviewResult.PENDING
            db.commit()
            db.refresh(interview)
    else:
        interview.evaluation = evaluation_data.evaluation
        interview.suggestion = evaluation_data.suggestion
        interview.total_score = evaluation_data.score
        interview.scores = {"overall": evaluation_data.score}
        interview.comments = {"overall": evaluation_data.evaluation}

        if full_transcript:
            interview.status = InterviewStatus.ANALYZING
            interview.result = InterviewResult.PENDING
            mark_legacy_interview_ended(interview)
            background_tasks.add_task(
                generate_combined_evaluation,
                interview.tenant_id,
                interview_id,
                full_transcript,
                evaluation_data.evaluation,
                evaluation_data.suggestion,
                evaluation_data.score
            )
        else:
            interview.result = InterviewResult.PENDING
            mark_legacy_interview_completed(interview)

        db.commit()
        db.refresh(interview)

    return interview


@router.post("/{interview_id}/direct-evaluation-with-audio")
def submit_direct_evaluation_with_audio(
    interview_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    evaluation: str = Form(...),
    suggestion: str = Form(None),
    score: int = Form(5),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """同时上传录音和评价，AI综合分析生成最终评价"""
    from app.services.audio_service import get_transcription_config, transcribe_audio

    interview = require_interview_assignment(db, interview_id, current_user)

    tenant_id = get_tenant_id(db)
    old_files = tenant_files_from_urls(
        db, tenant_id, "interview", interview_id, "interview_audio",
        [(interview.audio_records or {}).get("full_interview")],
    )
    stored = None
    background_payload = None
    try:
        stored = save_upload_file(
            file, tenant_id, "interview_audio",
            resource_type="interview", resource_id=interview_id,
        )
        db.add(stored)
        transcript_data = transcribe_audio(
            str(stored_file_path(stored)),
            config=get_transcription_config(db),
        )
        transcript = transcript_data.get("text", "") if isinstance(transcript_data, dict) else str(transcript_data)
        interview.audio_records = {"full_interview": f"/api/files/{stored.id}"}
        interview.transcripts = {
            **(interview.transcripts or {}),
            "full_interview": transcript,
            "full_interview_data": transcript_data,
        }

        panel_members = interview.panel_members or []
        if len(panel_members) > 1:
            panel = db.query(InterviewPanel).filter(
                InterviewPanel.interview_id == interview_id,
                InterviewPanel.interviewer_id == current_user.id,
            ).first()
            if panel is None:
                panel = InterviewPanel(
                    tenant_id=interview.tenant_id,
                    interview_id=interview_id,
                    interviewer_id=current_user.id,
                )
                db.add(panel)
            panel.scores = {"overall": score}
            panel.comments = {"overall": evaluation}
            panel.total_score = score
            panel.is_submitted = True
            submitted_panels = db.query(InterviewPanel).filter(
                InterviewPanel.interview_id == interview_id,
                InterviewPanel.is_submitted == True,
            ).all()
            submitted_ids = {str(item.interviewer_id) for item in submitted_panels}
            if all(str(uid) in submitted_ids for uid in panel_members):
                all_evaluations = []
                for item in submitted_panels:
                    name = item.interviewer_user.full_name if item.interviewer_user else str(item.interviewer_id)
                    all_evaluations.append(
                        f"**{name}**: {item.comments.get('overall', '')} (评分: {item.total_score})"
                    )
                combined = "\n\n".join(all_evaluations)
                average = sum(item.total_score or 0 for item in submitted_panels) // len(submitted_panels)
                interview.result = InterviewResult.PENDING
                interview.evaluation = combined
                interview.suggestion = "综合多位面试官评价"
                interview.total_score = average
                interview.scores = {"overall": average}
                interview.comments = {"overall": combined}
                if transcript:
                    interview.status = InterviewStatus.ANALYZING
                    mark_legacy_interview_ended(interview)
                    background_payload = (transcript, combined, "综合多位面试官评价", average)
                else:
                    mark_legacy_interview_completed(interview)
            else:
                interview.result = InterviewResult.PENDING
        else:
            interview.evaluation = evaluation
            interview.suggestion = suggestion
            interview.total_score = score
            interview.scores = {"overall": score}
            interview.comments = {"overall": evaluation}
            if transcript:
                interview.status = InterviewStatus.ANALYZING
                mark_legacy_interview_ended(interview)
                background_payload = (transcript, evaluation, suggestion, score)
            else:
                mark_legacy_interview_completed(interview)
            interview.result = InterviewResult.PENDING
        commit_file_replacement(db, stored, old_files, root=UPLOAD_ROOT)
    except Exception:
        if stored is not None:
            cleanup_new_file(db, stored, root=UPLOAD_ROOT)
        else:
            db.rollback()
        logger.warning("Direct evaluation audio upload failed", extra={"resource_id": str(interview_id)})
        raise HTTPException(status_code=500, detail="Audio upload failed") from None

    db.refresh(interview)
    if background_payload:
        background_tasks.add_task(
            generate_combined_evaluation,
            interview.tenant_id,
            interview_id,
            *background_payload,
        )
    return interview


@background_task_context
def generate_evaluation_from_transcript(tenant_id: UUID, interview_id: UUID, transcript: str):
    """根据转写内容生成评价（后台任务）"""
    generate_combined_evaluation(tenant_id, interview_id, transcript, None, None, None)


@background_task_context
def generate_combined_evaluation(
    tenant_id: UUID,
    interview_id: UUID,
    transcript: str,
    interviewer_evaluation: str = None,
    interviewer_suggestion: str = None,
    interviewer_score: int = None
):
    """根据录音转写和面试官评价综合生成评价（后台任务）"""
    from app.services.ai_service import generate_text
    from app.models.models import Interview as InterviewModel, Resume, Position

    with tenant_session(tenant_id) as db:
        interview = db.query(InterviewModel).filter(InterviewModel.id == interview_id).first()
        if not interview:
            return

        # 获取简历和岗位信息
        resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
        position = db.query(Position).filter(Position.id == interview.position_id).first()

        # 构建提示词
        if interviewer_evaluation:
            # 有面试官评价，结合录音分析
            prompt = f"""请根据面试录音转写内容和面试官的评价，生成一份综合面试评价报告。

候选人：{resume.candidate_name if resume else '未知'}
应聘岗位：{position.title if position else '未知'}

## 面试录音转写内容：
{transcript}

## 面试官填写的评价：
{interviewer_evaluation}

## 面试官的录用建议：
{interviewer_suggestion or '无'}

## 面试官评分：{interviewer_score or '未打分'}分

请结合以上信息，生成一份综合评价报告，要求：
1. 总结面试录音中的关键信息（技术能力、项目经验、沟通能力等）
2. 分析面试官评价的准确性，如有出入请指出
3. 给出最终的综合评价和录用建议
4. 格式清晰，使用Markdown格式"""
        else:
            # 只有录音，没有面试官评价
            prompt = f"""请根据以下面试录音转写内容，对候选人进行综合评价。

候选人：{resume.candidate_name if resume else '未知'}
应聘岗位：{position.title if position else '未知'}

面试录音转写内容：
{transcript}

请从以下几个方面进行评价：
1. 技术能力评估
2. 沟通表达能力
3. 项目经验分析
4. 综合素质评价
5. 录用建议

请用中文回答，格式清晰。"""

        # 调用AI生成评价
        evaluation = generate_text(prompt, db=db)

        if evaluation:
            interview.evaluation = evaluation
            interview.result = InterviewResult.PENDING
            mark_legacy_interview_completed(interview)

            # 如果有面试官评分，保留
            if interviewer_score:
                interview.total_score = interviewer_score
                interview.scores = {"overall": interviewer_score}

            # 保存综合建议
            if interviewer_suggestion:
                interview.suggestion = interviewer_suggestion

            db.commit()
