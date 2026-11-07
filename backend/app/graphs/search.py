"""search_graph（SPEC 4.2）：各网站并行搜索 → 读取职位页 / 抽取 → 跨来源去重 → 硬性排除 → 评分 → 签证状态 → 批次。

- 各网站用 LangGraph 的 Send 并行（fan-out）；单一网站失败不影响其他网站，失败原因写进批次。
- 批次内容在 finalize 一次写入，之后不再修改。
"""

from __future__ import annotations

import operator
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.fetch import FetchError
from app.llm.base import LLMError
from app.models import Company, SearchRun, SearchRunJob, SearchRunSite
from app.schemas.profile import JobPreferences
from app.search import progress
from app.search.ats import board_leads, filter_leads
from app.search.process import LeadResult, process_lead
from app.search.sites import SITE_RULES, Lead, SiteReport, clean_url
from app.search.web import get_searcher


class SearchState(TypedDict, total=False):
    run_id: str
    params: dict[str, Any]
    reports: Annotated[list[SiteReport], operator.add]
    results: list[LeadResult]


class SiteTask(TypedDict):
    run_id: str
    params: dict[str, Any]
    site: dict[str, Any]


# ---------- 节点 ----------


def fan_out(state: SearchState):
    sites = state["params"]["sites"]
    if not sites:
        return "process"
    return [Send("discover", {"run_id": state["run_id"], "params": state["params"], "site": s}) for s in sites]


def discover_site(site: dict[str, Any], prefs: JobPreferences) -> SiteReport:
    sid, limit = site["id"], site["max_results"]
    if site["access_method"] == "paste_only":
        return SiteReport(sid, "skipped", message="这个网站需要登录，只支援贴网址 / JD。")
    with get_sessionmaker()() as db:
        if site["access_method"] == "ats_api":
            boards = db.scalars(
                select(Company).where(Company.ats_kind == sid, Company.ats_board_token.is_not(None))
            ).all()
            targets = [(c.ats_board_token, c.display_name) for c in boards]
        else:
            if sid not in SITE_RULES:
                return SiteReport(sid, "skipped", message="这个网站还没有搜索规则。")
            searcher, label = get_searcher(db)
    if site["access_method"] == "ats_api":
        if not targets:
            return SiteReport(
                sid,
                "skipped",
                message="还没有已知的公司 board：读过含此 ATS 链接的职位页，或在页面手动加入后才会搜索。",
            )
        leads: list[Lead] = []
        failed = []
        for token, company in targets:
            try:
                leads += board_leads(sid, token, company)
            except FetchError as exc:
                failed.append(f"{token}（{str(exc).split('。')[0]}）")
        picked = filter_leads(leads, prefs, limit)
        msg = f"查了 {len(targets)} 个公司 board，共 {len(leads)} 个职位，职称与地点相符 {len(picked)} 个。"
        if failed:
            msg += f" 读取失败：{'、'.join(failed[:5])}。"
        status = "failed" if len(failed) == len(targets) else ("partial" if failed else "ok")
        return SiteReport(sid, status, picked, msg)
    if searcher is None:
        return SiteReport(sid, "skipped", message=label)
    try:
        report = searcher.search_site(sid, site["name"], prefs, limit)
    except LLMError as exc:
        return SiteReport(sid, "failed", message=f"搜索失败：{exc}")
    return report


def discover(task: SiteTask) -> dict:
    run_id, site = task["run_id"], task["site"]
    if progress.is_cancelled(run_id):
        report = SiteReport(site["id"], "skipped", message="搜索已取消。")
    else:
        prefs = JobPreferences.model_validate(task["params"]["preferences"])
        try:
            report = discover_site(site, prefs)
        except Exception as exc:  # noqa: BLE001  单一网站的意外错误不影响其他网站
            report = SiteReport(site["id"], "failed", message=f"搜索时发生错误（{type(exc).__name__}）。")
    progress.site_done(run_id, site["id"], report.status, len(report.leads))
    return {"reports": [report]}


