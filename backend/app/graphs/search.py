"""search_graph：读已知公司 board → 边搜索边读取职位页 / 抽取 → 跨来源去重 → 硬性排除 → 评分 → 签证状态 → 批次。

- 第一步用 LangGraph 的 Send 并行（fan-out）读已知的公司 board（公开 API，不用模型，很快），这些职位先处理。
- 要用模型搜索的部分（找新公司、LinkedIn 等网站）和处理同时进行：哪个网站先搜完就先处理，不等全部搜完。
- 处理完一个职位就写进批次，页面马上看得到；批次完成后内容不再修改。
- 单一网站失败不影响其他网站，失败原因写进批次。
"""

from __future__ import annotations

import contextvars
import operator
import uuid
from collections import deque
from collections.abc import Collection
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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
from app.jobs.service import IngestError, upsert_company
from app.llm.base import LLMError
from app.models import Company, SearchRun, SearchRunJob, SearchRunSite
from app.schemas.profile import JobPreferences
from app.search import progress
from app.search.ats import board_leads, filter_leads
from app.search.browser import browser_enabled
from app.search.linkedin import browser_leads
from app.search.process import SAVE_LOCK, LeadResult, process_lead
from app.search.sites import SITE_RULES, Lead, SiteReport, clean_url
from app.search.web import Searcher, get_searcher

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
    sites = [s for s in state["params"]["sites"] if s["access_method"] == "ats_api"]
    if not sites:
        return "process"
    return [Send("discover", {"run_id": state["run_id"], "params": state["params"], "site": s}) for s in sites]


def discover_boards(
    site: dict[str, Any],
    prefs: JobPreferences,
    exclude: Collection[str],
    searcher: Searcher | None,
    known: list[tuple[str, str]],
    part: str = "all",
) -> SiteReport:
    """公司招聘板：先用搜索找出还不认识的公司，再从公开 API 读每家公司的职位。known 是已知的 (board 名, 公司名)。

    part：known 只读已知的 board（不用模型）；search 只找新公司并读它们的 board；all 两样都做。
    """
    sid, limit = site["id"], site["max_results"]
    new: dict[str, str] = {}  # 搜索找到、还不认识的 board 名 → 公司名
    note = ""
    # shortcut: 只在第一轮找新公司，补搜只重读已知的 board；已知的 board 常被读完时改成每轮都找
    if part != "known" and searcher is not None and not exclude:
        seen = {token.lower() for token, _ in known}
        try:
            for lead in searcher.search_site(sid, site["name"], prefs, limit).leads:
                token = lead.site_job_id or ""
                if token.lower() not in seen:
                    seen.add(token.lower())
                    new[token] = lead.company or token.replace("-", " ").title()
        except LLMError as exc:
            note = tr("搜索新公司失败：{exc}", exc=exc)
    leads: list[Lead] = []
    failed, added = [], []
    base = [] if part == "search" else known
    for token, company in [*base, *new.items()]:
        try:
            got = board_leads(sid, token, company)
        except FetchError as exc:
            if token not in new:  # 新找到但读不到的不记下来，也不算失败
                failed.append(f"{token}（{str(exc).split('。')[0]}）")
            continue
        leads += got
        if token in new and got:
            added.append((token, company))
    if added:
        with SAVE_LOCK, get_sessionmaker()() as db:  # 几个网站同时搜索，可能找到同一家公司
            for token, name in added:
                try:
                    company = upsert_company(db, name)
                except IngestError:
                    continue
                if not company.ats_board_token:
                    company.ats_kind, company.ats_board_token = sid, token
            db.commit()
    if not base and not added:
        no_boards = tr("还没有已知的公司 board：读过含此 ATS 链接的职位页，或在页面手动加入后才会搜索。")
        not_found = note or tr("搜索没有找到使用 {name} 的公司。", name=site["name"])
        if part == "known":  # 有搜索来源时，由 search 那一份说明结果
            msg = no_boards if searcher is None else ""
        elif part == "search":
            msg = "" if searcher is None else (note if known else not_found)
        else:
            msg = no_boards if searcher is None else not_found
        return SiteReport(sid, "skipped", message=msg)
    picked = filter_leads(leads, prefs, limit, exclude)
    msg = tr(
        "查了 {v} 个公司 board，共 {v2} 个职位，职称与地点相符 {v3} 个。",
        v=len(base) + len(added),
        v2=len(leads),
        v3=len(picked),
    )
    if added:
        msg = tr("搜索找到 {n} 家新公司。", n=len(added)) + " " + msg
    if note:
        msg += " " + note
    if failed:
        msg += tr(" 读取失败：{v}。", v="、".join(failed[:5]))
    status = "failed" if len(failed) == len(base) + len(added) else ("partial" if failed else "ok")
    return SiteReport(sid, status, picked, msg)


