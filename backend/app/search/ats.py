"""Greenhouse / Lever / Ashby 的公开职位板 JSON API（免登录、免 key）。

需要知道公司的 board 名：来自之前读过的职位页里的 ATS 链接，或用户在页面手动加入。
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from urllib.parse import quote

from app.core.fetch import fetch_json, html_to_text
from app.jobs.normalize import location_tier
from app.schemas.profile import JobPreferences
from app.search.sites import Lead, title_matches

API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true",
}


def _iso(value) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _jd(company: str, title: str, location: str, body: str, extra: str = "") -> str:
    head = f"{title}\nCompany: {company}\nLocation: {location or 'unknown'}"
    if extra:
        head += f"\n{extra}"
    return f"{head}\n\n{body.strip()}"


def _html(text: str) -> str:
    return html_to_text(html.unescape(text or ""))[0]


def parse_greenhouse(data: dict, token: str, company: str) -> list[Lead]:
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(
            Lead(
                site_id="greenhouse",
                url=j.get("absolute_url") or f"https://job-boards.greenhouse.io/{token}/jobs/{j.get('id')}",
                site_job_id=str(j.get("id")),
                title=j.get("title", ""),
                company=company,
                location=loc,
                posted_at=_iso(j.get("first_published") or j.get("updated_at")),
                jd_text=_jd(company, j.get("title", ""), loc, _html(j.get("content", ""))),
                ats=("greenhouse", token),
            )
        )
    return out


def parse_lever(data: list, token: str, company: str) -> list[Lead]:
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        sections = "\n\n".join(f"{s.get('text', '')}\n{_html(s.get('content', ''))}" for s in j.get("lists") or [])
        body = "\n\n".join(x for x in (j.get("descriptionPlain", ""), sections, j.get("additionalPlain", "")) if x)
        extra = " · ".join(x for x in (cats.get("commitment"), j.get("workplaceType")) if x)
        rng = j.get("salaryRange") or {}
        if rng.get("min"):
            extra += (
                f"\nSalary: {rng.get('min')} - {rng.get('max')} {rng.get('currency', '')} per {rng.get('interval', '')}"
            )
        out.append(
            Lead(
                site_id="lever",
                url=j.get("hostedUrl") or f"https://jobs.lever.co/{token}/{j.get('id')}",
                site_job_id=str(j.get("id")),
                title=j.get("text", ""),
                company=company,
                location=loc,
                posted_at=_iso(j.get("createdAt")),
                jd_text=_jd(company, j.get("text", ""), loc, body, extra),
                ats=("lever", token),
            )
        )
    return out


def parse_ashby(data: dict, token: str, company: str) -> list[Lead]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location", "") + (
            " (Remote)" if j.get("isRemote") and "remote" not in j.get("location", "").lower() else ""
        )
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        extra = " · ".join(x for x in (j.get("employmentType"), j.get("workplaceType"), comp) if x)
        body = j.get("descriptionPlain") or _html(j.get("descriptionHtml", ""))
        out.append(
            Lead(
                site_id="ashby",
                url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{token}/{j.get('id')}",
                site_job_id=str(j.get("id")),
                title=j.get("title", ""),
                company=company,
                location=loc,
                posted_at=_iso(j.get("publishedAt")),
                jd_text=_jd(company, j.get("title", ""), loc, body, extra),
                ats=("ashby", token),
            )
        )
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


def board_leads(kind: str, token: str, company: str) -> list[Lead]:
    """读取一个公司的职位板。FetchError 由呼叫端处理。"""
    data = fetch_json(API[kind].format(token=quote(token, safe="")))
    return PARSERS[kind](data, token, company)


def filter_leads(leads: list[Lead], prefs: JobPreferences, limit: int) -> list[Lead]:
    """只留职称相符、地点在你的优先清单里的职位；先按地点优先顺序，再按发布时间新到旧。"""
    picked = []
    for lead in leads:
        if not title_matches(lead.title, prefs):
            continue
        mode = "remote" if "remote" in lead.location.lower() else "unknown"
        tier = location_tier(lead.location, mode, prefs.locations) if prefs.locations else 0
        if tier is None:
            continue
        picked.append((tier, -(lead.posted_at.timestamp() if lead.posted_at else 0), lead))
    picked.sort(key=lambda x: (x[0], x[1]))
    return [lead for _, _, lead in picked[:limit]]
