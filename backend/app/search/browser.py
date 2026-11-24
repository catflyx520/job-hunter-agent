"""登录浏览器：app 自己开一个独立的 Chrome 窗口，用户在里面登录，程序只读职位（SPEC v0.10）。

- 程序只做三件事：打开网址、卷动、读页面内容。不点任何东西。
- 登录页、验证页由用户自己在窗口里处理；程序只等，不碰。
- 不用无头模式，不做任何隐藏自动化的手段；不读取、不导出 cookie（登录状态由 Chrome 自己存在 profile 目录）。
- Playwright 的同步物件只能在建立它的执行绪里用，所以开一条专用的执行绪持有窗口，其他执行绪排队请它做事。
"""

from __future__ import annotations

import queue
import re
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import tr
from app.models import Integration
from app.search import progress

BROWSER_SITES = ("linkedin",)
WAIT_POLL, WAIT_MAX = 5, 180  # 等用户处理登录 / 验证：每几秒看一次、最多等几秒

_BLOCK_URL = re.compile(r"linkedin\.com/(login|checkpoint|authwall|uas/|signup)", re.I)
_BLOCK_TITLE = re.compile(r"just a moment|security verification|verify you are human|additional verification", re.I)

# 职位卡没有各自的链接，职位 ID 在 componentkey 里（2026-11-19 实测）；同一个 ID 留文字最长的那个元素
_CARDS_JS = """() => { const best = {};
  for (const el of document.querySelectorAll('[componentkey^="job-card-component-ref-"]')) {
    const id = el.getAttribute('componentkey').slice('job-card-component-ref-'.length);
    const text = el.innerText || '';
    if (/^\\d{6,}$/.test(id) && text.length > (best[id] || '').length) best[id] = text; }
  return Object.entries(best); }"""

logged_in: dict[str, bool] = {}  # 最近一次看到的登录状态，只放记忆体
_use = threading.Lock()  # 一次只让一个人用窗口：有人在等用户登录时，别的工作不能把页面导走
_gave_up: set[str] = set()  # 已经等到逾时的搜索批次：同一批后面的页面不再各等一次


@dataclass
class BrowserPage:
    url: str  # 最终网址
    title: str
    text: str  # body 的可见文字
    links: list[str]  # 页面上所有链接（绝对网址）
    cards: list[tuple[str, str]] = field(default_factory=list)  # LinkedIn 职位卡：(职位 ID, 卡片文字)


class BrowserError(Exception):
    """窗口开不了、被关掉、页面读取出错。"""


class BrowserBlocked(BrowserError):
    """登录页 / 验证页，等到逾时或搜索被取消。"""


class Browser(Protocol):
    def open(self, url: str, *, scroll: bool = False) -> BrowserPage: ...

    def current(self) -> BrowserPage: ...  # 不导航，读目前这一页

    def close(self) -> None: ...


def profile_dir() -> Path:
    return get_settings().data_dir / "browser-profile"


def browser_enabled(db: Session) -> bool:
    return db.scalar(select(Integration.id).where(Integration.kind == "browser", Integration.enabled)) is not None


def is_blocked(page: BrowserPage) -> bool:
    return bool(_BLOCK_URL.search(page.url.split("?")[0]) or _BLOCK_TITLE.search(page.title))


