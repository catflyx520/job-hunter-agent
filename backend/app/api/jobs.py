"""贴网址 / 贴 JD、职位、匹配评分、公司签证历史。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.fetch import FetchError
from app.jobs.exclusion import FLAG_LABELS, REASON_LABELS, check_exclusions
from app.jobs.service import IngestError, ingest, load_preferences, match_job
from app.llm.base import LLMError
from app.llm.registry import provider_for_task
from app.models import Application, ApplicationEvent, Company, CompanySponsorStatus, EmployerAlias, Job, JobMatch
from app.rag.retrieve import evidence_texts
from app.schemas.job import (
    AliasDecision,
    CompanyOut,
    CompanyUpdate,
    ExclusionOut,
    IngestIn,
    IngestOut,
    JobDetail,
    JobSummary,
    MatchOut,
    SponsorStatusOut,
)
from app.sponsor.entity import EntityError, suggest_entity
from app.sponsor.import_status import read_status
from app.sponsor.lookup import compute_status, coverage, refresh_company

router = APIRouter(prefix="/api", tags=["jobs"])


def _latest_match(db: Session, job_id: uuid.UUID) -> JobMatch | None:
    return db.scalar(select(JobMatch).where(JobMatch.job_id == job_id).order_by(JobMatch.created_at.desc()).limit(1))


def _application(db: Session, job_id: uuid.UUID) -> dict:
    row = db.execute(
        select(Application.status, Application.applied_at, func.max(ApplicationEvent.at).label("status_at"))
        .outerjoin(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .where(Application.job_id == job_id)
        .group_by(Application.id)
    ).first()
    if row is None:
        return {"application_status": None, "applied_at": None, "status_at": None}
    return {"application_status": row.status, "applied_at": row.applied_at, "status_at": row.status_at}


def _summary(db: Session, job: Job) -> dict:
    m = _latest_match(db, job.id)
    st = db.get(CompanySponsorStatus, job.company_id)
    prefs, _ = load_preferences(db)
    return {
        **{k: getattr(job, k) for k in JobSummary.model_fields if hasattr(job, k) and k != "company"},
        "company": CompanyOut.model_validate(job.company),
        "score": m.score if m else None,
        "recommendation": m.recommendation if m else None,
        "excluded": check_exclusions(job, prefs).excluded,
        "sponsor_status": st.status if st else None,
        "sponsor_h1b": bool(st.h1b_years) if st else None,
        "sponsor_perm": bool(st.perm_years) if st else None,
        **_application(db, job.id),
    }


def _detail(db: Session, job: Job) -> JobDetail:
    prefs, _ = load_preferences(db)
    exc = check_exclusions(job, prefs)
    m = _latest_match(db, job.id)
    st = db.get(CompanySponsorStatus, job.company_id)
    evidence = evidence_texts(db, [c for r in m.reasons for c in r.get("chunk_ids", [])], m.resume_id) if m else {}
    return JobDetail(
        **_summary(db, job),
        **{
            k: getattr(job, k)
            for k in JobDetail.model_fields
            if k not in JobSummary.model_fields
            and hasattr(job, k)
            and k not in ("sources", "exclusion", "match", "sponsor", "evidence")
        },
        sources=[{"site_id": s.site_id, "url": s.url} for s in job.sources],
        exclusion=ExclusionOut(
            reasons=[{"code": r, "label": REASON_LABELS[r]} for r in exc.reasons],
            flags=[{"code": f, "label": FLAG_LABELS[f]} for f in exc.flags],
        ),
        match=MatchOut.model_validate(m) if m else None,
        sponsor=SponsorStatusOut.model_validate(st, from_attributes=True) if st else None,
        evidence=evidence,
    )


def _get_job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "找不到这个职位")
    return job


@router.post("/jobs/ingest", response_model=IngestOut, status_code=201)
def ingest_job(body: IngestIn, db: Session = Depends(get_db)):
    try:
        result = ingest(db, body.url, body.jd_text, body.company, body.title)
    except FetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (IngestError, LLMError) as exc:
        raise HTTPException(422 if isinstance(exc, IngestError) else 502, str(exc)) from exc
    return IngestOut(job=_detail(db, result.job), notes=result.notes, created=result.created)


@router.get("/jobs", response_model=list[JobSummary])
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).order_by(Job.location_tier.asc().nulls_last(), Job.created_at.desc())).all()
    return [JobSummary(**_summary(db, j)) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _detail(db, _get_job(db, job_id))


@router.post("/jobs/{job_id}/match", response_model=JobDetail)
def match(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    try:
        match_job(db, job)
    except IngestError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(502, f"匹配评分失败：{exc}") from exc
    return _detail(db, job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get_job(db, job_id))


# ---------- 公司与签证历史 ----------


def _get_company(db: Session, company_id: uuid.UUID) -> Company:
    c = db.get(Company, company_id)
    if c is None:
        raise HTTPException(404, "找不到这家公司")
    return c


@router.get("/sponsor/coverage")
def sponsor_coverage(db: Session = Depends(get_db)):
    return {**coverage(db), "import": read_status(get_settings().data_dir)}


@router.patch("/companies/{company_id}", response_model=SponsorStatusOut)
def update_company(company_id: uuid.UUID, body: CompanyUpdate, db: Session = Depends(get_db)):
    c = _get_company(db, company_id)
    if body.website is not None:
        c.website = body.website.strip() or None
    if body.is_staffing_agency is not None:
        c.is_staffing_agency = body.is_staffing_agency
    db.flush()
    return SponsorStatusOut.model_validate(compute_status(db, c), from_attributes=True)


@router.post("/companies/{company_id}/sponsor/refresh", response_model=SponsorStatusOut)
def refresh_sponsor(company_id: uuid.UUID, db: Session = Depends(get_db)):
    return SponsorStatusOut.model_validate(refresh_company(db, _get_company(db, company_id)), from_attributes=True)


@router.post("/companies/{company_id}/sponsor/suggest-entity")
def suggest_legal_entity(company_id: uuid.UUID, db: Session = Depends(get_db)):
    c = _get_company(db, company_id)
    try:
        result = suggest_entity(db, c, provider_for_task(db, "sponsor_entity"))
    except EntityError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(502, f"推测法律实体失败：{exc}") from exc
    status = compute_status(db, c)
    return {**result, "sponsor": SponsorStatusOut.model_validate(status, from_attributes=True)}


@router.post("/sponsor/aliases/{alias_id}", response_model=SponsorStatusOut)
def decide_alias(alias_id: uuid.UUID, body: AliasDecision, db: Session = Depends(get_db)):
    alias = db.get(EmployerAlias, alias_id)
    if alias is None:
        raise HTTPException(404, "找不到这个比对建议")
    alias.status = body.status
    if body.status == "confirmed" and alias.method != "exact":
        alias.note = (alias.note or "") + "（已由你确认）"
    db.flush()
    return SponsorStatusOut.model_validate(compute_status(db, _get_company(db, alias.company_id)), from_attributes=True)
