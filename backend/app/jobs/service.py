"""贴网址 / 贴 JD 的流程：读取 → 抽取 → 存成职位 → 硬性排除 → 匹配评分。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.fetch import fetch_page
from app.jobs.exclusion import check_exclusions, closed_posting
from app.jobs.extract import JobExtraction, extract_job
from app.jobs.match import score_match
from app.jobs.normalize import canonical_key, location_tier, normalize_company, site_for_url
from app.llm.registry import provider_for_task
from app.models import Company, Job, JobMatch, JobSource, Preferences, Resume
from app.rag.retrieve import retrieve
from app.schemas.profile import JobPreferences
from app.search.sites import ats_from_url
from app.sponsor.lookup import refresh_company


class IngestError(ValueError):
    pass


@dataclass
class IngestResult:
    job: Job
    notes: list[str]
    created: bool


def load_preferences(db: Session) -> tuple[JobPreferences, int]:
    row = db.get(Preferences, 1)
    return (JobPreferences.model_validate(row.data), row.version) if row else (JobPreferences(), 0)


def upsert_company(db: Session, name: str, website: str = "", staffing: bool = False) -> Company:
    norm = normalize_company(name)
    if not norm:
        raise IngestError("JD 里找不到公司名称，请在「公司」栏填写。")
    company = db.scalar(select(Company).where(Company.normalized_name == norm))
    if company is None:
        company = Company(display_name=name.strip(), normalized_name=norm, is_staffing_agency=staffing)
        db.add(company)
    if website and not company.website:
        company.website = website
    if staffing:
        company.is_staffing_agency = True
    db.flush()
    return company


def ingest(
    db: Session, url: str | None, jd_text: str | None, company_hint: str = "", title_hint: str = ""
) -> IngestResult:
    notes: list[str] = []
    links: list[str] = []
    url = (url or "").strip() or None
    jd_text = (jd_text or "").strip() or None
    if not url and not jd_text:
        raise IngestError("请贴上职位网址或 JD。")

    if jd_text:
        verification, status, verified_at = "pasted", "unverified", None
        if url:
            notes.append("使用你贴上的 JD；网址只记录为来源，未重新读取。")
    else:
        page = fetch_page(url)  # FetchError 由 API 层转成讯息
        jd_text, url, links = page.text, page.url, page.links
        site = site_for_url(url)
        verification = (
            "job_board"
            if site not in ("manual", "greenhouse", "lever", "ashby")
            else ("ats_api" if site in ("greenhouse", "lever", "ashby") else "employer_site")
        )
        status, verified_at = "active", page.retrieved_at
        notes.append("已读取公开网页；网页文字可能包含 JD 以外的内容，请检查抽取结果。")

    ex, evidence_notes = extract_job(
        provider_for_task(db, "job_extract"), jd_text, {"company": company_hint, "title": title_hint}
    )
    notes += evidence_notes
    job, created = save_job(
        db,
        ex,
        jd_text,
        JobOrigin(
            url=url,
            site_id=site_for_url(url) if url else None,
            verification=verification,
            status=status,
            verified_at=verified_at,
            links=links,
        ),
        company_hint=company_hint,
    )
    if not created:
        notes.append("这个职位之前已经存过（同公司、职称、地点或职位编号），已用最新内容更新。")
    refresh_company(db, job.company)
    return IngestResult(job=job, notes=notes, created=created)


@dataclass
class JobOrigin:
    """职位从哪里来、核实到什么程度。"""

    url: str | None
    site_id: str | None
    verification: str
    status: str
    verified_at: datetime | None
    site_job_id: str | None = None
    run_id: str | None = None
    posted_at: datetime | None = None
    links: list[str] = field(default_factory=list)  # 职位页里的 ATS 链接，用来记下公司的 board 名


def find_existing(db: Session, ex: JobExtraction, company_hint: str = "") -> Job | None:
    norm = normalize_company(ex.company or company_hint)
    return db.scalar(
        select(Job).where(Job.canonical_key == canonical_key(norm, ex.title, ex.location_text, ex.requisition_id))
    )


def save_job(
    db: Session, ex: JobExtraction, jd_text: str, origin: JobOrigin, company_hint: str = ""
) -> tuple[Job, bool]:
    """把抽取结果存成职位（依 canonical_key 去重），并记下来源链接。回传 (职位, 是否新建)。"""
    if not ex.title.strip():
        raise IngestError("JD 里找不到职称，请在「职称」栏填写。")
    now = datetime.now(UTC)
    company = upsert_company(db, ex.company or company_hint, ex.company_website, ex.is_staffing_agency)
    for link in [*(origin.links or []), ex.apply_url, origin.url or ""]:
        found = ats_from_url(link) if link else None
        if found and not company.ats_board_token:
            company.ats_kind, company.ats_board_token = found
    prefs, _ = load_preferences(db)

    key = canonical_key(company.normalized_name, ex.title, ex.location_text, ex.requisition_id)
    job = db.scalar(select(Job).where(Job.canonical_key == key))
    created = job is None
    if job is None:
        job = Job(canonical_key=key, company_id=company.id)
        db.add(job)

    job.company = company
    job.requisition_id = ex.requisition_id or None
    job.title = ex.title
    job.seniority = ex.seniority
    job.location_text = ex.location_text or None
    job.work_mode = ex.work_mode
    job.employment_type = ex.employment_type
    job.location_tier = location_tier(ex.location_text, ex.work_mode, prefs.locations)
    job.salary_min, job.salary_max = ex.salary_min, ex.salary_max
    job.salary_currency = ex.salary_currency or ("USD" if ex.salary_min or ex.salary_max else None)
    job.salary_period = ex.salary_period if (ex.salary_min or ex.salary_max) else None
    job.posted_text = ex.posted_text or None
    if origin.posted_at:
        job.posted_at = origin.posted_at
    job.jd_text = jd_text
    job.jd_sha256 = hashlib.sha256(jd_text.encode()).hexdigest()
    job.jd_fetched_at = now
    job.sponsorship_policy = ex.sponsorship_policy
    job.sponsorship_evidence = ex.sponsorship_evidence or None
    job.new_grad_only = ex.new_grad_only
    job.citizenship_required = ex.citizenship_required
    job.clearance_required = ex.clearance_required
    job.apply_url = ex.apply_url or origin.url
    job.status = "expired" if origin.status == "active" and closed_posting(jd_text) else origin.status
    job.verified_at = origin.verified_at
    job.verification_source = origin.verification
    job.extracted = ex.model_dump()
    db.flush()

    if origin.url:
        add_source(db, job, origin.url, origin.site_id or site_for_url(origin.url), origin.site_job_id, origin.run_id)
    return job, created


def add_source(
    db: Session, job: Job, url: str, site_id: str, site_job_id: str | None = None, run_id: str | None = None
) -> JobSource:
    now = datetime.now(UTC)
    source = db.scalar(select(JobSource).where(JobSource.url == url))
    if source is None and site_job_id:
        source = db.scalar(select(JobSource).where(JobSource.site_id == site_id, JobSource.site_job_id == site_job_id))
    if source is None:
        source = JobSource(
            job_id=job.id, site_id=site_id, url=url, site_job_id=site_job_id, first_seen_run_id=run_id, last_seen_at=now
        )
        db.add(source)
    else:
        source.job_id, source.last_seen_at = job.id, now
    db.flush()
    return source


def match_job(db: Session, job: Job) -> JobMatch:
    resume = db.scalar(select(Resume).where(Resume.is_active.is_(True)))
    if resume is None:
        raise IngestError("请先上传并设定一份使用中的履历。")
    prefs, version = load_preferences(db)
    exclusion = check_exclusions(job, prefs)
    ex = job.extracted or {}
    keywords = [job.title, *ex.get("required_skills", []), *ex.get("nice_to_have_skills", [])]
    query = f"{job.title}\n{', '.join(keywords)}\n{(job.jd_text or '')[:2000]}"
    retrieval = retrieve(db, resume, query, keywords)
    if not retrieval.items:
        # 没有任何履历内容可引用时，模型只能给职位 / 技术 / 年资 0 分，分数没有意义，宁可不评
        raise IngestError(
            f"使用中的履历「{resume.label}」没有结构化出经历或专案，无法评分。"
            "请到「履历内容」检查后确认，或在「版本管理」按「重新结构化」。"
        )
    result = score_match(provider_for_task(db, "match_score"), job, prefs, retrieval.items, exclusion)
    if retrieval.note:
        result["gaps"].append({"text": retrieval.note, "severity": "low"})
    m = JobMatch(
        job_id=job.id,
        resume_id=resume.id,
        preferences_version=version,
        exclusion_reasons=exclusion.reasons or None,
        **result,
    )
    db.add(m)
    db.flush()
    return m