class ChromeBrowser:
    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._pw: Any = None
        self._ctx: Any = None
        self._last = 0.0

    # ----- 给其他执行绪用 -----

    def open(self, url: str, *, scroll: bool = False) -> BrowserPage:
        return self._call(self._open, url, scroll)

    def current(self) -> BrowserPage:
        return self._call(self._current)

    def close(self) -> None:
        if self._thread is not None:
            self._call(self._close)

    def is_open(self) -> bool:
        return self._ctx is not None

    def _call(self, fn, *args):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="browser", daemon=True)
                self._thread.start()
        future: Future = Future()
        self._jobs.put((future, fn, args))
        return future.result()

    # ----- 只在浏览器执行绪里跑 -----

    def _run(self) -> None:
        while True:
            future, fn, args = self._jobs.get()
            try:
                future.set_result(fn(*args))
            except BrowserError as exc:
                future.set_exception(exc)
            except Exception as exc:  # noqa: BLE001  多半是窗口被用户关掉：丢掉它，下次重新开
                self._drop()
                first = (str(exc).splitlines() or [""])[0][:200]
                future.set_exception(BrowserError(tr("浏览器窗口出错（可能被关掉了）：{v}", v=first)))

    def _drop(self) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = None

    def _close(self) -> None:
        self._drop()
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def _page(self):
        if self._ctx is None:
            if self._pw is None:
                from playwright.sync_api import sync_playwright  # 没开启功能时不 import

                self._pw = sync_playwright().start()
            errors = []
            for channel in ("chrome", "msedge"):  # 用本机已装的浏览器，不另外下载
                try:
                    self._ctx = self._pw.chromium.launch_persistent_context(
                        str(profile_dir()), channel=channel, headless=False
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append((str(exc).splitlines() or [""])[0][:120])
            if self._ctx is None:
                raise BrowserError(tr("开不了 Chrome 或 Edge：{v}", v="；".join(errors)))
        return self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def _read(self, page) -> BrowserPage:
        return BrowserPage(
            url=page.url,
            title=page.title(),
            text=page.inner_text("body"),
            links=page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"),
            cards=[(c[0], c[1]) for c in page.evaluate(_CARDS_JS)],
        )

    def _open(self, url: str, scroll: bool) -> BrowserPage:
        page = self._page()
        wait = self._last + get_settings().browser_page_interval - time.monotonic()
        if wait > 0:  # 限速：每开一页固定间隔
            time.sleep(wait)
        self._last = time.monotonic()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        if scroll:
            for _ in range(5):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1000)
        return self._read(page)

    def _current(self) -> BrowserPage:
        if self._ctx is None:
            raise BrowserError(tr("浏览器窗口没有开着。"))
        return self._read(self._page())


_browser: ChromeBrowser | None = None


def get_browser() -> Browser:
    global _browser
    if _browser is None:
        _browser = ChromeBrowser()
    return _browser


def close_browser() -> None:
    if _browser is not None:
        _browser.close()


def window_open() -> bool:
    return _browser is not None and _browser.is_open()


def open_checked(run_id: str | None, url: str, *, scroll: bool = False) -> BrowserPage:
    """打开网址；遇到登录页或验证页时等用户自己在窗口里处理，处理完重新打开原来的网址。

    同一个搜索批次只等一次：等到逾时之后，后面的页面被挡住就直接放弃（一批有几十个职位页，不能每个等 3 分钟）。
    """
    with _use:
        return _open_checked(run_id, url, scroll)


def _open_checked(run_id: str | None, url: str, scroll: bool) -> BrowserPage:
    browser = get_browser()
    page = browser.open(url, scroll=scroll)
    if not is_blocked(page):
        logged_in["linkedin"] = True
        return page
    logged_in["linkedin"] = False
    if run_id in _gave_up:
        raise BrowserBlocked(tr("LinkedIn 要求登录或验证"))
    if run_id:
        _gave_up.add(run_id)  # 等到了会在下面拿掉
        progress.set_note(run_id, tr("请在浏览器窗口完成登录或验证，完成后搜索会自动继续。"))
    try:
        for _ in range(WAIT_MAX // WAIT_POLL):
            if run_id and progress.is_cancelled(run_id):
                break
            time.sleep(WAIT_POLL)
            if not is_blocked(browser.current()):
                page = browser.open(url, scroll=scroll)  # 登录完会被带到首页，重新打开要读的那一页
                if not is_blocked(page):
                    logged_in["linkedin"] = True
                    _gave_up.discard(run_id)
                    return page
                break
        raise BrowserBlocked(tr("LinkedIn 要求登录或验证"))
    finally:
        if run_id:
            progress.set_note(run_id, None)
