"""建立搜索批次、在背景执行 search_graph、处理中断。"""

from __future__ import annotations

import string
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.jobs.service import load_preferences
from app.models import JobSite, Resume, SearchRun
from app.search import progress
from app.search.web import get_searcher


class RunError(ValueError):
    pass


def new_run_id(db: Session, today: str | None = None) -> str:
    """`YYYY-MM-DD-A`，同一天依序 B、C…，超过 Z 之后是 AA、AB…。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    used = set(db.scalars(select(SearchRun.id).where(SearchRun.id.like(f"{today}-%"))))
    letters = string.ascii_uppercase
    candidates = list(letters) + [a + b for a in letters for b in letters]
    for suffix in candidates:
        if f"{today}-{suffix}" not in used:
            return f"{today}-{suffix}"
    raise RunError("今天的搜索批次太多了。")


def create_run(db: Session, site_ids: list[str] | None = None, sponsor_history: bool = True) -> SearchRun:
    if progress.active():
        raise RunError("已经有一个搜索正在进行，请等它完成或取消。")
    resume = db.scalar(select(Resume).where(Resume.is_active.is_(True)))
    if resume is None:
        raise RunError("请先上传并设定一份使用中的履历。")
    prefs, version = load_preferences(db)
    if not prefs.active_roles:
        raise RunError("请先在「求职需求」填写目标职位，或至少启用一个。")
    q = select(JobSite).where(JobSite.access_method != "paste_only").order_by(JobSite.sort_order)
    sites = db.scalars(q.where(JobSite.id.in_(site_ids)) if site_ids is not None else q.where(JobSite.enabled)).all()
    if not sites:
        raise RunError("请至少勾选一个要搜索的网站。")
    _, source_label = get_searcher(db)
    run = SearchRun(
        id=new_run_id(db),
        status="pending",
        resume_id=resume.id,
        preferences_version=version,
        # 当时的需求与网站设定快照：之后改需求不影响这个批次
        params={
            "sites": [
                {"id": s.id, "name": s.name, "access_method": s.access_method, "max_results": s.max_results}
                for s in sites
            ],
            "preferences": prefs.model_dump(),
            "total_limit": prefs.search.total_limit,
            "sponsor_history": sponsor_history,
            "search_source": source_label,
        },
    )
    run.graph_thread_id = run.id
    db.add(run)
    db.flush()
    return run


def execute_run(run_id: str) -> None:
    """背景执行。任何未预期的错误都写进批次，不让批次停在「进行中」。"""
    from app.graphs.search import build_graph

    maker = get_sessionmaker()
    with maker() as db:
        run = db.get(SearchRun, run_id)
        if run is None:
            return
        run.status, run.started_at = "running", datetime.now(UTC)
        params = run.params
        db.commit()
    progress.begin(run_id, [s["id"] for s in params["sites"]])
    try:
        build_graph().invoke({"run_id": run_id, "params": params, "reports": []})
    except Exception as exc:  # noqa: BLE001
        with maker() as db:
            run = db.get(SearchRun, run_id)
            run.status, run.finished_at = "failed", datetime.now(UTC)
            run.error = f"搜索中断（{type(exc).__name__}）：{str(exc)[:300]}"
            db.commit()
        progress.finish(run_id)


def spawn(target: Callable[[str], None], run_id: str) -> None:
    threading.Thread(target=target, args=(run_id,), name=f"search-{run_id}", daemon=True).start()


def recover_interrupted() -> None:
    """服务启动时：上次没跑完的批次标成失败（进度只存在记忆体里，无法接续）。"""
    try:
        with get_sessionmaker()() as db:
            for run in db.scalars(select(SearchRun).where(SearchRun.status.in_(("pending", "running")))):
                run.status, run.finished_at = "failed", datetime.now(UTC)
                run.error = "服务重启，搜索中断。请重新搜索。"
            db.commit()
    except Exception:  # noqa: BLE001  数据库还没启动时不影响服务启动
        pass
