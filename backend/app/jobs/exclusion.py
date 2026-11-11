"""硬性排除：程序规则，优先于分数。被排除的职位附原因保留，不直接丢掉。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.jobs.normalize import normalize_company
from app.models import Job
from app.schemas.profile import Blacklist, JobPreferences

HOURS_PER_YEAR = 2080

REASON_LABELS = {
    "explicit_no_sponsorship": "你需要 sponsorship，但职位明确写不提供",
    "citizenship_required": "要求公民 / 绿卡身份或需公民身份的 security clearance",
    "employment_type": "雇佣类型是你排除的类型",
    "salary_below_minimum": "薪资区间整个低于你的最低年薪",
    "new_grad_only": "明确限定 New Grad / 毕业年份",
    "expired": "职位已过期",
    "blacklisted_company": "公司在你的黑名单里",
    "blacklisted_title": "职称符合黑名单里的职位",
}
FLAG_LABELS = {
    "salary_partially_below": "薪资区间下段低于你的最低年薪（区间有涵盖到，保留）",
    "sponsorship_unclear": "JD 没写 sponsorship 政策（不明，不代表支持）",
    "salary_unknown": "薪资未列出",
}


# 职位页上「已下架 / 不再收件」的说法（程序判断，不靠模型）
CLOSED_POSTING = re.compile(
    r"this job (?:was|has been) removed|job (?:is )?no longer available|no longer accepting applications|"
    r"this (?:job|position|posting) (?:has )?(?:expired|closed|been filled)|position has been filled|"
    r"job posting (?:has )?expired|this job is closed",
    re.I,
)


def closed_posting(jd_text: str) -> str | None:
    """页面写明职位已下架时，回传那句原文；否则 None。只看页面前段，避免误判推荐职位区块。"""
    m = CLOSED_POSTING.search(jd_text[:4000])
    return m.group(0) if m else None


@dataclass
class ExclusionResult:
    reasons: list[str]  # 排除原因代码
    flags: list[str]  # 不排除、但要标注的事项

    @property
    def excluded(self) -> bool:
        return bool(self.reasons)


def annual(amount: int | None, period: str | None) -> int | None:
    if amount is None:
        return None
    return amount * HOURS_PER_YEAR if period == "hour" else amount


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9#+]+", text.lower())) + " "


def title_matches(title: str, phrase: str) -> bool:
    """职称里含这组词（整词、按顺序、不分大小写与标点）。例：「Sales Engineer」符合「Senior Sales Engineer, West」。"""
    p = _words(phrase)
    return p.strip() != "" and p in _words(title)


def blacklist_reasons(job: Job, bl: Blacklist) -> list[str]:
    reasons = []
    company = getattr(job, "company", None)
    if company is not None and bl.companies:
        norm = normalize_company(company.display_name)
        if norm and norm in {normalize_company(c) for c in bl.companies}:
            reasons.append("blacklisted_company")
    if any(title_matches(job.title or "", t) for t in bl.titles):
        reasons.append("blacklisted_title")
    return reasons


def check_exclusions(job: Job, prefs: JobPreferences) -> ExclusionResult:
    reasons: list[str] = blacklist_reasons(job, prefs.blacklist)
    flags: list[str] = []
    auth = prefs.work_authorization
    needs_sponsor = bool(auth.needs_sponsorship_now or auth.needs_sponsorship_future)

    if job.sponsorship_policy == "explicit_no" and needs_sponsor:
        reasons.append("explicit_no_sponsorship")
    elif job.sponsorship_policy == "unclear" and needs_sponsor:
        flags.append("sponsorship_unclear")

    if job.citizenship_required and auth.authorized_in_us is not True:
        reasons.append("citizenship_required")
    elif job.citizenship_required and needs_sponsor:
        # 已可工作但需要 sponsorship，代表不是公民 / 绿卡
        reasons.append("citizenship_required")

    allowed = set(prefs.employment_types)
    if "contract" in allowed:
        allowed.add("c2c")
    if job.employment_type != "unknown" and allowed and job.employment_type not in allowed:
        reasons.append("employment_type")

    if prefs.min_salary:
        lo, hi = annual(job.salary_min, job.salary_period), annual(job.salary_max, job.salary_period)
        top = hi if hi is not None else lo
        if top is None:
            flags.append("salary_unknown")
        elif top < prefs.min_salary:
            reasons.append("salary_below_minimum")
        elif lo is not None and lo < prefs.min_salary:
            flags.append("salary_partially_below")

    if prefs.exclude_new_grad_only and job.new_grad_only:
        reasons.append("new_grad_only")

    if job.status == "expired":
        reasons.append("expired")
    return ExclusionResult(reasons=reasons, flags=flags)
