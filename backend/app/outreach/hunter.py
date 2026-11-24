"""Hunter.io 邮箱查找（用户自己的 API key）。只在用户按按钮时呼叫，不批量查。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.core.security import decrypt_secret
from app.llm.base import LLMError
from app.models import Integration
from app.search.sites import SITE_RULES, ats_from_url

BASE = "https://api.hunter.io/v2"
# 职位网址落在这些网站上时，网址的网域不是雇主的网域
NOT_EMPLOYER_HOSTS = (
    "ashbyhq.com",
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workday.com",
    "smartrecruiters.com",
    "workable.com",
    "icims.com",
    "jobvite.com",
    "bamboohr.com",
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "builtin.com",
    "wellfound.com",
    "ziprecruiter.com",
    "dice.com",
    # app 自己搜索的招聘网站：职位的申请网址常常就是这些网站
    *{d.split("/")[0] for rule in SITE_RULES.values() for d in rule["domains"]},
)


class HunterError(LLMError):
    pass


@dataclass
class HunterPerson:
    first_name: str
    last_name: str
    position: str
    email: str
    confidence: int | None
    linkedin: str | None


class HunterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = httpx.get(f"{BASE}/{path}", params=params, headers={"X-API-KEY": self.api_key}, timeout=30)
        except httpx.HTTPError as exc:
            raise HunterError(tr("无法连线到 Hunter。")) from exc
        if r.status_code == 401:
            raise HunterError(tr("Hunter API key 无效。"))
        if r.status_code == 429:
            raise HunterError(tr("Hunter 额度用完了，要等额度重置或升级方案。"))
        if r.status_code == 403:
            raise HunterError(tr("查询太频繁，Hunter 暂时拒绝，请稍后再试。"))
        if r.status_code != 200:
            raise HunterError(tr("Hunter 回应 {status_code}。", status_code=r.status_code))
        return r.json().get("data") or {}

    def check(self) -> None:
        self._get("account")

    def find_email(self, domain: str, first_name: str, last_name: str) -> tuple[str, int] | None:
        data = self._get("email-finder", {"domain": domain, "first_name": first_name, "last_name": last_name})
        if not data.get("email"):
            return None
        return data["email"], int(data.get("score") or 0)

    def domain_people(self, domain: str, departments: list[str]) -> list[HunterPerson]:
        people = []
        for dept in departments:  # 免费方案 limit + offset 不能超过 10
            data = self._get("domain-search", {"domain": domain, "department": dept, "limit": 10, "type": "personal"})
            for e in data.get("emails") or []:
                if not (e.get("first_name") and e.get("last_name")):
                    continue
                people.append(
                    HunterPerson(
                        first_name=e["first_name"],
                        last_name=e["last_name"],
                        position=e.get("position") or "",
                        email=e.get("value") or "",
                        confidence=e.get("confidence"),
                        linkedin=e.get("linkedin"),
                    )
                )
        return people


def hunter_row(db: Session) -> Integration | None:
    return db.scalar(select(Integration).where(Integration.kind == "hunter"))


def get_hunter(db: Session) -> HunterClient | None:
    row = hunter_row(db)
    if row is None or not row.enabled or not row.secret_encrypted:
        return None
    return HunterClient(decrypt_secret(row.secret_encrypted))


def host_of(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    try:
        host = urlsplit(url if "//" in url else f"//{url}").hostname
    except ValueError:
        return None
    if not host or "." not in host:
        return None
    return host.removeprefix("www.")


def company_domain(company, job) -> str | None:
    """雇主的网域：公司网址 → 职位的申请网址（但 ATS / 招聘网站不算）→ 不知道就回传 None，请用户填。"""
    host = host_of(getattr(company, "website", None))
    if host:
        return host
    apply_url = getattr(job, "apply_url", None) or ""
    if ats_from_url(apply_url):
        return None
    host = host_of(apply_url)
    if host and not any(host == h or host.endswith("." + h) for h in NOT_EMPLOYER_HOSTS):
        return host
    return None
