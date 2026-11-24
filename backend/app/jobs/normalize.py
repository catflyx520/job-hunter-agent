"""名称正规化、去重键、地点优先级。纯程序。"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

# 法律实体后缀（比对时去掉）
_SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "lp", "llp", "pc", "pllc", "gmbh", "sa", "ag", "bv", "ulc", "pbc", "na", "holdings",
}  # fmt: skip
_DBA = re.compile(r"\b(?:d\s*/?\s*b\s*/?\s*a|dba|doing business as)\b.*$")


def normalize_company(name: str) -> str:
    """'Acme Analytics, Inc. d/b/a Acme' → 'acme analytics'。用于去重与签证资料比对。"""
    s = name.lower().replace("&", " and ")
    # 带点号的缩写后缀（L.L.C.、S.A.、B.V.、N.A.）先合并成 llc、sa、bv、na
    s = re.sub(r"\b(?:[a-z]\.\s?){2,}", lambda m: m.group(0).replace(".", "").replace(" ", "") + " ", s)
    s = _DBA.sub("", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    words = s.split()
    while words and (words[-1] in _SUFFIXES or " ".join(words[-2:]) in _SUFFIXES or words[-1] == "and"):
        # 「& Co.」去掉 co 之后会剩下 and，一并去掉
        words = words[:-2] if " ".join(words[-2:]) in _SUFFIXES else words[:-1]
    if words and words[0] == "the" and len(words) > 1:
        words = words[1:]
    return " ".join(words)


def normalize_title(title: str) -> str:
    s = title.lower()
    s = re.sub(r"\bsr\b\.?", "senior", s)
    s = re.sub(r"\bjr\b\.?", "junior", s)
    s = re.sub(r"\bswe\b", "software engineer", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_key(company_norm: str, title: str, location: str, requisition_id: str = "") -> str:
    """去重键：有 requisition ID 时用它，否则用「公司 + 正规化职称 + 地点」的杂凑。"""
    if requisition_id.strip():
        return f"req:{company_norm}:{requisition_id.strip().lower()}"
    raw = "|".join((company_norm, normalize_title(title), re.sub(r"[^a-z0-9]+", " ", location.lower()).strip()))
    return "h:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


SITE_HOSTS = {
    "linkedin.com": "linkedin",
    "indeed.com": "indeed",
    "joinhandshake.com": "handshake",
    "builtin.com": "builtin",
    "builtinla.com": "builtin",
    "wellfound.com": "wellfound",
    "ycombinator.com": "yc",
    "workatastartup.com": "yc",
    "dice.com": "dice",
    "welcometothejungle.com": "wttj",
    "weworkremotely.com": "wwr",
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
}


def site_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if re.search(r"(?:^|\.)builtin[a-z]*\.(?:com|org)$", host):
        return "builtin"
    for domain, site in SITE_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return site
    return "manual"


def job_page_url(url: str) -> str:
    """LinkedIn 的搜索结果 / 推荐列表网址（…/jobs/search-results/?currentJobId=123）换成公开职位页 /jobs/view/123；
    未登入时列表页没有 JD。其他网址原样回传。"""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if site_for_url(url) != "linkedin" or not parts.path.startswith("/jobs/") or parts.path.startswith("/jobs/view/"):
        return url
    job_id = parse_qs(parts.query).get("currentJobId", [""])[0]
    return f"https://{host}/jobs/view/{job_id}" if job_id.isdigit() else url


_UNIT_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def parse_posted(text: str | None, now: datetime) -> datetime | None:
    """'3 days ago'、'Reposted 2 Months Ago'、'Posted Oct 25, 2026'、'2026-10-25' → 日期；看不懂回传 None。"""
    s = (text or "").strip().lower()
    if not s:
        return None
    if re.search(r"\b(just now|today|moments? ago)\b", s):
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month|year)s?\s+ago", s)
    if m:
        return now - timedelta(days=int(m[1]) * _UNIT_DAYS[m[2]])
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        return datetime.strptime(m[0], "%Y-%m-%d").replace(tzinfo=UTC)
    m = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        try:
            return datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%b %d %Y").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def location_tier(location_text: str, work_mode: str, preferred: list[str]) -> int | None:
    """落在用户地点优先顺序的第几级（1 起算）；比对不到回传 None（未知，不是排除）。"""
    loc = location_text.lower()
    for i, pref in enumerate(preferred, start=1):
        p = pref.lower().strip()
        if not p:
            continue
        if "remote" in p and work_mode == "remote":
            return i
        tokens = [t for t in re.split(r"[^a-z0-9]+", p) if len(t) > 2 and t not in {"remote", "area", "metro"}]
        if loc and tokens and all(t in loc for t in tokens):
            return i
    return None
