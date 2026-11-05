from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QualityRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    screening_days: int = Field(default=2, ge=1, le=60)
    department_assignment_days: int = Field(default=2, ge=1, le=60)
    department_decision_days: int = Field(default=1, ge=1, le=60)
    interview_arrangement_days: int = Field(default=2, ge=1, le=60)
    next_interview_days: int = Field(default=2, ge=1, le=60)
    interview_decision_days: int = Field(default=1, ge=1, le=60)
    offer_send_days: int = Field(default=2, ge=1, le=60)
    result_update_days: int = Field(default=1, ge=1, le=60)
    exception_days: int = Field(default=1, ge=1, le=60)
    department_review_required: bool = False

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_rules(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for old, new in (("screening_hours", "screening_days"),
                         ("interview_review_hours", "interview_decision_days")):
            hours = value.pop(old, None)
            if hours is not None and new not in value:
                value[new] = max(1, min(60, (int(hours) + 23) // 24))
        value.pop("coding_test_required", None)
        # Retain old policy JSON while retiring periodic follow-up scoring.
        value.pop("follow_up_days", None)
        # The old department rule timed reviewers, not the HR decision.
        value.pop("department_review_hours", None)
        return value


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="标准招聘流程", min_length=1, max_length=100)
    position_id: UUID | None = None
    rules: QualityRules = Field(default_factory=QualityRules)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("模板名称不能为空")
        return value.strip()


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["note"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("必须填写原因")
        return value.strip()