def process(state: SearchState) -> dict:
    run_id, params = state["run_id"], state["params"]
    prefs = JobPreferences.model_validate(params["preferences"])
    order = {s["id"]: i for i, s in enumerate(params["sites"])}
    reports = sorted(state.get("reports", []), key=lambda r: order.get(r.site_id, 999))

    # 同一网址只处理一次；超过总上限的不处理
    queue: list[Lead] = []
    results: list[LeadResult] = []
    seen: set[str] = set()
    for r in reports:
        for lead in r.leads:
            key = clean_url(lead.url)
            if key in seen:
                continue
            seen.add(key)
            if len(queue) >= params["total_limit"]:
                results.append(LeadResult(lead.site_id, lead.url, "over_limit", message="超过每次搜索的总上限"))
            else:
                queue.append(lead)
    progress.start_processing(run_id, len(queue))

    def work(lead: Lead) -> LeadResult:
        if progress.is_cancelled(run_id):
            return LeadResult(lead.site_id, lead.url, "cancelled", message="搜索已取消")
        try:
            res = process_lead(run_id, lead, prefs, params.get("sponsor_history", True))
        except Exception as exc:  # noqa: BLE001
            res = LeadResult(lead.site_id, lead.url, "failed", message=f"处理时发生错误（{type(exc).__name__}）")
        progress.lead_done(run_id, res.outcome)
        return res

    with ThreadPoolExecutor(max_workers=max(1, get_settings().cli_max_concurrency)) as pool:
        results += list(pool.map(work, queue))
    return {"results": results}


OUTCOME_RANK = {"kept": 0, "excluded": 1, "duplicate": 2}


def site_summary(report: SiteReport, results: list[LeadResult], kept_jobs: set[str]) -> tuple[str, int, str]:
    """依读取结果调整网站状态，并写出给用户看的说明。回传 (状态, 保留数, 说明)。"""
    mine = [r for r in results if r.site_id == report.site_id]
    count = {k: sum(1 for r in mine if r.outcome == k) for k in
             ("kept", "excluded", "duplicate", "blocked", "failed", "expired", "cancelled", "over_limit")}  # fmt: skip
    kept = len({r.job_id for r in mine if r.outcome == "kept" and r.job_id in kept_jobs})
    parts = [report.message] if report.message else []
    if mine:
        found = f"找到 {len(report.leads)} 个职位页"
        detail = [f"保留 {kept}"]
        for key, label in (("excluded", "排除"), ("duplicate", "之前批次已有"), ("blocked", "读不到（登录/验证页）"),
                           ("expired", "已下架"), ("failed", "失败"), ("over_limit", "超过总上限未处理"),
                           ("cancelled", "取消")):  # fmt: skip
            if count[key]:
                detail.append(f"{label} {count[key]}")
        parts.append(f"{found}：{'、'.join(detail)}。")
        fails = [r for r in mine if r.outcome in ("blocked", "failed", "expired") and r.message]
        if fails:
            parts.append(f"例如：{fails[0].message}。")
        unread_urls = [r.url for r in mine if r.outcome in ("blocked", "failed")]
        if unread_urls:
            parts.append("读不到的职位页（可自行打开后贴 JD）：" + " ".join(unread_urls[:8]))
    status = report.status
    if status == "ok" and mine:
        unread = count["blocked"] + count["failed"]
        if unread == len(mine) and count["blocked"]:
            status = "blocked"
        elif unread == len(mine):
            status = "failed"
        elif unread or count["cancelled"]:
            status = "partial"
    return status, kept, " ".join(parts).strip()


def finalize(state: SearchState) -> dict:
    run_id = state["run_id"]
    results = state.get("results", [])
    # 一个职位在批次里只有一行：同时被多个网站找到时取「保留」优先
    by_job: dict[str, LeadResult] = {}
    for r in results:
        if r.job_id and r.outcome in OUTCOME_RANK:
            cur = by_job.get(r.job_id)
            if cur is None or OUTCOME_RANK[r.outcome] < OUTCOME_RANK[cur.outcome]:
                by_job[r.job_id] = r
    kept_jobs = {j for j, r in by_job.items() if r.outcome == "kept"}
    with get_sessionmaker()() as db:
        run = db.get(SearchRun, run_id)
        for report in state.get("reports", []):
            status, kept, msg = site_summary(report, results, kept_jobs)
            db.add(
                SearchRunSite(
                    run_id=run_id,
                    site_id=report.site_id,
                    status=status,
                    found_count=min(len(report.leads), 32767),
                    kept_count=kept,
                    message=msg[:2000] or None,
                )
            )
        for job_id, r in by_job.items():
            db.add(
                SearchRunJob(
                    run_id=run_id, job_id=uuid.UUID(job_id), outcome=r.outcome, exclusion_reasons=r.reasons or None
                )
            )
        run.status = "cancelled" if progress.is_cancelled(run_id) else "completed"
        run.finished_at = datetime.now(UTC)
        db.commit()
    progress.finish(run_id)
    return {}


def build_graph():
    g = StateGraph(SearchState)
    g.add_node("discover", discover)
    g.add_node("process", process)
    g.add_node("finalize", finalize)
    g.add_conditional_edges(START, fan_out, ["discover", "process"])
    g.add_edge("discover", "process")
    g.add_edge("process", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
