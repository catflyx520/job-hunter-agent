from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestIn(BaseModel):
    url: str | None = Field(None, max_length=2500)
    jd_text: str | None = Field(None, max_length=60_000)
    company: str = Field("", max_length=200)
    title: str = Field("", max_length=300)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    website: str | None
    is_staffing_agency: bool


class CompanyUpdate(BaseModel):
    website: str | None = Field(None, max_length=500)
    is_staffing_agency: bool | None = None


class SponsorStatusOut(BaseModel):
    status: Literal["records_found", "no_match_in_scope", "not_checked", "employer_unknown"]
    h1b_years: list[int] | None
    perm_years: list[int] | None
    summary: dict[str, Any]
    coverage: dict[str, Any]
    computed_at: datetime


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    score: int
    breakdown: dict[str, Any]
    recommendation: Literal["apply", "maybe", "skip"]
    reasons: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    exclusion_reasons: list[str] | None
    model: str
    resume_id: uuid.UUID
    preferences_version: int
    created_at: datetime


class ExclusionOut(BaseModel):
    reasons: list[dict[str, str]]  # [{code, label}]
    flags: list[dict[str, str]]


class JobSummary(BaseModel):
    id: uuid.UUID
    title: str
    company: CompanyOut
    location_text: str | None
    work_mode: str
    employment_type: str
    salary_min: int | None
    salary_max: int | None
    salary_period: str | None
    sponsorship_policy: str
    status: str
    created_at: datetime
    score: int | None = None
    recommendation: str | None = None
    excluded: bool = False
    sponsor_status: str | None = None
    location_tier: int | None = None
    posted_text: str | None = None
    posted_at: datetime | None = None
    apply_url: str | None = None


class JobDetail(JobSummary):
    requisition_id: str | None
    seniority: str | None
    salary_currency: str | None
    sponsorship_evidence: str | None
    new_grad_only: bool | None
    citizenship_required: bool | None
    clearance_required: bool | None
    easy_apply: bool | None
    verification_source: str | None
    verified_at: datetime | None
    jd_text: str | None
    extracted: dict[str, Any] | None
    sources: list[dict[str, str]]
    exclusion: ExclusionOut
    match: MatchOut | None
    sponsor: SponsorStatusOut | None
    evidence: dict[str, str] = Field(default_factory=dict)  # chunk_id → 履历原文，显示理由引用用


class IngestOut(BaseModel):
    job: JobDetail
    notes: list[str]
    created: bool


class AliasDecision(BaseModel):
    status: Literal["confirmed", "rejected"]


# ---------- 搜索（F3） ----------


class JobSiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    access_method: Literal["web_search", "ats_api", "paste_only"]
    enabled: bool
    max_results: int
    sort_order: int
    limitation_note: str | None
    boards: int = 0  # ATS 网站：已知的公司 board 数


class JobSiteUpdate(BaseModel):
    enabled: bool | None = None
    max_results: int | None = Field(None, ge=1, le=100)


class SearchSourceOut(BaseModel):
    ready: bool
    label: str  # 目前使用的搜索来源，或无法搜索的原因
    integration: dict[str, Any] | None  # {kind, base_url, key_last4}


class IntegrationIn(BaseModel):
    kind: Literal["none", "tavily", "searxng"]
    api_key: str | None = Field(None, max_length=500)
    base_url: str | None = Field(None, max_length=500)


class AtsBoardIn(BaseModel):
    url: str = Field(max_length=2500)
    company: str = Field("", max_length=200)


class AtsBoardOut(BaseModel):
    company_id: uuid.UUID
    company: str
    kind: str
    token: str


class SearchRunIn(BaseModel):
    site_ids: list[str] | None = None  # 不给就用已勾选的网站
    sponsor_history: bool = True


class RunSiteOut(BaseModel):
    site_id: str
    name: str
    status: str  # ok / partial / blocked / failed / skipped，进行中为 searching
    found_count: int = 0
    kept_count: int = 0
    message: str | None = None


class RunJobOut(JobSummary):
    outcome: Literal["kept", "excluded", "duplicate"]
    exclusion_reasons: list[dict[str, str]] = Field(default_factory=list)
    found_on: list[str] = Field(default_factory=list)  # 这个批次在哪些网站找到


class SearchRunOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    search_source: str | None
    sponsor_history: bool
    sites: list[RunSiteOut]
    progress: dict[str, Any] | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class SearchRunDetail(SearchRunOut):
    jobs: list[RunJobOut] = Field(default_factory=list)