def discover_site(
    site: dict[str, Any],
    prefs: JobPreferences,
    exclude: Collection[str] = (),
    part: str = "all",
    run_id: str | None = None,
) -> SiteReport:
    """part 只影响公司招聘板（见 discover_boards）；其他网站整个搜索都要用模型，不分段。

    run_id：登录浏览器等用户处理验证时，用来显示提示与响应取消。
    """
    sid, limit = site["id"], site["max_results"]
    if site["access_method"] == "paste_only":
        return SiteReport(sid, "skipped", message=tr("这个网站需要登录，只支援贴网址 / JD。"))
    if site["access_method"] == "browser":
        with get_sessionmaker()() as db:
            enabled = browser_enabled(db)
        if not enabled:
            return SiteReport(
                sid, "skipped", message=tr("登录浏览器没有开启：请到设定页开启，或把这个网站改回网页搜索。")
            )
        return browser_leads(run_id, site, prefs, exclude)
    if sid not in SITE_RULES:
        return SiteReport(sid, "skipped", message=tr("这个网站还没有搜索规则。"))
    with get_sessionmaker()() as db:
        searcher, label = get_searcher(db)
        if site["access_method"] == "ats_api":
            boards = db.scalars(
                select(Company).where(Company.ats_kind == sid, Company.ats_board_token.is_not(None))
            ).all()
            known = [(c.ats_board_token, c.display_name) for c in boards]
    if site["access_method"] == "ats_api":
        return discover_boards(site, prefs, exclude, searcher, known, part)
    if searcher is None:
        return SiteReport(sid, "skipped", message=label)
    try:
        report = searcher.search_site(sid, site["name"], prefs, limit, exclude)
    except LLMError as exc:
        return SiteReport(sid, "failed", message=tr("搜索失败：{exc}", exc=exc))
    return report


