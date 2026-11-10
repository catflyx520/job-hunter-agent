"""F3 自动搜索：网站勾选、搜索来源设定、ATS board、搜索批次。"""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.jobs import _summary
from app.core.db import get_db
from app.core.security import encrypt_secret, last4
from app.jobs.exclusion import REASON_LABELS, check_exclusions
from app.jobs.service import IngestError, load_preferences, upsert_company
from app.llm.base import LLMError
from app.models import Company, Integration, Job, JobSite, JobSource, SearchRun, SearchRunJob, SearchRunSite
from app.schemas.job import (
    AtsBoardIn,
    AtsBoardOut,
    IntegrationIn,
    JobSiteOut,
    JobSiteUpdate,
    RunJobOut,
    RunSiteOut,
    SearchRunDetail,
    SearchRunIn,
    SearchRunOut,
    SearchSourceOut,
)
from app.search import progress, runner
from app.search.sites import ats_from_url
from app.search.web import active_integration, get_searcher, searcher_from_integration

router = APIRouter(prefix="/api", tags=["search"])


# ---------- 网站 ----------


def _site_out(db: Session, site: JobSite) -> JobSiteOut:
    out = JobSiteOut.model_validate(site)
    if site.access_method == "ats_api":
        out.boards = db.scalar(
            select(func.count())
            .select_from(Company)
            .where(Company.ats_kind == site.id, Company.ats_board_token.is_not(None))
        )
    return out


@router.get("/job-sites", response_model=list[JobSiteOut])
def list_sites(db: Session = Depends(get_db)):
    sites = db.scalars(select(JobSite).where(JobSite.id != "manual").order_by(JobSite.sort_order)).all()
    return [_site_out(db, s) for s in sites]


@router.patch("/job-sites/{site_id}", response_model=JobSiteOut)
def update_site(site_id: str, body: JobSiteUpdate, db: Session = Depends(get_db)):
    site = db.get(JobSite, site_id)
    if site is None or site.id == "manual":
        raise HTTPException(404, "找不到这个网站")
    if body.enabled is not None:
        if body.enabled and site.access_method == "paste_only":
            raise HTTPException(422, f"{site.name} 需要登录，只支援贴网址 / JD，不能自动搜索。")
        site.enabled = body.enabled
    if body.max_results is not None:
        site.max_results = body.max_results
    db.flush()
    return _site_out(db, site)


# ---------- 搜索来源 ----------


def _source(db: Session) -> SearchSourceOut:
    searcher, label = get_searcher(db)
    row = active_integration(db)
    integration = (
        {"kind": row.kind, "base_url": row.config.get("base_url"), "key_last4": row.config.get("key_last4")}
        if row
        else None
    )
    return SearchSourceOut(ready=searcher is not None, label=label, integration=integration)


@router.get("/search/source", response_model=SearchSourceOut)
def search_source(db: Session = Depends(get_db)):
    return _source(db)


@router.put("/search/integration", response_model=SearchSourceOut)
def set_integration(body: IntegrationIn, db: Session = Depends(get_db)):
    """一次只启用一个外部搜索服务；kind=none 代表改回模型自带搜索。"""
    rows = db.scalars(select(Integration)).all()
    for r in rows:
        r.enabled = False
    if body.kind != "none":
        row = next((r for r in rows if r.kind == body.kind), None)
        if row is None:
            row = Integration(kind=body.kind, config={})
            db.add(row)
        config = dict(row.config or {})
        if body.kind == "tavily":
            key = (body.api_key or "").strip()
            if key:
                row.secret_encrypted = encrypt_secret(key)
                config["key_last4"] = last4(key)
            elif not row.secret_encrypted:
                raise HTTPException(422, "请填写 Tavily API key。")
        else:
            base = (body.base_url or "").strip().rstrip("/")
            if not base.startswith(("http://", "https://")):
                raise HTTPException(422, "请填写 SearXNG 的网址，例如 http://localhost:8888")
            config["base_url"] = base
        row.config = config
        row.enabled = True
    db.flush()
    return _source(db)


@router.post("/search/integration/test")
def test_integration(db: Session = Depends(get_db)):
    row = active_integration(db)
    if row is None:
        raise HTTPException(422, "目前使用模型自带搜索，没有外部搜索服务可以测试。")
    try:
        found = searcher_from_integration(row)._query("software engineer jobs", "linkedin.com")  # type: ignore[attr-defined]
    except (LLMError, httpx.HTTPError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "results": len(found)}


# ---------- ATS board ----------


@router.get("/ats-boards", response_model=list[AtsBoardOut])
def list_boards(db: Session = Depends(get_db)):
    rows = db.scalars(select(Company).where(Company.ats_board_token.is_not(None)).order_by(Company.display_name)).all()
    return [
        AtsBoardOut(company_id=c.id, company=c.display_name, kind=c.ats_kind, token=c.ats_board_token) for c in rows
    ]


@router.post("/ats-boards", response_model=AtsBoardOut, status_code=201)
def add_board(body: AtsBoardIn, db: Session = Depends(get_db)):
    found = ats_from_url(body.url)
    if found is None:
        raise HTTPException(
            422, "请贴 Greenhouse / Lever / Ashby 的职位板网址，例如 https://job-boards.greenhouse.io/acme"
        )
    kind, token = found
    existing = db.scalar(select(Company).where(Company.ats_kind == kind, Company.ats_board_token == token))
    if existing:
        company = existing
    else:
        try:
            company = upsert_company(db, body.company.strip() or token.replace("-", " ").title())
        except IngestError as exc:
            raise HTTPException(422, str(exc)) from exc
        company.ats_kind, company.ats_board_token = kind, token
        db.flush()
    return AtsBoardOut(company_id=company.id, company=company.display_name, kind=kind, token=token)


