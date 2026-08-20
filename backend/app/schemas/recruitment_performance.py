from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_TARGET_DAYS = {
    "campus": 30,
    "domestic_functional": 45,
    "domestic_rd": 75,
    "overseas": 90,
    "executive_expert": 120,
}
DEFAULT_TIME_COEFFICIENTS = {
    "lte_80": 1.2,
    "80_90": 1.1,
    "90_100": 1.0,
    "100_110": 0.9,
    "110_130": 0.8,
    "130_150": 0.7,
    "gt_150": 0.5,
}
DEFAULT_RESULT_COEFFICIENTS = {
    "onboarded": 1.0,
    "offer_accepted": 0.9,
    "offer_pending": 0.8,
    "interview_passed": 0.6,
    "business_interview_completed": 0.4,
    "hr_interview_completed": 0.2,
    "open": 0.0,
}


class PerformanceConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_year: int = Field(ge=2026, le=2100)
    effective_quarter: int = Field(ge=1, le=4)
    target_days: Dict[str, int]
    time_coefficients: Dict[str, float]
    result_coefficients: Dict[str, float]

    @field_validator("target_days")
    @classmethod
    def validate_target_days(cls, value):
        if set(value) != set(DEFAULT_TARGET_DAYS) or any(days < 1 for days in value.values()):
            raise ValueError("目标时间必须覆盖全部岗位分类且大于0")
        return value

    @field_validator("time_coefficients")
    @classmethod
    def validate_time_coefficients(cls, value):
        if set(value) != set(DEFAULT_TIME_COEFFICIENTS) or any(not 0 <= coefficient <= 2 for coefficient in value.values()):
            raise ValueError("时间系数必须覆盖全部固定区间且介于0和2之间")
        return value

    @field_validator("result_coefficients")
    @classmethod
    def validate_result_coefficients(cls, value):
        if set(value) != set(DEFAULT_RESULT_COEFFICIENTS) or any(not 0 <= coefficient <= 1 for coefficient in value.values()):
            raise ValueError("结果系数必须覆盖全部固定阶段且介于0和1之间")
        return value


class PerformanceConfigResponse(PerformanceConfigPayload):
    id: Optional[UUID] = None
    status: str = "default"
    version: int = 0
    published_at: Optional[datetime] = None


class HcScore(BaseModel):
    slot_id: UUID
    slot_number: int
    candidate_name: Optional[str]
    result_stage: str
    result_coefficient: float
    target_days: int
    actual_days: int
    deducted_days: int
    effective_held_days: int
    time_coefficient: float
    task_points: float
    score: float
    status: str


class PositionScore(BaseModel):
    position_id: UUID
    title: str
    category: str
    priority: int
    hc_count: int
    onboarded_count: int
    excluded_count: int
    task_points: float
    score: float
    achievement_rate: Optional[float]
    highest_result_stage: str
    slots: List[HcScore]


class PersonScore(BaseModel):
    user_id: UUID
    name: str
    email: str
    hc_count: int
    excluded_count: int
    onboarded_count: int
    task_points: float
    score: float
    achievement_rate: Optional[float]
    positions: List[PositionScore] = []


class PerformanceOverview(BaseModel):
    period: str
    as_of: date
    status: str
    settlement_version: Optional[int] = None
    people: List[PersonScore]


class PerformanceLeaderboardEntry(BaseModel):
    rank: int
    name: str
    achievement_rate: float
    is_current_user: bool = False


class PerformanceLeaderboard(BaseModel):
    period: str
    as_of: date
    status: str
    settlement_version: Optional[int] = None
    entries: List[PerformanceLeaderboardEntry]


class PerformancePeriodOptions(BaseModel):
    periods: List[str]
    default_period: str


class SettlementRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=1000)


class PauseRequest(BaseModel):
    start_at: datetime
    end_at: Optional[datetime] = None
    reason: str = Field(min_length=1, max_length=1000)


class PauseDecision(BaseModel):
    approve: bool
    end_at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, max_length=1000)


class OnboardingConfirmation(BaseModel):
    actual_onboard_date: date

    @field_validator("actual_onboard_date")
    @classmethod
    def cannot_be_future(cls, value):
        beijing_today = datetime.now(timezone(timedelta(hours=8))).date()
        if value > beijing_today:
            raise ValueError("实际入职日期不能晚于今天")
        return value
