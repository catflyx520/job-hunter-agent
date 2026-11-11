"""search_graph：各网站并行搜索 → 读取职位页 / 抽取 → 跨来源去重 → 硬性排除 → 评分 → 签证状态 → 批次。

- 各网站用 LangGraph 的 Send 并行（fan-out）；单一网站失败不影响其他网站，失败原因写进批次。
- 批次内容在 finalize 一次写入，之后不再修改。
"""

from __future__ import annotations

import contextvars
import operator
import uuid
from collections import deque
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from itertools import zip_longest
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.fetch import FetchError
from app.core.i18n import tr
from app.llm.base import LLMError
from app.models import Company, SearchRun, SearchRunJob, SearchRunSite
from app.schemas.profile import JobPreferences
from app.search import progress
from app.search.ats import board_leads, filter_leads
from app.search.process import LeadResult, process_lead
from app.search.sites import SITE_RULES, Lead, SiteReport, clean_url
from app.search.web import get_searcher

MAX_EXTRA_ROUNDS = 2  # 线索用完还没到目标时，最多再搜几轮


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


def discover_site(site: dict[str, Any], prefs: JobPreferences, exclude: Collection[str] = ()) -> SiteReport:
    sid, limit = site["id"], site["max_results"]
    if site["access_method"] == "paste_only":
        return SiteReport(sid, "skipped", message=tr("这个网站需要登录，只支援贴网址 / JD。"))
    with get_sessionmaker()() as db:
        if site["access_method"] == "ats_api":
            boards = db.scalars(
                select(Company).where(Company.ats_kind == sid, Company.ats_board_token.is_not(None))
            ).all()
            targets = [(c.ats_board_token, c.display_name) for c in boards]
        else:
            if sid not in SITE_RULES:
                return SiteReport(sid, "skipped", message=tr("这个网站还没有搜索规则。"))
            searcher, label = get_searcher(db)
    if site["access_method"] == "ats_api":
        if not targets:
            return SiteReport(
                sid,
                "skipped",
                message=tr("还没有已知的公司 board：读过含此 ATS 链接的职位页，或在页面手动加入后才会搜索。"),
            )
        leads: list[Lead] = []
        failed = []
        for token, company in targets:
            try:
                leads += board_leads(sid, token, company)
            except FetchError as exc:
                failed.append(f"{token}（{str(exc).split('。')[0]}）")
        picked = filter_leads(leads, prefs, limit, exclude)
        msg = tr(
            "查了 {v} 个公司 board，共 {v2} 个职位，职称与地点相符 {v3} 个。",
            v=len(targets),
            v2=len(leads),
            v3=len(picked),
        )
        if failed:
            msg += tr(" 读取失败：{v}。", v="、".join(failed[:5]))
        status = "failed" if len(failed) == len(targets) else ("partial" if failed else "ok")
        return SiteReport(sid, status, picked, msg)
    if searcher is None:
        return SiteReport(sid, "skipped", message=label)
    try:
        report = searcher.search_site(sid, site["name"], prefs, limit, exclude)
    except LLMError as exc:
        return SiteReport(sid, "failed", message=tr("搜索失败：{exc}", exc=exc))
    return report


def discover(task: SiteTask) -> dict:
    run_id, site = task["run_id"], task["site"]
    if progress.is_cancelled(run_id):
        report = SiteReport(site["id"], "skipped", message=tr("搜索已取消。"))
    else:
        prefs = JobPreferences.model_validate(task["params"]["preferences"])
        try:
            report = discover_site(site, prefs)
        except Exception as exc:  # noqa: BLE001  单一网站的意外错误不影响其他网站
            report = SiteReport(
                site["id"], "failed", message=tr("搜索时发生错误（{__name__}）。", __name__=type(exc).__name__)
            )
    progress.site_done(run_id, site["id"], report.status, len(report.leads))
    return {"reports": [report]}


def interleave(reports: list[SiteReport], seen: set[str]) -> list[Lead]:
    """轮流从各网站取线索（凑够目标就停，不能都来自排在前面的网站）；同一网址只留一次，并记进 seen。"""
    out = []
    for row in zip_longest(*[r.leads for r in reports]):
        for lead in row:
            if lead is not None and clean_url(lead.url) not in seen:
                seen.add(clean_url(lead.url))
                out.append(lead)
    return out


def merge_reports(reports: list[SiteReport]) -> list[SiteReport]:
    """补搜的结果并回第一次的报告：每个网站只写一笔。"""
    merged: dict[str, SiteReport] = {}
    for r in reports:
        if r.site_id in merged:
            merged[r.site_id] = replace(merged[r.site_id], leads=merged[r.site_id].leads + r.leads)
        else:
            merged[r.site_id] = r
    return list(merged.values())


