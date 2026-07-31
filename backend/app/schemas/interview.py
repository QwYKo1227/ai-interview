from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional, List, Dict, Any, Union, Literal
from uuid import UUID
from datetime import datetime
from app.models.models import InterviewStatus, InterviewResult
from app.schemas.resume import ResumeResponse
from app.schemas.position import PositionResponse

class InterviewBase(BaseModel):
    resume_id: UUID
    position_id: UUID
    interviewer: Optional[str] = None
    interview_time: Optional[datetime] = None
    panel_members: Optional[List[str]] = [] # List of user IDs for the panel (strings or UUIDs)
    round: Optional[int] = 1
    interview_type: Optional[str] = 'onsite'  # onsite, video, phone - 面试形式
    interview_category: Optional[str] = 'technical'  # hr, technical, manager, ceo, comprehensive - 面试类型
    interview_location: Optional[str] = None
    meeting_link: Optional[str] = None

class InterviewCreate(InterviewBase):
    interview_time: datetime
    question_bank_ids: Optional[List[UUID]] = []
    question_count: Optional[int] = 5
    skip_ai_questions: Optional[bool] = False
    skip_email: Optional[bool] = False

    @model_validator(mode="after")
    def validate_scheduling_details(self):
        if self.interview_type == "onsite" and not (self.interview_location or "").strip():
            raise ValueError("现场面试必须填写面试地点")
        if self.interview_type == "video" and not (self.meeting_link or "").strip():
            raise ValueError("视频面试必须填写会议链接")
        return self

class InterviewUpdate(BaseModel):
    interviewer: Optional[str] = None
    interview_time: Optional[datetime] = None
    status: Optional[InterviewStatus] = None
    result: Optional[InterviewResult] = None
    evaluation: Optional[str] = None
    suggestion: Optional[str] = None


class InterviewScheduleUpdate(BaseModel):
    panel_members: List[UUID] = Field(min_length=1)
    interview_time: datetime
    interview_type: Literal["onsite", "video", "phone"]
    interview_location: Optional[str] = None
    meeting_link: Optional[str] = None

    @model_validator(mode="after")
    def validate_scheduling_details(self):
        if len(set(self.panel_members)) != len(self.panel_members):
            raise ValueError("面试官不能重复")
        if self.interview_type == "onsite" and not (self.interview_location or "").strip():
            raise ValueError("现场面试必须填写面试地点")
        if self.interview_type == "video" and not (self.meeting_link or "").strip():
            raise ValueError("视频面试必须填写会议链接")
        return self


class InterviewScheduleNotificationRequest(BaseModel):
    recipient_ids: List[UUID] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)

class InterviewScore(BaseModel):
    scores: Dict[str, int] # 题目索引 -> 分数
    comments: Optional[Dict[str, str]] = {} # 题目索引 -> 评语
    
class InterviewPanelResponse(BaseModel):
    id: UUID
    interviewer_id: UUID
    interviewer_name: Optional[str] = None
    scores: Optional[Dict[str, Any]] = None
    comments: Optional[Dict[str, Any]] = None
    total_score: Optional[int] = None
    is_submitted: bool
    notes_frozen_at: Optional[datetime] = None
    human_scores: Optional[Dict[str, int]] = None
    human_comments: Optional[str] = None
    human_recommendation: Optional[str] = None
    human_review_submitted_at: Optional[datetime] = None
    human_review_updated_at: Optional[datetime] = None
    human_review_reminder_sent_at: Optional[datetime] = None
    
    # Custom field to indicate main interview status
    interview_status: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class InterviewResponse(InterviewBase):
    id: UUID
    questions: Optional[List[Dict[str, Any]]] = None
    scores: Optional[Dict[str, Any]] = None
    comments: Optional[Dict[str, Any]] = None
    total_score: Optional[int] = None
    result: InterviewResult
    evaluation: Optional[str] = None
    suggestion: Optional[str] = None
    status: InterviewStatus
    started_at: Optional[datetime] = None
    lifecycle_state: str = "scheduled"
    ended_at: Optional[datetime] = None
    end_reason: Optional[str] = None
    recording_session_id: Optional[UUID] = None
    recording_owner_id: Optional[UUID] = None
    recording_state: str = "idle"
    recording_reservation_expires_at: Optional[datetime] = None
    recording_heartbeat_at: Optional[datetime] = None
    ai_analysis_status: str = "pending"
    ai_analysis: Optional[Dict[str, Any]] = None
    ai_analysis_error: Optional[str] = None
    ai_analysis_version: int = 0
    ai_analysis_started_at: Optional[datetime] = None
    ai_analysis_completed_at: Optional[datetime] = None
    asr_job_status: str = "pending"
    asr_job_attempts: int = 0
    final_decision_by: Optional[UUID] = None
    final_decision_at: Optional[datetime] = None
    decision_history: List[Dict[str, Any]] = Field(default_factory=list)
    cancel_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    notes_revealed_at: Optional[datetime] = None
    created_at: datetime
    resume: Optional[ResumeResponse] = None
    position: Optional[PositionResponse] = None
    panels: Optional[List[InterviewPanelResponse]] = []

    model_config = ConfigDict(from_attributes=True)


class InterviewDetailResponse(InterviewResponse):
    transcripts: Optional[Dict[str, Any]] = None


class RecordingSessionResponse(BaseModel):
    session_id: UUID
    owner_id: UUID
    recording_state: str
    lifecycle_state: str
    reservation_expires_at: Optional[datetime] = None
    next_chunk_index: int = 0


class RecordingSessionRequest(BaseModel):
    session_id: UUID


class EndInterviewRequest(RecordingSessionRequest):
    reason: Optional[str] = None


class ForceEndInterviewRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("强制结束原因不能为空")
        return self


class LiveNotesRequest(BaseModel):
    notes: str = ""


class NoteSupplementRequest(BaseModel):
    content: str


class HumanReviewRequest(BaseModel):
    scores: Dict[str, int] = Field(default_factory=dict)
    comments: str = ""
    recommendation: str


class FinalDecisionRequest(BaseModel):
    decision: str


class FinalDecisionCorrectionRequest(FinalDecisionRequest):
    reason: str = Field(min_length=1, max_length=500)


class CancelInterviewResponse(InterviewResponse):
    notification_sent: bool = False
    notification_errors: List[str] = Field(default_factory=list)


class ReviewerReplacementRequest(BaseModel):
    old_interviewer_id: UUID
    new_interviewer_id: UUID


class CorrectedTranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[Union[str, int]] = None


class CorrectedTranscriptRequest(BaseModel):
    segments: List[CorrectedTranscriptSegment]


class SpeakerLabelsRequest(BaseModel):
    labels: Dict[str, str]

    @model_validator(mode="after")
    def validate_labels(self):
        if len(self.labels) > 20:
            raise ValueError("At most 20 speaker labels are allowed")
        for speaker, label in self.labels.items():
            if not speaker.strip() or len(speaker) > 100:
                raise ValueError("Speaker identifiers must be 1-100 characters")
            if not label.strip() or len(label.strip()) > 100:
                raise ValueError("Speaker labels must be 1-100 characters")
        return self
