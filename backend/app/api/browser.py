"""登录浏览器的设定：开关、打开窗口让用户登录、清除登录状态（SPEC v0.10）。"""

from __future__ import annotations

import importlib.util
import shutil
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.i18n import tr
from app.models import Integration, JobSite
from app.schemas.browser import BrowserOpen, BrowserStatus, BrowserToggle
from app.search import browser, progress
from app.search.browser import BROWSER_SITES, BrowserError, close_browser, logged_in, profile_dir, window_open

router = APIRouter(prefix="/api/browser", tags=["browser"])

LOGIN_URLS = {"linkedin": "https://www.linkedin.com/login"}


def availability() -> tuple[bool, str | None]:
    if importlib.util.find_spec("playwright") is None:
        return False, tr("没有安装 Playwright：在 backend 目录执行 uv sync。")
    return True, None


def _status(db: Session) -> BrowserStatus:
    available, reason = availability()
    return BrowserStatus(
        enabled=browser.browser_enabled(db),
        available=available,
        reason=reason,
        window_open=window_open(),
        logged_in={s: logged_in.get(s) for s in BROWSER_SITES},
    )


@router.get("", response_model=BrowserStatus)
def get_status(db: Session = Depends(get_db)):
    return _status(db)


@router.put("", response_model=BrowserStatus)
def set_enabled(body: BrowserToggle, db: Session = Depends(get_db)):
    row = db.scalar(select(Integration).where(Integration.kind == "browser"))
    if body.enabled:
        available, reason = availability()
        if not available:
            raise HTTPException(422, reason)
        if row is None:
            row = Integration(kind="browser", config={})  # 只是开关，不存任何秘密
            db.add(row)
        row.enabled = True
    else:
        if row is not None:
            row.enabled = False
        for site in db.scalars(select(JobSite).where(JobSite.access_method == "browser")):
            site.access_method = "web_search"
        close_browser()
    db.flush()
    return _status(db)


def _open_login(site: str) -> None:
    try:
        page = browser.get_browser().open(LOGIN_URLS[site])
    except BrowserError:
        return  # 窗口开不了：登录状态维持「还没检查」，搜索时会写出原因
    logged_in[site] = not browser.is_blocked(page)  # 已经登录的话会被直接带到首页


@router.post("/open", status_code=202)
def open_window(body: BrowserOpen, db: Session = Depends(get_db)):
    """打开窗口并转到登录页，让用户自己登录。在背景执行，不等结果。"""
    if body.site not in BROWSER_SITES:
        raise HTTPException(422, tr("这个网站不支援登录浏览器。"))
    if not browser.browser_enabled(db):
        raise HTTPException(409, tr("请先开启登录浏览器。"))
    threading.Thread(target=_open_login, args=(body.site,), name="browser-login", daemon=True).start()
    return {"ok": True}


@router.delete("/profile", status_code=204)
def clear_profile():
    """关掉窗口并删除本机的登录资料（等于登出）。"""
    if progress.active():
        raise HTTPException(409, tr("搜索进行中，等它结束再清除登录状态。"))
    close_browser()
    shutil.rmtree(profile_dir(), ignore_errors=True)
    logged_in.clear()
