"""F5 统计页：从 v_job_overview 等 view 计算，不另存资料。所有维度都能下钻到职位清单。"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.jobs import _summary
from app.core.db import get_db
from app.core.i18n import tr
from app.jobs.exclusion import REASON_LABELS
from app.models import Job, JobSite, SearchRun
from app.schemas.job import JobSummary

router = APIRouter(prefix="/api", tags=["stats"])

SUBMITTED = ("applied", "interviewing", "offer", "rejected", "ghosted")
REPLIED = ("interviewing", "offer", "rejected")
STALE_DAYS = 14

SALARY_BUCKETS = [(0, 80_000, "< $80k"), (80_000, 100_000, "$80k–100k"), (100_000, 130_000, "$100k–130k"),
                  (130_000, 160_000, "$130k–160k"), (160_000, 200_000, "$160k–200k"), (200_000, 10**9, "≥ $200k")]  # fmt: skip
SCORE_BUCKETS = [(0, 40, "0–39"), (40, 55, "40–54"), (55, 75, "55–74"), (75, 101, "75–100")]


class Filters:
    def __init__(
        self,
        company: uuid.UUID | None = None,
        site: str | None = None,
        run: str | None = None,
        location_tier: str | None = None,
        work_mode: str | None = None,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ):
        self.company, self.site, self.run = company, site, run
        self.location_tier, self.work_mode, self.status = location_tier, work_mode, status
        self.date_from, self.date_to = date_from, date_to


def _rows(db: Session, f: Filters) -> list[dict[str, Any]]:
    rows = [dict(r._mapping) for r in db.execute(text("SELECT * FROM v_job_overview"))]
    out = []
    for r in rows:
        if f.company and r["company_id"] != f.company:
            continue
        if f.site and f.site not in r["sites"]:
            continue
        if f.run and f.run not in r["run_ids"]:
            continue
        if f.location_tier and _tier(r) != f.location_tier:
            continue
        if f.work_mode and r["work_mode"] != f.work_mode:
            continue
        if f.status and r["application_status"] != f.status:
            continue
        created = r["created_at"].date()
        if f.date_from and created < f.date_from:
            continue
        if f.date_to and created > f.date_to:
            continue
        out.append(r)
    return out


def _tier(r) -> str:
    return str(r["location_tier"]) if r["location_tier"] is not None else "none"


def _bucket(value: int | None, buckets) -> str:
    if value is None:
        return "unknown"
    return next((label for lo, hi, label in buckets if lo <= value < hi), "unknown")


def _reasons(r) -> set[str]:
    return set(r["run_exclusion_reasons"] or []) | set(r["match_exclusion_reasons"] or [])


def _easy(r) -> str:
    return "unknown" if r["easy_apply"] is None else ("yes" if r["easy_apply"] else "no")


# 下钻：维度 → 判断函数
DIMENSIONS: dict[str, Callable[[dict, str], bool]] = {
    "all": lambda r, v: True,
    "application_status": lambda r, v: r["application_status"] == v,
    "stage": lambda r, v: _in_stage(r, v),
    "sponsorship_policy": lambda r, v: r["sponsorship_policy"] == v,
    "sponsor_status": lambda r, v: (r["sponsor_status"] or "not_checked") == v,
    "location_tier": lambda r, v: _tier(r) == v,
    "work_mode": lambda r, v: r["work_mode"] == v,
    "exclusion": lambda r, v: v in _reasons(r),
    "site": lambda r, v: v in r["sites"],
    "easy_apply": lambda r, v: _easy(r) == v,
    "salary": lambda r, v: _bucket(r["salary_max_annual"] or r["salary_min_annual"], SALARY_BUCKETS) == v,
    "score": lambda r, v: (_bucket(r["score"], SCORE_BUCKETS) if r["score"] is not None else "none") == v,
    "recommendation": lambda r, v: (r["recommendation"] or "none") == v,
    "backlog": lambda r, v: _backlog(r) == v,
}

STAGES = [
    ("found", "搜索到", lambda r: True),
    ("saved", "收藏以上", lambda r: r["application_status"] not in ("none", "dismissed")),
    ("applied", "已投递", lambda r: r["application_status"] in SUBMITTED),
    ("interviewing", "面试", lambda r: r["application_status"] in ("interviewing", "offer")),
    ("offer", "Offer", lambda r: r["application_status"] == "offer"),
]


def _in_stage(r, stage: str) -> bool:
    return next((fn(r) for key, _, fn in STAGES if key == stage), False)


def _backlog(r) -> str | None:
    if r["application_status"] == "saved":
        return "saved_not_applied"
    if r["application_status"] == "applied" and r["application_updated_at"]:
        if datetime.now(UTC) - r["application_updated_at"] > timedelta(days=STALE_DAYS):
            return "applied_no_update"
    return None


def _count(rows, key: Callable[[dict], str]) -> dict[str, int]:
    return dict(Counter(key(r) for r in rows).most_common())


def _trend(db: Session, job_ids: set, unit: str) -> list[dict[str, Any]]:
    if not job_ids:
        return []
    rows = db.execute(
        text(
            "SELECT date_trunc(:unit, e.at) AS bucket, e.to_status, count(*) AS n "
            "FROM application_events e JOIN applications a ON a.id = e.application_id "
            "WHERE a.job_id = ANY(:ids) GROUP BY 1, 2 ORDER BY 1"
        ),
        {"unit": unit, "ids": list(job_ids)},
    )
    out: dict[str, dict[str, Any]] = {}
    for bucket, status, n in rows:
        key = bucket.date().isoformat()
        item = out.setdefault(key, {"date": key, "applied": 0, "interviewing": 0, "other": 0})
        item["applied" if status == "applied" else "interviewing" if status == "interviewing" else "other"] += n
    if not out:
        return []
    # 补上没有变更的日期 / 周，让时间轴连续
    step = timedelta(days=7 if unit == "week" else 1)
    cur, last = date.fromisoformat(min(out)), date.fromisoformat(max(out))
    filled = []
    while cur <= last:
        key = cur.isoformat()
        filled.append(out.get(key, {"date": key, "applied": 0, "interviewing": 0, "other": 0}))
        cur += step
    return filled


def _filters(
    company: uuid.UUID | None = None,
    site: str | None = None,
    run: str | None = None,
    location_tier: str | None = None,
    work_mode: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Filters:
    return Filters(company, site, run, location_tier, work_mode, status, date_from, date_to)


@router.get("/stats")
def stats(f: Filters = Depends(_filters), db: Session = Depends(get_db)):
    rows = _rows(db, f)
    status = _count(rows, lambda r: r["application_status"])
    submitted = sum(status.get(s, 0) for s in SUBMITTED)
    replied = sum(status.get(s, 0) for s in REPLIED)

    sources: dict[str, dict[str, int]] = {}
    for r in rows:
        for site in r["sites"] or ["(无来源链接)"]:
            s = sources.setdefault(site, {"found": 0, "kept": 0, "applied": 0, "interviews": 0})
            s["found"] += 1
            s["kept"] += r["first_outcome"] == "kept"
            s["applied"] += r["application_status"] in SUBMITTED
            s["interviews"] += r["application_status"] in ("interviewing", "offer")
    site_names = dict(db.execute(select(JobSite.id, JobSite.name)).all())

    exclusions = Counter(reason for r in rows for reason in _reasons(r))
    salary_dir = [
        {"company": r["company"], "title": r["title"], "min": r["salary_min_annual"], "max": r["salary_max_annual"],
         "score": r["score"]}
        for r in rows if r["salary_max_annual"] or r["salary_min_annual"]
    ]  # fmt: skip
    job_ids = {r["job_id"] for r in rows}
    return {
        "totals": {
            "found": len(rows),
            "saved": status.get("saved", 0),
            "submitted": submitted,
            "interviewing": status.get("interviewing", 0),
            "offer": status.get("offer", 0),
            "rejected": status.get("rejected", 0),
            "ghosted": status.get("ghosted", 0),
            "dismissed": status.get("dismissed", 0),
            "reply_rate": round(replied / submitted, 3) if submitted else None,
        },
        "funnel": [{"stage": k, "label": label, "count": sum(1 for r in rows if fn(r))} for k, label, fn in STAGES],
        "application_status": status,
        "sponsorship_policy": _count(rows, lambda r: r["sponsorship_policy"]),
        "sponsor_status": _count(rows, lambda r: r["sponsor_status"] or "not_checked"),
        "location_tier": _count(rows, _tier),
        "work_mode": _count(rows, lambda r: r["work_mode"]),
        "exclusions": [{"code": c, "label": REASON_LABELS.get(c, c), "count": n} for c, n in exclusions.most_common()],
        "sources": [
            {"site": k, "name": site_names.get(k, k), **v}
            for k, v in sorted(sources.items(), key=lambda kv: -kv[1]["found"])
        ],
        "easy_apply": _count(rows, _easy),
        "salary": _count(rows, lambda r: _bucket(r["salary_max_annual"] or r["salary_min_annual"], SALARY_BUCKETS)),
        "salary_points": salary_dir[:500],
        "score": _count(rows, lambda r: _bucket(r["score"], SCORE_BUCKETS) if r["score"] is not None else "none"),
        "recommendation": _count(rows, lambda r: r["recommendation"] or "none"),
        "trend": {"day": _trend(db, job_ids, "day"), "week": _trend(db, job_ids, "week")},
        "backlog": {
            "saved_not_applied": sum(1 for r in rows if _backlog(r) == "saved_not_applied"),
            "applied_no_update": sum(1 for r in rows if _backlog(r) == "applied_no_update"),
            "stale_days": STALE_DAYS,
        },
    }


@router.get("/stats/options")
def stats_options(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT DISTINCT company_id, company FROM v_job_overview ORDER BY company")).all()
    return {
        "companies": [{"id": str(cid), "name": name} for cid, name in rows],
        "sites": [
            {"id": i, "name": n} for i, n in db.execute(select(JobSite.id, JobSite.name).order_by(JobSite.sort_order))
        ],
        "runs": list(db.scalars(select(SearchRun.id).order_by(SearchRun.created_at.desc()).limit(100))),
    }


@router.get("/stats/jobs", response_model=list[JobSummary])
def drill_down(
    dim: str = Query("all"),
    value: str = Query(""),
    f: Filters = Depends(_filters),
    db: Session = Depends(get_db),
):
    pred = DIMENSIONS.get(dim)
    if pred is None:
        raise HTTPException(422, tr("不支援的维度"))
    ids = [r["job_id"] for r in _rows(db, f) if pred(r, value)][:500]
    jobs = db.scalars(select(Job).where(Job.id.in_(ids))).all() if ids else []
    order = {i: n for n, i in enumerate(ids)}
    return [JobSummary(**_summary(db, j)) for j in sorted(jobs, key=lambda j: order[j.id])]
