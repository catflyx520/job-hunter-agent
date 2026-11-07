"""求职需求与个人事实库的 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Seniority = Literal["junior", "mid", "senior", "staff_plus"]
WorkMode = Literal["onsite", "hybrid", "remote"]
EmploymentType = Literal["full_time", "part_time", "contract", "contract_to_hire", "c2c", "internship"]


class WorkAuthorization(BaseModel):
    authorized_in_us: bool | None = None  # None = 尚未填写
    needs_sponsorship_now: bool | None = None
    needs_sponsorship_future: bool | None = None
    note: str = ""


class SearchSettings(BaseModel):
    sites: list[str] = Field(default_factory=list)  # job_sites.id，M3 才使用
    per_site_limit: int = Field(20, ge=1, le=100)
    total_limit: int = Field(100, ge=1, le=500)


class JobPreferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    seniority: list[Seniority] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list, description="依优先顺序排列")
    work_modes: list[WorkMode] = Field(default_factory=lambda: ["onsite", "hybrid", "remote"])
    employment_types: list[EmploymentType] = Field(default_factory=lambda: ["full_time"])
    min_salary: int | None = Field(None, ge=0)
    salary_rule: str = ""
    exclude_new_grad_only: bool = True
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    search: SearchSettings = Field(default_factory=SearchSettings)

    @field_validator("target_roles", "locations")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]


class PreferencesOut(BaseModel):
    data: JobPreferences
    version: int
    updated_at: datetime | None


# ---------- 个人事实库 ----------

ValueType = Literal["text", "number", "date", "boolean", "choice"]
FactSource = Literal["user_confirmed", "resume_derived", "from_answer"]


class FactIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    question: str = Field(min_length=1)
    value: str = ""
    value_type: ValueType = "text"
    source: FactSource = "user_confirmed"
    confirm: bool = False


class FactUpdate(BaseModel):
    question: str | None = None
    value: str | None = None
    value_type: ValueType | None = None
    confirm: bool | None = None  # True = 标记已确认；False = 取消确认


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    question: str
    value: str
    value_type: ValueType
    source: FactSource
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FactTemplate(BaseModel):
    key: str
    question: str
    value_type: ValueType


FACT_TEMPLATES: list[FactTemplate] = [
    FactTemplate(key="earliest_start_date", question="When can you start?", value_type="date"),
    FactTemplate(key="notice_period", question="What is your notice period?", value_type="text"),
    FactTemplate(key="willing_to_relocate", question="Are you willing to relocate?", value_type="boolean"),
    FactTemplate(key="desired_salary", question="What are your salary expectations?", value_type="text"),
    FactTemplate(
        key="work_authorization",
        question="Are you legally authorized to work in the United States?",
        value_type="boolean",
    ),
    FactTemplate(
        key="requires_sponsorship",
        question="Will you now or in the future require visa sponsorship?",
        value_type="boolean",
    ),
    FactTemplate(key="languages", question="What languages do you speak, and at what level?", value_type="text"),
    FactTemplate(key="years_of_experience", question="How many years of professional experience?", value_type="number"),
    FactTemplate(key="linkedin_url", question="LinkedIn profile URL", value_type="text"),
    FactTemplate(key="portfolio_url", question="Portfolio / GitHub URL", value_type="text"),
]
