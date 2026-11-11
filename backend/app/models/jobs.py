"""C 组：职位搜索与匹配。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import _created, _in, _updated, _uuid_pk

SITE_ACCESS = ("web_search", "ats_api", "paste_only")
ATS_KINDS = ("greenhouse", "lever", "ashby", "workday", "other", "unknown")
SENIORITY = ("junior", "mid", "senior", "staff_plus", "unknown")
WORK_MODES = ("onsite", "hybrid", "remote", "unknown")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "contract_to_hire", "internship", "unknown")
SPONSORSHIP = ("explicit_yes", "explicit_no", "unclear")
JOB_STATUS = ("active", "expired", "unverified")
VERIFICATION = ("employer_site", "ats_api", "job_board", "search_snippet", "pasted")
RUN_STATUS = ("pending", "running", "completed", "failed", "cancelled")
RUN_SITE_STATUS = ("ok", "partial", "blocked", "failed", "skipped")
RUN_OUTCOME = ("kept", "excluded", "duplicate")
RECOMMENDATION = ("apply", "maybe", "skip")


class JobSite(Base):
    __tablename__ = "job_sites"
    __table_args__ = (CheckConstraint(_in("access_method", SITE_ACCESS), name="ck_job_sites_access"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    access_method: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    max_results: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="20")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    limitation_note: Mapped[str | None] = mapped_column(Text)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (CheckConstraint(_in("ats_kind", ATS_KINDS), name="ck_companies_ats_kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(Text)
    careers_url: Mapped[str | None] = mapped_column(Text)
    ats_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    ats_board_token: Mapped[str | None] = mapped_column(Text)
    is_staffing_agency: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("seniority", SENIORITY), name="ck_jobs_seniority"),
        CheckConstraint(_in("work_mode", WORK_MODES), name="ck_jobs_work_mode"),
        CheckConstraint(_in("employment_type", EMPLOYMENT_TYPES), name="ck_jobs_employment_type"),
        CheckConstraint(_in("sponsorship_policy", SPONSORSHIP), name="ck_jobs_sponsorship"),
        CheckConstraint(_in("status", JOB_STATUS), name="ck_jobs_status"),
        CheckConstraint(_in("verification_source", VERIFICATION), name="ck_jobs_verification"),
        Index("ix_jobs_list", "status", "location_tier", "posted_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    requisition_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seniority: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(Text)
    location_tier: Mapped[int | None] = mapped_column(SmallInteger)
    work_mode: Mapped[str] = mapped_column(Text, nullable=False)
    employment_type: Mapped[str] = mapped_column(Text, nullable=False)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(Text)
    salary_period: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_text: Mapped[str | None] = mapped_column(Text)
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_sha256: Mapped[str | None] = mapped_column(Text)
    jd_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sponsorship_policy: Mapped[str] = mapped_column(Text, nullable=False)
    sponsorship_evidence: Mapped[str | None] = mapped_column(Text)
    new_grad_only: Mapped[bool | None] = mapped_column(Boolean)
    clearance_required: Mapped[bool | None] = mapped_column(Boolean)
    citizenship_required: Mapped[bool | None] = mapped_column(Boolean)
    easy_apply: Mapped[bool | None] = mapped_column(Boolean)
    apply_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_source: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # LLM 抽取的完整结果（含证据句）
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    company: Mapped[Company] = relationship()
    sources: Mapped[list["JobSource"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobSource(Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("site_id", "site_job_id", name="uq_job_sources_site_job"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[str] = mapped_column(Text, ForeignKey("job_sites.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    site_job_id: Mapped[str | None] = mapped_column(Text)
    first_seen_run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("search_runs.id"))
    last_seen_at: Mapped[datetime] = _created()

    job: Mapped[Job] = relationship(back_populates="sources")


class SearchRun(Base):
    __tablename__ = "search_runs"
    __table_args__ = (CheckConstraint(_in("status", RUN_STATUS), name="ck_search_runs_status"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL")
    )
    preferences_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_thread_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class SearchRunSite(Base):
    __tablename__ = "search_run_sites"
    __table_args__ = (CheckConstraint(_in("status", RUN_SITE_STATUS), name="ck_search_run_sites_status"),)

    run_id: Mapped[str] = mapped_column(Text, ForeignKey("search_runs.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[str] = mapped_column(Text, ForeignKey("job_sites.id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    found_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    kept_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    message: Mapped[str | None] = mapped_column(Text)


class SearchRunJob(Base):
    __tablename__ = "search_run_jobs"
    __table_args__ = (CheckConstraint(_in("outcome", RUN_OUTCOME), name="ck_search_run_jobs_outcome"),)

    run_id: Mapped[str] = mapped_column(Text, ForeignKey("search_runs.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    exclusion_reasons: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = _created()


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        CheckConstraint(_in("recommendation", RECOMMENDATION), name="ck_job_matches_recommendation"),
        Index("ix_job_matches_latest", "job_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL")
    )
    preferences_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    exclusion_reasons: Mapped[list[str] | None] = mapped_column(ARRAY(Text))  # 贴 JD 流程的硬性排除结果
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
