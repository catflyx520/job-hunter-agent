"""处理一个职位线索：读取职位页 → 抽取 → 去重 → 硬性排除 → 匹配评分 → 签证状态。

每个线索用自己的数据库 session；存档的那一段加锁，避免两个来源同时建出同一个职位。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.fetch import FetchError, fetch_page
from app.jobs.exclusion import check_exclusions
from app.jobs.extract import extract_job
from app.jobs.normalize import site_for_url
from app.jobs.service import IngestError, JobOrigin, add_source, find_existing, match_job, save_job
from app.llm.base import LLMError
from app.llm.registry import provider_for_task
from app.models import Job, JobMatch, JobSource, SearchRunJob
from app.schemas.profile import JobPreferences
from app.search.sites import Lead, clean_url
from app.sponsor.lookup import refresh_company

SAVE_LOCK = threading.Lock()


@dataclass
class LeadResult:
    site_id: str
    url: str
    outcome: str  # kept / excluded / duplicate / blocked / failed / expired / cancelled / over_limit
    job_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    message: str = ""


def _seen_before(db: Session, job_id, run_id: str) -> bool:
    """这个职位是否已经出现在更早的搜索批次里。"""
    return (
        db.scalar(
            select(SearchRunJob.run_id).where(SearchRunJob.job_id == job_id, SearchRunJob.run_id != run_id).limit(1)
        )
        is not None
    )


def _existing_by_url(db: Session, lead: Lead) -> Job | None:
    src = db.scalar(select(JobSource).where(JobSource.url.in_([lead.url, clean_url(lead.url)])))
    if src is None and lead.site_job_id:
        src = db.scalar(
            select(JobSource).where(JobSource.site_id == lead.site_id, JobSource.site_job_id == lead.site_job_id)
        )
    return src.job if src else None


def _evaluate(db: Session, job: Job, lead: Lead, prefs: JobPreferences, sponsor: bool) -> LeadResult:
    """硬性排除优先；没被排除才做匹配评分（省模型额度）。"""
    if sponsor:
        refresh_company(db, job.company)
    exclusion = check_exclusions(job, prefs)
    if exclusion.excluded:
        return LeadResult(lead.site_id, lead.url, "excluded", str(job.id), exclusion.reasons)
    latest = db.scalar(select(JobMatch).where(JobMatch.job_id == job.id).order_by(JobMatch.created_at.desc()).limit(1))
    if latest is None or latest.created_at < (job.updated_at or job.created_at):
        try:
            match_job(db, job)
        except IngestError:
            pass  # 履历没有可引用的内容：职位照样保留，显示「未评分」，详情页可在修好履历后重新评分
    return LeadResult(lead.site_id, lead.url, "kept", str(job.id))


def process_lead(run_id: str, lead: Lead, prefs: JobPreferences, sponsor: bool) -> LeadResult:
    maker = get_sessionmaker()
    now = datetime.now(UTC)

    # 1. 已经存过的网址：不重新读取
    with maker() as db:
        job = _existing_by_url(db, lead)
        if job is not None:
            with SAVE_LOCK:
                add_source(db, job, lead.url, lead.site_id, lead.site_job_id, run_id)
                db.commit()
            if _seen_before(db, job.id, run_id):
                return LeadResult(lead.site_id, lead.url, "duplicate", str(job.id), message="已在之前的批次出现")
            try:
                result = _evaluate(db, job, lead, prefs, sponsor)
                db.commit()
                return result
            except LLMError as exc:
                db.rollback()
                return LeadResult(lead.site_id, lead.url, "failed", str(job.id), message=f"匹配评分失败：{exc}")

    # 2. 取得 JD：ATS API 已经给了；否则用安全读取去读职位页
    links: list[str] = []
    if lead.jd_text:
        jd_text, url, verification, verified_at = lead.jd_text, lead.url, "ats_api", now
    else:
        try:
            page = fetch_page(lead.url)
        except FetchError as exc:
            outcome = "blocked" if exc.blocked else ("expired" if "下架" in str(exc) else "failed")
            return LeadResult(lead.site_id, lead.url, outcome, message=str(exc).split("。")[0])
        jd_text, url, links, verified_at = page.text, lead.url, page.links, page.retrieved_at
        verification = "employer_site" if site_for_url(page.url) == "manual" else "job_board"

    # 3. 抽取（模型呼叫，不加锁）
    with maker() as db:
        hints = {"title": lead.title} if lead.ats else {}
        if lead.ats and lead.company:
            hints["company"] = lead.company
        try:
            ex, _ = extract_job(provider_for_task(db, "job_extract"), jd_text, hints)
        except LLMError as exc:
            return LeadResult(lead.site_id, lead.url, "failed", message=f"职位资料抽取失败：{exc}")
        if not ex.title.strip() or not (ex.company or lead.company).strip():
            return LeadResult(lead.site_id, lead.url, "failed", message="页面里找不到职称或公司名称")
        if not ex.posted_text and lead.posted_text:
            ex.posted_text = lead.posted_text

        # 4. 存档（加锁）：同一职位可能同时从别的网站找到
        with SAVE_LOCK:
            job = find_existing(db, ex, lead.company)
            if job is not None:
                # 同一职位已经存在（别的网站找到、或之前贴过）：只补上这个来源链接
                add_source(db, job, url, lead.site_id, lead.site_job_id, run_id)
            else:
                origin = JobOrigin(
                    url=url,
                    site_id=lead.site_id,
                    verification=verification,
                    status="active",
                    verified_at=verified_at,
                    site_job_id=lead.site_job_id,
                    run_id=run_id,
                    posted_at=lead.posted_at,
                    links=links,
                )
                job, _ = save_job(db, ex, jd_text, origin, company_hint=lead.company)
            db.commit()
        if _seen_before(db, job.id, run_id):
            return LeadResult(lead.site_id, lead.url, "duplicate", str(job.id), message="已在之前的批次出现")

        # 5. 排除与评分
        try:
            result = _evaluate(db, job, lead, prefs, sponsor)
            db.commit()
            return result
        except LLMError as exc:
            db.rollback()
            return LeadResult(lead.site_id, lead.url, "failed", str(job.id), message=f"匹配评分失败：{exc}")
