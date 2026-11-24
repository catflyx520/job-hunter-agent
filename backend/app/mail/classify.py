"""邮件分类（模型任务 email_classify）：这封信能证明什么。对上哪个职位由程式判断（match.py）。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.jobs.extract import evidence_in_text
from app.jobs.normalize import normalize_company
from app.llm.base import LLMProvider, Message
from app.mail.gmail import MailMessage

MAX_BODY = 6000
BATCH = 10  # 一次分类几封
BATCH_BODY = 3000  # 一批里每封送多少字
# 求职平台与 ATS：不能当成雇主（和 SYSTEM 里列的一致）
PLATFORMS = {
    "linkedin", "indeed", "handshake", "wellfound", "glassdoor", "ziprecruiter", "greenhouse", "lever",
    "ashby", "workday", "smartrecruiters", "icims", "jobvite", "dice",
}  # fmt: skip

SYSTEM = """You classify one email from a job seeker's mailbox. Be strict and never guess.

kind:
- application_received: the employer or job platform confirms the application WAS submitted or received.
- rejection: the employer says they will not move forward with this application.
- interview: an invitation to schedule or attend an interview (phone screen, technical, onsite) with a person.
- offer: a job offer.
- not_evidence: everything else. This includes job alerts, recommended jobs, saved-job reminders, drafts,
  "complete your application" / "you haven't finished applying" reminders, online assessments and coding
  challenges, account or newsletter emails, marketing, and recruiter cold outreach about a role the
  person did not apply to.

company: the hiring employer. When the sender is a job platform or ATS (LinkedIn, Indeed, Handshake,
Wellfound, Glassdoor, ZipRecruiter, Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS), use the
employer named in the email, never the platform. Leave empty if no employer is named.
title: the exact job title written in the email. Leave empty if the email does not name the role
(for example a generic interview invitation). Do not infer it.
requisition_id: the job or requisition ID if written, else empty.
evidence: copy one sentence verbatim from the email that proves the kind. Empty for not_evidence."""


class MailClassification(BaseModel):
    kind: Literal["application_received", "rejection", "interview", "offer", "not_evidence"] = Field(
        description="What this email proves."
    )
    company: str = Field("", description="Hiring employer, not the job platform.")
    title: str = Field("", description="Exact job title written in the email, or empty.")
    requisition_id: str = Field("", description="Job / requisition ID written in the email, or empty.")
    evidence: str = Field("", description="One sentence copied verbatim from the email.")


class BatchItem(MailClassification):
    index: int = Field(description="The email's number from its === Email N === header.")


class MailBatch(BaseModel):
    results: list[BatchItem] = Field(description="One result per email.")


def _email(msg: MailMessage, limit: int) -> str:
    return f"From: {msg.from_addr}\nDate: {msg.received_at.isoformat()}\nSubject: {msg.subject}\n\n{msg.text[:limit]}"


def classify(provider: LLMProvider, msg: MailMessage) -> tuple[MailClassification, str | None]:
    """回传分类与「需要确认的原因」代码（None 表示可信；文字在 match.reason_text）。"""
    result = provider.generate(
        [Message("system", SYSTEM), Message("user", _email(msg, MAX_BODY))], schema=MailClassification
    )
    return result.parsed, _check(result.parsed, msg)  # type: ignore[arg-type]


def classify_batch(provider: LLMProvider, msgs: list[MailMessage]) -> list[tuple[MailClassification, str | None]]:
    """一次分类多封（省时间与额度）；每封照样核对原句、公司与职称。模型漏掉的列为需要确认。"""
    user = "\n\n".join(f"=== Email {i} ===\n{_email(m, BATCH_BODY)}" for i, m in enumerate(msgs, 1))
    system = SYSTEM + "\n\nYou get several emails, each under an === Email N === header. Classify each one separately."
    result = provider.generate([Message("system", system), Message("user", user)], schema=MailBatch)
    by_index = {r.index: r for r in result.parsed.results}  # type: ignore[union-attr]
    out: list[tuple[MailClassification, str | None]] = []
    for i, msg in enumerate(msgs, 1):
        item = by_index.get(i)
        if item is None:
            out.append((MailClassification(kind="not_evidence"), "skipped"))
            continue
        cls = MailClassification(**item.model_dump(exclude={"index"}))
        out.append((cls, _check(cls, msg)))
    return out


def _check(cls: MailClassification, msg: MailMessage) -> str | None:
    """核对模型的答案：原句、公司、职称都必须真的出现在信里（模型不能自己补）。回传原因代码。"""
    if cls.kind == "not_evidence":
        return None
    haystack = f"{msg.subject}\n{msg.text}"
    if not evidence_in_text(cls.evidence, haystack):
        return "quote_missing"
    company = normalize_company(cls.company)
    if company in PLATFORMS:
        return "platform"
    # 公司常常只出现在寄件人（Acme Recruiting <jobs@acme.com>）
    words = _words(f"{msg.from_addr}\n{haystack}")
    title = _words(cls.title).strip()
    # 只要求开头是完整的词：有些信把职称和下一个词黏在一起（「Engineerat Acme」）
    if title and f" {title}" not in words:
        return "not_in_email"
    if company and f" {company}" not in words:
        # 寄件地址里常把公司名连写（homedepot@myworkday.com）；名字太短的不这样比，免得碰巧相符
        glued = company.replace(" ", "")
        if len(glued) < 5 or glued not in re.sub(r"[^a-z0-9]", "", msg.from_addr.lower()):
            return "not_in_email"
    return None


def _words(s: str) -> str:
    # & 写成 and，和 normalize_company 一致（R&A → r and a）
    return f" {re.sub(r'[^a-z0-9]+', ' ', s.lower().replace('&', ' and ')).strip()} "