def safe_discover(run_id: str, site: dict[str, Any], prefs: JobPreferences, part: str) -> SiteReport:
    """单一网站的意外错误不影响其他网站。"""
    if progress.is_cancelled(run_id):
        return SiteReport(site["id"], "skipped", message=tr("搜索已取消。"))
    try:
        return discover_site(site, prefs, part=part, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return SiteReport(
            site["id"], "failed", message=tr("搜索时发生错误（{__name__}）。", __name__=type(exc).__name__)
        )


def discover(task: SiteTask) -> dict:
    """只读已知的公司 board：很快，这些职位先处理。这个网站还要再找新公司，所以状态仍是搜索中。"""
    run_id, site = task["run_id"], task["site"]
    prefs = JobPreferences.model_validate(task["params"]["preferences"])
    report = safe_discover(run_id, site, prefs, "known")
    progress.site_more(run_id, site["id"], len(report.leads))
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
    """同一个网站的几份报告（已知 board、模型搜索、补搜）并成一笔：每个网站只写一笔。

    skipped 的那份只补说明，不改状态；两份状态不同就是 partial。
    """
    merged: dict[str, SiteReport] = {}
    for r in reports:
        cur = merged.get(r.site_id)
        if cur is None:
            merged[r.site_id] = r
            continue
        if "skipped" in (cur.status, r.status):
            status = r.status if cur.status == "skipped" else cur.status
        else:
            status = cur.status if cur.status == r.status else "partial"
        message = " ".join(m for m in dict.fromkeys((cur.message, r.message)) if m)
        merged[r.site_id] = replace(cur, status=status, leads=cur.leads + r.leads, message=message)
    return list(merged.values())


OUTCOME_RANK = {"kept": 0, "excluded": 1, "duplicate": 2}


def record_result(run_id: str, res: LeadResult) -> None:
    """处理完一个就写进批次：页面不用等整批搜完才看得到。同一职位被几个网站找到时，留「保留」优先的那个结果。"""
    if not res.job_id or res.outcome not in OUTCOME_RANK:
        return
    job_id = uuid.UUID(res.job_id)
    with SAVE_LOCK, get_sessionmaker()() as db:
        row = db.get(SearchRunJob, (run_id, job_id))
        if row is None:
            db.add(
                SearchRunJob(run_id=run_id, job_id=job_id, outcome=res.outcome, exclusion_reasons=res.reasons or None)
            )
        elif OUTCOME_RANK[res.outcome] < OUTCOME_RANK[row.outcome]:
            row.outcome, row.exclusion_reasons = res.outcome, res.reasons or None
        db.commit()


def process(state: SearchState) -> dict:
    run_id, params = state["run_id"], state["params"]
    prefs = JobPreferences.model_validate(params["preferences"])
    order = {s["id"]: i for i, s in enumerate(params["sites"])}
    first = sorted(state.get("reports", []), key=lambda r: order.get(r.site_id, 999))  # 已知公司 board 的职位

    target, cap = params.get("target_jobs", params["total_limit"]), params["total_limit"]
    workers = max(1, get_settings().cli_max_concurrency)
    seen: set[str] = set()
    queue = deque(interleave(first, seen))
    results: list[LeadResult] = []
    found: list[SiteReport] = []  # 这个节点里搜到的
    kept: set[str] = set()  # 一个职位可能从两个网站找到，按职位算
    checked = rounds = 0
    progress.start_processing(run_id, target)

    def work(lead: Lead) -> LeadResult:
        if progress.is_cancelled(run_id):
            return LeadResult(lead.site_id, lead.url, "cancelled", message=tr("搜索已取消"))
        try:
            res = process_lead(run_id, lead, prefs, params.get("sponsor_history", True))
            record_result(run_id, res)
        except Exception as exc:  # noqa: BLE001
            res = LeadResult(
                lead.site_id,
                lead.url,
                "failed",
                message=tr("处理时发生错误（{__name__}）", __name__=type(exc).__name__),
            )
        progress.lead_done(run_id, res.outcome)
        return res

    def submit(pool: ThreadPoolExecutor, fn, *args) -> Future:
        # context 要在这里（发起的执行绪）复制，工作执行绪才拿得到介面语言
        return pool.submit(contextvars.copy_context().run, fn, *args)

    def run_all(pool: ThreadPoolExecutor, fn, items) -> list:
        return [f.result() for f in [submit(pool, fn, x) for x in items]]

    def rediscover(site: dict[str, Any]) -> SiteReport:
        try:
            return discover_site(site, prefs, seen)
        except Exception:  # noqa: BLE001  补搜失败不影响已经找到的职位
            return SiteReport(site["id"], "failed")

    def site_status(site_id: str) -> str:
        return merge_reports([r for r in [*first, *found] if r.site_id == site_id])[0].status

    # 要用模型搜索的部分和处理同时进行。本机 CLI 的并行名额有限，搜索只占一部分，其余留给读取与评分；
    # 公司招聘板排前面（找新公司），LinkedIn 等网站在后；登录浏览器可能要等用户处理验证，排最后才不会挡住别的网站。
    finder = ThreadPoolExecutor(max_workers=max(1, workers - 1), thread_name_prefix="site-search")
    speed = ("ats_api", "web_search", "browser")
    by_speed = sorted(params["sites"], key=lambda s: speed.index(s["access_method"]))
    pending = {submit(finder, safe_discover, run_id, s, prefs, "search"): s for s in by_speed}

    def collect(block: bool) -> None:
        """收下已经搜完的网站，线索排进队列。block：最多等 2 秒（期间仍能响应取消）。"""
        if not pending:
            return
        finished = wait(pending, timeout=2 if block else 0, return_when=FIRST_COMPLETED)[0]
        reports = [f.result() for f in list(pending) if f in finished]  # 照送出的顺序，结果才固定
        for f in finished:
            del pending[f]
        found.extend(reports)
        for r in reports:
            progress.site_done(run_id, r.site_id, site_status(r.site_id), len(r.leads))
        queue.extend(interleave(reports, seen))

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while not progress.is_cancelled(run_id):
                collect(block=False)
                if len(kept) >= target or checked >= cap:
                    break
                if queue:
                    # 一批不超过还缺的数量，才不会多找；被排除的不算，下一批补上
                    size = min(workers, target - len(kept), cap - checked, len(queue))
                    done = run_all(pool, work, [queue.popleft() for _ in range(size)])
                    results += done
                    checked += size
                    kept |= {r.job_id for r in done if r.outcome == "kept" and r.job_id}
                    progress.set_kept(run_id, len(kept))
                    continue
                if pending:
                    collect(block=True)
                    continue
                # 都搜完、线索也用完了还没到目标：再搜几轮
                again = [s for s in params["sites"] if site_status(s["id"]) in ("ok", "partial")]
                if rounds >= MAX_EXTRA_ROUNDS or not again:
                    break
                rounds += 1
                more = [r for r in run_all(pool, rediscover, again) if r.leads]
                for r in more:
                    progress.site_more(run_id, r.site_id, len(r.leads))
                fresh = interleave(more, seen)
                if not fresh:
                    break
                # 补搜只补线索，不改网站的状态与说明
                found += [replace(r, status="skipped", message="") for r in more]
                queue.extend(fresh)
    finally:
        finder.shutdown(wait=False, cancel_futures=True)  # 还在搜的不等了

    # 没处理到的线索、没等到的网站：写进各网站的说明
    if progress.is_cancelled(run_id):
        left, unfinished = ("cancelled", tr("搜索已取消")), tr("搜索已取消。")
    elif len(kept) >= target:
        left = ("not_needed", tr("已达到目标数量"))
        unfinished = tr("已达到目标数量，没有等这个网站的搜索结果。")
    else:
        left = ("over_limit", tr("超过每次搜索的总上限"))
        unfinished = tr("已到每次搜索的总上限，没有等这个网站的搜索结果。")
    results += [LeadResult(lead.site_id, lead.url, left[0], message=left[1]) for lead in queue]
    found += [SiteReport(s["id"], "skipped", message=unfinished) for s in pending.values()]
    return {"results": results, "reports": found}


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
        # 批次里的职位在处理时已经逐个写入（record_result）
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
