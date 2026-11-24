"""各网站的职位页网址规则与搜索关键字。纯程序。

只接受「单一职位页」的网址；搜索结果里的列表页、公司页、登录页都不算找到职位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from app.schemas.profile import JobPreferences


@dataclass
class Lead:
    """搜索找到的一个职位线索（尚未读取、抽取）。"""

    site_id: str
    url: str
    site_job_id: str | None = None
    title: str = ""
    company: str = ""
    location: str = ""
    posted_text: str = ""
    posted_at: datetime | None = None
    snippet: str = ""
    jd_text: str | None = None  # ATS API 已经给了完整 JD 时才有
    ats: tuple[str, str] | None = None  # (greenhouse|lever|ashby, board token)
    via_browser: bool = False  # 职位页要用登录浏览器读（SPEC v0.10）


@dataclass
class SiteReport:
    site_id: str
    status: str  # ok / partial / blocked / failed / skipped（搜索阶段的结果；读取职位页后可能再调整）
    leads: list[Lead] = field(default_factory=list)
    message: str = ""
    dropped: int = 0  # 搜索回传了、但不是该网站职位页的网址


# 每个网站：搜索时限定的网域、职位页网址的规则（第一个 group 是平台职位 ID）
SITE_RULES: dict[str, dict] = {
    "linkedin": {"domains": ["linkedin.com/jobs/view"], "job": [r"linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d{6,})"]},
    "indeed": {
        "domains": ["indeed.com/viewjob"],
        "job": [r"indeed\.com/(?:m/)?(?:viewjob|rc/clk|pagead/clk)\?(?:.*&)?jk=([0-9a-f]{8,})"],
    },
    "builtin": {
        "domains": ["builtin.com/job", "builtinla.com/job"],
        "job": [r"builtin[a-z]*\.(?:com|org)/job/[^?#]*?/(\d{4,})"],
    },
    "wellfound": {"domains": ["wellfound.com"], "job": [r"wellfound\.com/(?:company/[^/]+/)?jobs/(\d{4,})"]},
    "yc": {
        "domains": ["ycombinator.com/companies", "workatastartup.com/jobs"],
        "job": [r"ycombinator\.com/companies/[^/]+/jobs/([A-Za-z0-9]+)", r"workatastartup\.com/jobs/(\d+)"],
    },
    "dice": {"domains": ["dice.com/job-detail"], "job": [r"dice\.com/job-detail/([0-9a-fA-F-]{20,})"]},
    "wttj": {
        "domains": ["welcometothejungle.com"],
        "job": [r"welcometothejungle\.com/[a-z-]+/companies/[^/]+/jobs/([^/?#]+)"],
    },
    "wwr": {"domains": ["weworkremotely.com/remote-jobs"], "job": [r"weworkremotely\.com/remote-jobs/([^/?#]+)"]},
    # 公司招聘板：搜索只用来找出公司的 board 名（网址规则见 ATS_URL），职位本身从公开 API 读
    "greenhouse": {"domains": ["job-boards.greenhouse.io", "boards.greenhouse.io"]},
    "lever": {"domains": ["jobs.lever.co"]},
    "ashby": {"domains": ["jobs.ashbyhq.com"]},
}

ATS_URL = [
    (
        "greenhouse",
        re.compile(r"^https?://(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)", re.I),
    ),
    ("lever", re.compile(r"^https?://jobs(?:\.eu)?\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
]
_ATS_RESERVED = {"embed", "api", "v1", "jobs", "job_app"}


def ats_from_url(url: str) -> tuple[str, str] | None:
    """从网址推出 ATS 种类与公司的 board 名。例如 boards.greenhouse.io/acme/jobs/1 → ("greenhouse", "acme")。"""
    for kind, rx in ATS_URL:
        m = rx.match(url.strip())
        if m and m.group(1).lower() not in _ATS_RESERVED:
            return kind, m.group(1)
    return None


def clean_url(url: str) -> str:
    """去掉追踪参数与 fragment，作为去重用的网址。Indeed 保留 jk。"""
    p = urlsplit(url.strip())
    query = p.query
    if "indeed." in (p.hostname or ""):
        m = re.search(r"(?:^|&)jk=([0-9a-f]+)", query)
        query = f"jk={m.group(1)}" if m else ""
    else:
        query = "&".join(
            kv for kv in query.split("&") if kv and not kv.lower().startswith(("utm_", "ref", "trk", "src", "gh_src"))
        )
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", query, ""))


def match_job_url(site_id: str, url: str) -> str | None:
    """网址是这个网站的单一职位页时，回传平台职位 ID；否则回传 None。公司招聘板的网址回传 board 名。"""
    rules = SITE_RULES.get(site_id, {})
    if "job" not in rules:
        found = ats_from_url(url)
        return found[1] if found and found[0] == site_id else None
    for rx in rules["job"]:
        m = re.search(rx, url, re.I)
        if m:
            return next(g for g in m.groups() if g)
    return None


_ENGINEER = {"engineer", "engineers", "developer", "programmer", "swe"}
_LEVEL = {"senior", "junior", "sr", "jr", "ii", "iii", "i", "the", "and", "of", "lead", "staff", "mid", "level", "role", "roles"}  # fmt: skip


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9#+.]+", text.lower().replace("-", " ")))


def title_matches(title: str, prefs: JobPreferences) -> bool:
    """职称符合任一个目标职位（给 ATS 职称过滤用）。目标是工程师类时，职称也要是工程师类。"""
    have = _words(title)
    engineer = bool(have & _ENGINEER)
    if not prefs.active_roles:
        return engineer
    for role in prefs.active_roles:
        words = _words(role)
        if words & _ENGINEER and not engineer:
            continue
        rest = {w for w in words - _ENGINEER - _LEVEL if len(w) > 1}
        distinctive = rest - {"software"}  # 有辨识度的字（full、stack、backend、react…）
        # 目标没有辨识字（Software Engineer）时要有 software，才不会把 Frontend Engineer 也算进来
        if distinctive & have if distinctive else rest <= have:
            return True
    return False


def search_locations(prefs: JobPreferences) -> list[str]:
    return [loc for loc in prefs.locations if loc.strip()][:3] or ["United States"]


def build_queries(site_id: str, prefs: JobPreferences, limit: int = 6) -> list[str]:
    """给 Tavily / SearXNG 用的查询字串（模型自带搜索则直接给它规则，由它自己组查询）。"""
    roles = prefs.active_roles or ["Software Engineer"]
    domains = SITE_RULES[site_id]["domains"]
    out = []
    for role in roles:
        for loc in search_locations(prefs):
            out.append(f'site:{domains[0]} "{role}" {loc}')
    return out[:limit]
