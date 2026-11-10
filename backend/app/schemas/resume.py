"""履历相关的 Pydantic schema（对应 jsonb 栏位，写入前验证）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Link(BaseModel):
    label: str = ""
    url: str


class Basics(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)


class Experience(BaseModel):
    company: str = ""
    title: str = ""
    location: str = ""
    start: str = ""  # 保留原文写法，例如 "Jan 2021"
    end: str = ""  # "Present" 也保留原文
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str = ""
    description: str = ""
    tech: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""
    details: list[str] = Field(default_factory=list)


class ParsedResume(BaseModel):
    """LLM 结构化后的履历。所有文字照抄原文，不改写、不补充。"""

    basics: Basics = Field(default_factory=Basics)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    """履历管理页的版本列表：最近一次评分。"""

    model_config = ConfigDict(from_attributes=True)

    parse_score: int
    content_score: int
    keyword_score: int | None
    created_at: datetime


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    filename: str
    mime: str
    sha256: str
    parsed: ParsedResume
    parsed_confirmed_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0
    latest_review: ReviewSummary | None = None


class ResumeDetail(ResumeOut):
    raw_text: str


class UploadResult(BaseModel):
    resume: ResumeDetail
    parse_error: str | None = None
    # 结构化结果中在原文找不到的项目（可能被模型改写），请用户确认
    unverified_items: list[str] = Field(default_factory=list)


class ResumeRename(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class ParsedUpdate(BaseModel):
    parsed: ParsedResume
    confirm: bool = True


class ChunkResult(BaseModel):
    chunk_count: int
    embedding_model: str | None = None
    error: str | None = None


# ---------- 履历评分 ----------

FindingStatus = Literal["pass", "warn", "fail"]
FindingCategory = Literal["parse", "content", "keyword"]


class Finding(BaseModel):
    category: FindingCategory
    check: str
    status: FindingStatus
    message: str
    evidence: str | None = None
    points_lost: int = 0


class ReviewRequest(BaseModel):
    target_role: str | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID
    target_role: str | None
    parse_score: int
    content_score: int
    keyword_score: int | None
    findings: list[Finding]
    model: str
    created_at: datetime
