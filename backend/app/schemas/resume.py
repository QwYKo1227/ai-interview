from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from app.models.models import ResumeStatus, ScreeningResult, RejectReasonCategory, ReviewRecommendation
from app.schemas.position import PositionResponse
import re

def _validate_reject_reason_category(v):
    if v is None:
        return None
    if isinstance(v, RejectReasonCategory):
        return v
    if isinstance(v, str):
        try:
            return RejectReasonCategory(v)
        except ValueError:
            valid_values = [e.value for e in RejectReasonCategory]
            raise ValueError(f"无效的淘汰原因，有效值为: {valid_values}")
    return v

def _normalize_email(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            return None
    return v

class ResumeBase(BaseModel):
    candidate_name: Optional[str] = None
    contact: Optional[str] = None
    email: Optional[str] = None
    position_id: UUID

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return _normalize_email(v)
    
class ResumeCreate(ResumeBase):
    pass

class ResumeUpdate(BaseModel):
    screening_result: Optional[ScreeningResult] = None
    hr_review: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[ResumeStatus] = None
    candidate_name: Optional[str] = None
    contact: Optional[str] = None
    email: Optional[str] = None
    highest_degree: Optional[str] = None
    school: Optional[str] = None
    major: Optional[str] = None
    years_of_experience: Optional[str] = None
    recent_company: Optional[str] = None
    stage: Optional[str] = None
    # 淘汰相关字段
    reject_reason_category: Optional[RejectReasonCategory] = None
    reject_reason_detail: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return _normalize_email(v)

    @field_validator("years_of_experience", mode="before")
    @classmethod
    def normalize_years_of_experience(cls, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        return v

    @field_validator("hr_review", mode="before")
    @classmethod
    def normalize_hr_review(cls, v):
        if not isinstance(v, str):
            return v
        normalized = v.strip()
        return normalized or None

class ResumeResponse(ResumeBase):
    id: UUID
    file_path: Optional[str] = None
    file_id: Optional[UUID] = None
    parsed_data: Optional[Dict[str, Any]] = None
    match_score: Optional[int] = None
    parse_status: Optional[str] = None
    parse_error: Optional[str] = None
    parsed_at: Optional[datetime] = None
    screening_result: ScreeningResult
    ai_review: Optional[str] = None
    hr_review: Optional[str] = None
    status: ResumeStatus
    stage: Optional[str] = "new"
    # 其他岗位匹配信息
    other_position_matches: Optional[List[Dict[str, Any]]] = None
    # 淘汰相关字段
    reject_reason_category: Optional[RejectReasonCategory] = None
    reject_reason_detail: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[UUID] = None
    created_at: datetime
    position: Optional[PositionResponse] = None
    department_reviews: Optional[List["DepartmentReviewResponse"]] = None
    duplicate_resume_count: int = 1

    model_config = ConfigDict(from_attributes=True)


class DuplicateResumeSummary(BaseModel):
    id: UUID
    candidate_name: Optional[str] = None
    position_id: UUID
    position: Optional[PositionResponse] = None
    status: ResumeStatus
    match_score: Optional[int] = None
    parse_status: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# 部门评审相关 Schema
class DepartmentReviewBase(BaseModel):
    technical_score: Optional[int] = None  # 技术评分 1-10
    experience_score: Optional[int] = None  # 经验评分 1-10
    overall_score: Optional[int] = None  # 综合评分 1-10
    recommendation: Optional[ReviewRecommendation] = None
    comment: Optional[str] = None


class DepartmentReviewCreate(DepartmentReviewBase):
    pass


class DepartmentReviewUpdate(BaseModel):
    technical_score: Optional[int] = None
    experience_score: Optional[int] = None
    overall_score: Optional[int] = None
    recommendation: Optional[ReviewRecommendation] = None
    comment: Optional[str] = None


class PublicDepartmentReviewSubmit(BaseModel):
    technical_score: Optional[int] = Field(default=None, ge=1, le=10)
    experience_score: Optional[int] = Field(default=None, ge=1, le=10)
    overall_score: Optional[int] = Field(default=None, ge=1, le=10)
    recommendation: ReviewRecommendation
    comment: Optional[str] = Field(default=None, max_length=5000)


class DepartmentReviewResponse(DepartmentReviewBase):
    id: UUID
    resume_id: UUID
    reviewer_id: UUID
    reviewed_position_id: Optional[UUID] = None
    reviewed_position_title: Optional[str] = None
    is_completed: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_reminded_at: Optional[datetime] = None
    reviewer_name: Optional[str] = None  # 评审人姓名

    public_token: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AssignedDepartmentReviewResponse(BaseModel):
    review_id: UUID
    resume_id: UUID
    candidate_name: Optional[str] = None
    position_title: Optional[str] = None
    match_score: Optional[int] = None
    status: ResumeStatus
    is_completed: bool
    overall_score: Optional[int] = None
    recommendation: Optional[ReviewRecommendation] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class AssignedDepartmentReviewListResponse(BaseModel):
    items: List[AssignedDepartmentReviewResponse]
    total: int
    pending_total: int
    completed_total: int
    page: int
    page_size: int
    total_pages: int


class DepartmentReviewLinkResponse(BaseModel):
    public_token: str


class DepartmentReviewEmailPreviewRequest(BaseModel):
    public_token: str = Field(min_length=40, max_length=128)
    review_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_review_url(self):
        expected_path = f"/public/review/{self.public_token}"
        if (
            self.review_url.path != expected_path
            or self.review_url.query is not None
            or self.review_url.fragment is not None
        ):
            raise ValueError("评审链接与评审令牌不匹配")
        return self


class DepartmentReviewEmailPreviewResponse(BaseModel):
    review_id: UUID
    to_email: str
    reviewer_name: str
    candidate_name: Optional[str] = None
    subject: str
    content: str


class DepartmentReviewEmailSendRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)


# HR决策相关 Schema
class HRDecisionCreate(BaseModel):
    hr_id: UUID = Field(
        ...,
        deprecated=True,
        description="Deprecated: ignored; the authenticated user is used instead.",
    )
    decision: ResumeStatus  # REJECTED, WAITLIST, PENDING_INTERVIEW 等
    reject_reason_category: Optional[RejectReasonCategory] = None
    reject_reason_detail: Optional[str] = None
    hr_comment: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("reject_reason_category", mode="before")
    @classmethod
    def validate_reject_reason(cls, v):
        return _validate_reject_reason_category(v)

    @field_validator("hr_comment", mode="before")
    @classmethod
    def normalize_hr_comment(cls, v):
        if not isinstance(v, str):
            return v
        normalized = v.strip()
        return normalized or None


class HRDecisionResponse(BaseModel):
    resume_id: UUID
    decision: ResumeStatus
    reject_reason_category: Optional[RejectReasonCategory] = None
    reject_reason_detail: Optional[str] = None
    hr_comment: Optional[str] = None
    decided_at: datetime

    model_config = ConfigDict(from_attributes=True)


# 简历查重检查
class DuplicateCheckRequest(BaseModel):
    email: Optional[str] = None
    contact: Optional[str] = None
    position_id: UUID

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return _normalize_email(v)


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    existing_resume: Optional[ResumeResponse] = None
    message: Optional[str] = None


# 部门评审聚合报告
class DepartmentReviewSummary(BaseModel):
    resume_id: UUID
    total_reviewers: int
    completed_reviewers: int
    avg_technical_score: Optional[float] = None
    avg_experience_score: Optional[float] = None
    avg_overall_score: Optional[float] = None
    recommend_count: int = 0
    not_recommend_count: int = 0
    pending_count: int = 0
    recommend_ratio: float = 0.0
    comments: List[str] = []
    reviews: List[DepartmentReviewResponse] = []

    model_config = ConfigDict(from_attributes=True)


# Resolve forward references
ResumeResponse.model_rebuild()
