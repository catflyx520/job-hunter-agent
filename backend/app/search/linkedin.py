"""用登录浏览器在 LinkedIn 找职位（SPEC v0.10）。页面的样子以 2026-11-19 的实测为准。

- 登录后的搜索页是新版（/jobs/search-results/）：地点参数会被丢掉，所以把地点写进关键字；「最近一周」的筛选有保留。
- 职位卡没有各自的链接，职位 ID 由浏览器从卡片的属性取出（见 browser._CARDS_JS）。
- 搜索结果比较杂，先用卡片上的职称与地点过滤，再去打开职位页。
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any
from urllib.parse import quote

from app.core.i18n import tr
from app.schemas.profile import JobPreferences
from app.search.ats import filter_leads
from app.search.browser import WAIT_MAX, BrowserBlocked, BrowserError, open_checked
from app.search.sites import Lead, SiteReport

MAX_SEARCHES = 6  # 一次搜索最多开几个搜索页
_POSTED = re.compile(r"\d+ (?:minute|hour|day|week|month)s? ago")


def search_urls(prefs: JobPreferences) -> list[str]:
    """每个职位 × 每个地点一条；先把每个职位在第一优先的地点搜过，再换下一个地点。"""
    words = [f"{role} {place}".strip() for place in (prefs.locations or [""]) for role in prefs.active_roles]
    return [
        f"https://www.linkedin.com/jobs/search-results/?keywords={quote(w)}&f_TPR=r604800" for w in words[:MAX_SEARCHES]
    ]


def parse_card(job_id: str, text: str) -> Lead:
    """卡片文字依序是：职称（有的重复一次，前面可能有 "Selected, "、后面可能有 "(Verified job)"）、公司、地点。"""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    repeated = len(lines) > 1 and lines[1] in lines[0]
    title = lines[1] if repeated else re.sub(r"\s*\(Verified job\)$", "", lines[0]) if lines else ""
    rest = lines[2:] if repeated else lines[1:]
    posted = _POSTED.search(text)
    return Lead(
        site_id="linkedin",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        site_job_id=job_id,
        title=title,
        company=rest[0] if rest else "",
        location=rest[1] if len(rest) > 1 else "",
        posted_text=posted.group(0) if posted else "",
        via_browser=True,
    )


def browser_leads(
    run_id: str | None, site: dict[str, Any], prefs: JobPreferences, exclude: Collection[str] = ()
) -> SiteReport:
    sid = site["id"]
    if exclude:
        # shortcut: 新版搜索页的翻页参数还没实测，补搜不再搜 LinkedIn；常搜不够时再加翻页
        return SiteReport(sid, "ok")
    cards: dict[str, str] = {}
    opened, problem = 0, ""
    status = "ok"
    for url in search_urls(prefs):
        try:
            page = open_checked(run_id, url, scroll=True)
        except BrowserBlocked:
            status = "blocked"
            problem = tr(
                "LinkedIn 要求登录或验证，等了 {n} 秒没有处理。请到设定页打开浏览器窗口登录后再搜索。", n=WAIT_MAX
            )
            break
        except BrowserError as exc:
            status, problem = "failed", str(exc)
            break
        opened += 1
        for job_id, text in page.cards:
            cards.setdefault(job_id, text)
    if status == "ok" and not cards:
        # 不能静静地当成「没有职位」：LinkedIn 改版时这里最先坏
        return SiteReport(sid, "failed", message=tr("LinkedIn 搜索页里找不到职位卡，页面结构可能改了。"))
    leads = filter_leads([parse_card(i, t) for i, t in cards.items()], prefs, site["max_results"], exclude)
    if status != "ok" and leads:
        status = "partial"  # 被挡住之前找到的照样处理
    msg = tr(
        "开了 {n} 个搜索页，共 {cards} 张职位卡，职称与地点相符 {kept} 个。",
        n=opened,
        cards=len(cards),
        kept=len(leads),
    )
    return SiteReport(sid, status, leads, f"{msg} {problem}".strip() if opened else problem)