def process(state: SearchState) -> dict:
    run_id, params = state["run_id"], state["params"]
    prefs = JobPreferences.model_validate(params["preferences"])
    order = {s["id"]: i for i, s in enumerate(params["sites"])}
    reports = sorted(state.get("reports", []), key=lambda r: order.get(r.site_id, 999))

    target, cap = params.get("target_jobs", params["total_limit"]), params["total_limit"]
    workers = max(1, get_settings().cli_max_concurrency)
    seen: set[str] = set()
    queue = deque(interleave(reports, seen))
    results: list[LeadResult] = []
    extra: list[SiteReport] = []
    kept: set[str] = set()  # 一个职位可能从两个网站找到，按职位算
    checked = rounds = 0
    progress.start_processing(run_id, target)

    def work(lead: Lead) -> LeadResult:
        if progress.is_cancelled(run_id):
            return LeadResult(lead.site_id, lead.url, "cancelled", message=tr("搜索已取消"))
        try:
            res = process_lead(run_id, lead, prefs, params.get("sponsor_history", True))
        except Exception as exc:  # noqa: BLE001
            res = LeadResult(
                lead.site_id,
                lead.url,
                "failed",
                message=tr("处理时发生错误（{__name__}）", __name__=type(exc).__name__),
            )
        progress.lead_done(run_id, res.outcome)
        return res

    def run_all(pool: ThreadPoolExecutor, fn, items) -> list:
        # context 要在这里（发起的执行绪）复制，工作执行绪才拿得到介面语言
        return [f.result() for f in [pool.submit(contextvars.copy_context().run, fn, x) for x in items]]

    def rediscover(site: dict[str, Any]) -> SiteReport:
        try:
            return discover_site(site, prefs, seen)
        except Exception:  # noqa: BLE001  补搜失败不影响已经找到的职位
            return SiteReport(site["id"], "failed")

    searchable = [
        s for s in params["sites"] if s["id"] in {r.site_id for r in reports if r.status in ("ok", "partial")}
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while not progress.is_cancelled(run_id):
            # 一批不超过还缺的数量，才不会多找；被排除的不算，下一批补上
            while queue and len(kept) < target and checked < cap and not progress.is_cancelled(run_id):
                batch = [queue.popleft() for _ in range(min(workers, target - len(kept), cap - checked, len(queue)))]
                done = run_all(pool, work, batch)
                results += done
                checked += len(batch)
                kept |= {r.job_id for r in done if r.outcome == "kept" and r.job_id}
                progress.set_kept(run_id, len(kept))
            if len(kept) >= target or checked >= cap or rounds >= MAX_EXTRA_ROUNDS or not searchable:
                break
            rounds += 1
            more = [r for r in run_all(pool, rediscover, searchable) if r.leads]
            for r in more:
                progress.site_more(run_id, r.site_id, len(r.leads))
            fresh = interleave(more, seen)
            if not fresh:
                break
            extra += more
            queue.extend(fresh)

    # 没处理到的线索：写进各网站的说明
    if progress.is_cancelled(run_id):
        left = ("cancelled", tr("搜索已取消"))
    elif len(kept) >= target:
        left = ("not_needed", tr("已达到目标数量"))
    else:
        left = ("over_limit", tr("超过每次搜索的总上限"))
    results += [LeadResult(lead.site_id, lead.url, left[0], message=left[1]) for lead in queue]
    return {"results": results, "reports": extra}


OUTCOME_RANK = {"kept": 0, "excluded": 1, "duplicate": 2}


def site_summary(report: SiteReport, results: list[LeadResult], kept_jobs: set[str]) -> tuple[str, int, str]:
    """依读取结果调整网站状态，并写出给用户看的说明。回传 (状态, 保留数, 说明)。"""
    mine = [r for r in results if r.site_id == report.site_id]
    count = {k: sum(1 for r in mine if r.outcome == k) for k in
             ("kept", "excluded", "duplicate", "blocked", "failed", "expired", "cancelled", "over_limit", "not_needed")}  # fmt: skip
    kept = len({r.job_id for r in mine if r.outcome == "kept" and r.job_id in kept_jobs})
    parts = [report.message] if report.message else []
    if mine:
        found = tr("找到 {v} 个职位页", v=len(report.leads))
        detail = [tr("保留 {kept}", kept=kept)]
        for key, label in (("excluded", tr("排除")), ("duplicate", tr("之前批次已有")), ("blocked", tr("读不到（登录/验证页）")),
                           ("expired", tr("已下架")), ("failed", tr("失败")), ("over_limit", tr("超过总上限未处理")),
                           ("cancelled", tr("取消")), ("not_needed", tr("已达到目标，未处理"))):  # fmt: skip
            if count[key]:
                detail.append(f"{label} {count[key]}")
        parts.append(f"{found}：{'、'.join(detail)}。")
        fails = [r for r in mine if r.outcome in ("blocked", "failed", "expired") and r.message]
        if fails:
            parts.append(tr("例如：{message}。", message=fails[0].message))
        unread_urls = [r.url for r in mine if r.outcome in ("blocked", "failed")]
        if unread_urls:
            parts.append(tr("读不到的职位页（可自行打开后贴 JD）：") + " ".join(unread_urls[:8]))
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
        for report in merge_reports(state.get("reports", [])):
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