@router.delete("/ats-boards/{company_id}", status_code=204)
def remove_board(company_id: uuid.UUID, db: Session = Depends(get_db)):
    c = db.get(Company, company_id)
    if c is None:
        raise HTTPException(404, "找不到这家公司")
    c.ats_board_token, c.ats_kind = None, "unknown"


# ---------- 搜索批次 ----------


def _sites_out(db: Session, run: SearchRun) -> list[RunSiteOut]:
    names = {s["id"]: s["name"] for s in run.params["sites"]}
    rows = {r.site_id: r for r in db.scalars(select(SearchRunSite).where(SearchRunSite.run_id == run.id))}
    snap = progress.snapshot(run.id)
    out = []
    for sid, name in names.items():
        r = rows.get(sid)
        if r is not None:
            out.append(RunSiteOut(site_id=sid, name=name, status=r.status, found_count=r.found_count,
                                  kept_count=r.kept_count, message=r.message))  # fmt: skip
        else:
            status = snap["sites"].get(sid, "searching") if snap else "searching"
            found = snap["found"].get(sid, 0) if snap else 0
            out.append(RunSiteOut(site_id=sid, name=name, status=status, found_count=found))
    return out


def _run_out(db: Session, run: SearchRun) -> dict:
    counts = dict(
        db.execute(
            select(SearchRunJob.outcome, func.count())
            .where(SearchRunJob.run_id == run.id)
            .group_by(SearchRunJob.outcome)
        ).all()
    )
    return {
        "id": run.id,
        "status": run.status,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "search_source": run.params.get("search_source"),
        "sponsor_history": run.params.get("sponsor_history", True),
        "sites": _sites_out(db, run),
        "progress": progress.snapshot(run.id),
        "counts": counts,
    }


def _get_run(db: Session, run_id: str) -> SearchRun:
    run = db.get(SearchRun, run_id)
    if run is None:
        raise HTTPException(404, "找不到这个搜索批次")
    return run


@router.post("/search-runs", response_model=SearchRunOut, status_code=201)
def start_run(body: SearchRunIn, db: Session = Depends(get_db)):
    busy = db.scalar(select(SearchRun.id).where(SearchRun.status.in_(("pending", "running"))).limit(1))
    if busy and busy in progress.active():
        raise HTTPException(409, f"批次 {busy} 还在搜索中，请等它完成或取消。")
    try:
        run = runner.create_run(db, body.site_ids, body.sponsor_history)
    except runner.RunError as exc:
        raise HTTPException(409 if "正在进行" in str(exc) else 422, str(exc)) from exc
    db.commit()
    progress.begin(run.id, [s["id"] for s in run.params["sites"]])  # 先登记，避免同时开两个
    runner.spawn(runner.execute_run, run.id)
    return SearchRunOut(**_run_out(db, run))


@router.get("/search-runs", response_model=list[SearchRunOut])
def list_runs(db: Session = Depends(get_db)):
    runs = db.scalars(select(SearchRun).order_by(SearchRun.created_at.desc()).limit(50)).all()
    return [SearchRunOut(**_run_out(db, r)) for r in runs]


@router.get("/search-runs/{run_id}", response_model=SearchRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    rows = db.execute(
        select(SearchRunJob, Job).join(Job, Job.id == SearchRunJob.job_id).where(SearchRunJob.run_id == run.id)
    ).all()
    found_on: dict[uuid.UUID, list[str]] = {}
    for job_id, site_id in db.execute(
        select(JobSource.job_id, JobSource.site_id).where(JobSource.first_seen_run_id == run.id)
    ):
        found_on.setdefault(job_id, []).append(site_id)
    prefs, _ = load_preferences(db)
    jobs = []
    for rj, job in rows:
        # 排除规则按目前的求职需求重算：改了身份（例如改成 OPT）后，旧批次也立刻反映
        outcome, codes = rj.outcome, rj.exclusion_reasons or []
        if outcome != "duplicate":
            live = check_exclusions(job, prefs)
            outcome, codes = ("excluded" if live.excluded else "kept"), live.reasons
        jobs.append(
            RunJobOut(
                **_summary(db, job),
                outcome=outcome,
                exclusion_reasons=[{"code": c, "label": REASON_LABELS.get(c, c)} for c in codes],
                found_on=sorted(set(found_on.get(job.id, []))),
            )
        )
    rank = {"kept": 0, "excluded": 1, "duplicate": 2}
    jobs.sort(
        key=lambda j: (
            rank[j.outcome],
            j.location_tier if j.location_tier is not None else 99,
            -(j.posted_at.timestamp() if j.posted_at else 0),
            -(j.score or 0),
        )
    )
    return SearchRunDetail(**_run_out(db, run), jobs=jobs)


@router.post("/search-runs/{run_id}/cancel", response_model=SearchRunOut)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    if run.status not in ("pending", "running"):
        raise HTTPException(409, "这个批次已经结束。")
    progress.cancel(run_id)
    return SearchRunOut(**_run_out(db, run))
