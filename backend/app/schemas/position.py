from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any, Optional, List
from uuid import UUID
from datetime import datetime
from app.models.models import PositionCategory, PositionEventType, PositionStatus, PositionType


LEGACY_URGENCY_TO_PRIORITY = {
    "low": 1,
    "medium": 3,
    "high": 4,
    "urgent": 5,
}


def _normalize_position_classification(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    normalized = dict(data)
    if "priority" not in normalized and "urgency" in normalized:
        urgency = normalized.pop("urgency")
        urgency_value = getattr(urgency, "value", urgency)
        normalized["priority"] = LEGACY_URGENCY_TO_PRIORITY.get(urgency_value, 3)
    else:
        normalized.pop("urgency", None)
    if "priority" in normalized and normalized["priority"] is None:
        normalized["priority"] = 3
    if "category" in normalized and normalized["category"] is None:
        normalized["category"] = PositionCategory.UNCATEGORIZED
    return normalized

class PositionBase(BaseModel):
    title: str
    description: str
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    status: PositionStatus = PositionStatus.OPEN
    priority: int = Field(default=3, ge=1, le=5)
    category: PositionCategory = PositionCategory.UNCATEGORIZED
    position_type: PositionType = PositionType.FULL_TIME
    headcount: int = 1
    hiring_manager_id: Optional[UUID] = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_urgency(cls, data: Any) -> Any:
        return _normalize_position_classification(data)

class PositionCreate(PositionBase):
    pass

class PositionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    status: Optional[PositionStatus] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    category: Optional[PositionCategory] = None
    position_type: Optional[PositionType] = None
    headcount: Optional[int] = None
    hiring_manager_id: Optional[UUID] = None
    status_change_reason: Optional[str] = Field(default=None, max_length=1000)
    owner_change_reason: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_urgency(cls, data: Any) -> Any:
        return _normalize_position_classification(data)

class PositionResponse(PositionBase):
    id: UUID
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[UUID] = None
    delete_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HiringManagerOption(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: str
    model_config = ConfigDict(from_attributes=True)

class PositionStats(BaseModel):
    total_resumes: int = 0
    pending_screening: int = 0
    pending_interview: int = 0
    interview_completed: int = 0
    interview_passed: int = 0
    offer_pending: int = 0
    offer_accepted: int = 0
    rejected: int = 0

class PositionWithStats(PositionResponse):
    stats: PositionStats = PositionStats()
    hiring_manager_name: Optional[str] = None
    deleted_by_name: Optional[str] = None


class PositionEventResponse(BaseModel):
    id: UUID
    event_type: PositionEventType
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    actor_id: Optional[UUID] = None
    actor_name: Optional[str] = None
    reason: Optional[str] = None
    occurred_at: datetime
    event_metadata: dict = Field(default_factory=dict)
    model_config = ConfigDict(from_attributes=True)

class PositionDetailResponse(PositionResponse):
    stats: PositionStats = PositionStats()
    hiring_manager_name: Optional[str] = None
    linked_question_banks: List['QuestionBankBrief'] = []
    events: List[PositionEventResponse] = Field(default_factory=list)


class PositionBatchStatusRequest(BaseModel):
    position_ids: List[UUID] = Field(min_length=1, max_length=100)
    status: PositionStatus
    reason: Optional[str] = Field(default=None, max_length=1000)


class PositionBatchStatusResponse(BaseModel):
    updated_count: int


class PositionRestoreRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

class QuestionBankBrief(BaseModel):
    id: UUID
    name: str
    category: str
    question_count: int = 0
    model_config = ConfigDict(from_attributes=True)

class JDGenerateRequest(BaseModel):
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    salary_range: Optional[str] = None
    keywords: Optional[str] = None

class JDGenerateResponse(BaseModel):
    description: str
    requirements: str

class JDChatMessage(BaseModel):
    role: str
    content: str

class JDChatRequest(BaseModel):
    messages: List[JDChatMessage]
    current_description: str = ""
    current_requirements: str = ""
