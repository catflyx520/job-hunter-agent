"""求职需求与个人事实库的 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Seniority = Literal["junior", "mid", "senior", "staff_plus"]
WorkMode = Literal["onsite", "hybrid", "remote"]
EmploymentType = Literal["full_time", "part_time", "contract", "contract_to_hire", "c2c", "internship"]
VisaStatus = Literal["us_citizen", "green_card", "h1b", "opt", "other"]

# 身份 → (已可在美国工作, 现在需要 sponsorship, 未来需要 sponsorship)
# H-1B 换雇主要新雇主递 transfer 申请，算「现在需要」；OPT / STEM OPT 现在能工作，之后要 H-1B。
STATUS_FLAGS: dict[str, tuple[bool, bool, bool]] = {
    "us_citizen": (True, False, False),
    "green_card": (True, False, False),
    "h1b": (True, True, True),
    "opt": (True, False, True),
}


class WorkAuthorization(BaseModel):
    status: VisaStatus | None = None  # 选了身份就以身份推出下面三项；"other" 或未选时用手动填的三项
    authorized_in_us: bool | None = None  # None = 尚未填写
    needs_sponsorship_now: bool | None = None
    needs_sponsorship_future: bool | None = None
    note: str = ""

    @model_validator(mode="after")
    def _from_status(self) -> WorkAuthorization:
        if self.status in STATUS_FLAGS:
            self.authorized_in_us, self.needs_sponsorship_now, self.needs_sponsorship_future = STATUS_FLAGS[self.status]
        return self


class Blacklist(BaseModel):
    """不想再看到的公司与职位。公司按正规化名称比对；职位是关键词组，职称里含这组词就算（不分大小写）。"""

    companies: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)

    @field_validator("companies", "titles")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for s in v:
            s = " ".join(s.split())
            if s and s.lower() not in {x.lower() for x in out}:
                out.append(s[:200])
        return out


class SearchSettings(BaseModel):
    sites: list[str] = Field(default_factory=list)  # job_sites.id，M3 才使用
    per_site_limit: int = Field(20, ge=1, le=100)
    target_jobs: int = Field(20, ge=1, le=200)  # 目标：找到几个可投的职位（被排除、之前已有的不算）
    total_limit: int = Field(100, ge=1, le=500)  # 安全上限：一次搜索最多检查几个职位页


class JobPreferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    paused_roles: list[str] = Field(default_factory=list, description="暂时停用的目标职位（仍保留在清单里）")
    seniority: list[Seniority] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list, description="依优先顺序排列")
    work_modes: list[WorkMode] = Field(default_factory=lambda: ["onsite", "hybrid", "remote"])
    employment_types: list[EmploymentType] = Field(default_factory=lambda: ["full_time"])
    min_salary: int | None = Field(None, ge=0)
    salary_rule: str = ""
    exclude_new_grad_only: bool = True
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    blacklist: Blacklist = Field(default_factory=Blacklist)
    search: SearchSettings = Field(default_factory=SearchSettings)

    @field_validator("target_roles", "locations")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]

    @field_validator("target_roles")
    @classmethod
    def _split_roles(cls, v: list[str]) -> list[str]:
        """「A, B, C」一次贴进来时拆成三个职位，搜索才会各查一次。"""
        out: list[str] = []
        for s in v:
            for part in s.replace("，", ",").split(","):
                if part.strip() and part.strip() not in out:
                    out.append(part.strip())
        return out

    @model_validator(mode="after")
    def _paused_subset(self) -> JobPreferences:
        self.paused_roles = [r for r in dict.fromkeys(self.paused_roles) if r in self.target_roles]
        return self

    @property
    def active_roles(self) -> list[str]:
        """搜索、评分、关键词检查只用启用中的职位。"""
        return [r for r in self.target_roles if r not in self.paused_roles]


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
