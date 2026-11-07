"""名称正规化、去重键、地点优先级。纯程序。"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

# 法律实体后缀（比对时去掉）
_SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "lp", "llp", "pc", "pllc", "gmbh", "sa", "ag", "bv", "ulc", "pbc", "holdings",
}  # fmt: skip
_DBA = re.compile(r"\b(?:d\s*/?\s*b\s*/?\s*a|dba|doing business as)\b.*$")


def normalize_company(name: str) -> str:
    """'Acme Analytics, Inc. d/b/a Acme' → 'acme analytics'。用于去重与签证资料比对。"""
    s = name.lower().replace("&", " and ")
    s = _DBA.sub("", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    words = s.split()
    while words and (words[-1] in _SUFFIXES or " ".join(words[-2:]) in _SUFFIXES):
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
    """去重键（SPEC 3.1）：有 requisition ID 时用它，否则用「公司 + 正规化职称 + 地点」的杂凑。"""
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
