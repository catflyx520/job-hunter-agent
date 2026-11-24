"""把分类好的信对上职位并写入状态（程式判断，不交给模型）。
规则：只往前改；不覆盖已有的投递时间与证据；不编造投递时间；看不准的列为需要确认，由用户在 summary 处理。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import literal, or_, select
from sqlalchemy.orm import Session

from app.api.applications import SUBMITTED, change_status
from app.core.i18n import tr
from app.jobs.exclusion import title_matches
from app.jobs.normalize import canonical_key, normalize_company, normalize_title
from app.jobs.service import upsert_company
from app.mail.classify import PLATFORMS, MailClassification
from app.models import Application, ApplicationEvent, Company, EmailMessage, Job, JobSource

RANK = {"saved": 0, "referred": 1, "applied": 1, "ghosted": 1, "interviewing": 2, "offer": 3, "rejected": 3}
TARGET = {"application_received": "applied", "interview": "interviewing", "rejection": "rejected", "offer": "offer"}

Outcome = Literal["created", "updated", "evidence_only", "needs_review", "ignored", "resolved"]

# 「需要确认」的原因：资料库存代码，给用户看的句子在输出时才依介面语言产生
REASONS: dict[str, Callable[[], str]] = {
    # 模型的答案没通过核对（classify._check、sync）
    "quote_missing": lambda: tr("模型给的原句在信里找不到。"),
    "platform": lambda: tr("雇主名称是求职平台；如果你投的就是这家公司，请按「新建为职位」。"),
    "not_in_email": lambda: tr("模型给的公司或职称在信里找不到。"),
    "skipped": lambda: tr("模型漏掉了这封信。"),
    # 内容可信，但对不上职位
    "no_company": lambda: tr("信里没有写公司名称。"),
    "no_title": lambda: tr("信里没有写职称。"),
    "same_title_many": lambda: tr("有多个职位名称相同，不确定是哪一个。"),
    "similar": lambda: tr("同公司有名称相近的职位，不确定是不是同一个。"),
    "interview_no_match": lambda: tr("面试信没有写出对得上的职位名称，无法确定是哪个职位。"),
    "dismissed": lambda: tr("对到的职位已删除。"),
    "not_applied": lambda: tr("对到的职位还没有投递记录。"),
    "many_submitted": lambda: tr("这家公司有多个已投递的职位，信里没写是哪一个。"),
    "no_job": lambda: tr("找不到对应的职位。"),
}
# 没通过核对的信只能由用户决定，不会自动套规则
UNTRUSTED = {"quote_missing", "platform", "not_in_email", "skipped", "unclassified"}


def reason_text(reason: str | None) -> str | None:
    if not reason:
        return None
    code, _, detail = reason.partition(": ")
    if code == "unclassified":
        return tr("模型无法判断这封信是什么：{e}", e=detail)
    return REASONS[reason]() if reason in REASONS else reason  # 不是代码就原样显示


@dataclass
class Decision:
    outcome: Outcome
    job_id: uuid.UUID | None = None
    reason: str | None = None
    candidates: list[uuid.UUID] = field(default_factory=list)
    from_status: str | None = None
    to_status: str | None = None
    rechecked: int = 0  # 用户处理这封之后，同公司另外几封也跟着自动处理了


def forward(current: str, to: str) -> bool:
    """只往前：offer 与 rejected 之间不互改。"""
    return RANK.get(to, 0) > RANK.get(current, 0)


def _app(db: Session, job_id: uuid.UUID) -> Application | None:
    return db.scalar(select(Application).where(Application.job_id == job_id))


def company_jobs(db: Session, company: str) -> list[Job]:
    norm = normalize_company(company)
    if not norm:
        return []
    return list(db.scalars(select(Job).join(Company).where(Company.normalized_name == norm).order_by(Job.created_at)))


# 一般信箱：寄件网域不代表公司
MAIL_HOSTS = {"gmail", "googlemail", "google", "outlook", "hotmail", "live", "msn", "yahoo", "icloud", "aol", "proton"}


def _sender_company(from_addr: str) -> str:
    """寄件网域的主要部分（jobs@acme.com → acme）；一般信箱、求职平台与 ATS 的网域不算。"""
    m = re.search(r"@([\w.-]+)", from_addr or "")
    parts = m.group(1).lower().split(".") if m else []
    label = parts[-2] if len(parts) >= 2 else ""
    if len(label) < 3 or label in MAIL_HOSTS or any(p in label for p in PLATFORMS):
        return ""
    return label


def candidate_jobs(db: Session, company: str | None, from_addr: str = "") -> list[Job]:
    """给用户选的候选职位：公司名相同的，加上公司名开头相同的（Innova → Innova Electronics）；
    信里没写公司就用寄件网域来找。只用来列清单让用户选，自动规则仍然只认公司名完全相同的。"""
    exact = company_jobs(db, company or "")
    norm = normalize_company(company or "") or _sender_company(from_addr)
    if len(norm) < 3:
        return exact
    related = (
        select(Job)
        .join(Company)
        .where(or_(Company.normalized_name.like(f"{norm} %"), literal(norm).like(Company.normalized_name + " %")))
    )
    seen = {j.id for j in exact}
    return exact + [j for j in db.scalars(related.order_by(Job.created_at)) if j.id not in seen]


def _exact(job: Job, title: str, req: str) -> bool:
    if req and job.requisition_id and req.strip().lower() == job.requisition_id.strip().lower():
        return True
    return bool(title.strip()) and normalize_title(job.title) == normalize_title(title)


def similar_title(job: Job, title: str) -> bool:
    return bool(title.strip()) and (title_matches(job.title, title) or title_matches(title, job.title))


def _status(db: Session, job: Job) -> str | None:
    app = _app(db, job.id)
    return app.status if app else None


def _apply(db: Session, job: Job, row: EmailMessage, kind: str) -> tuple[str | None, str]:
    """把信的结果写进这个职位（呼叫者已确认可以往前改）。回传 (原状态, 新状态)。"""
    to = TARGET[kind]
    applied_at = row.received_at if kind == "application_received" else None
    app = _app(db, job.id)
    if app is None:
        app = Application(job_id=job.id, status=to, applied_at=applied_at if to in SUBMITTED else None)
        db.add(app)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=app.id,
                from_status=None,
                to_status=to,
                source="email",
                email_message_id=row.id,
                at=row.received_at,
            )
        )
        db.flush()
        return None, to
    frm = app.status
    if frm == "dismissed":
        app.previous_status = None  # 用户把信对到已删除的职位：等于还原
    change_status(db, app, to, email=row, applied_at=applied_at)
    db.flush()
    return frm, to


def create_email_job(db: Session, row: EmailMessage, company: str, title: str, requisition_id: str = "") -> Job:
    """从信建出职位（没有 JD、未验证、来源 email）；同一个去重键已存在就回传那个。"""
    c = upsert_company(db, company)
    db.flush()
    key = canonical_key(c.normalized_name, title, "", requisition_id)
    job = db.scalar(select(Job).where(Job.canonical_key == key))
    if job is None:
        job = Job(
            company_id=c.id,
            canonical_key=key,
            requisition_id=requisition_id.strip() or None,
            title=title.strip(),
            work_mode="unknown",
            employment_type="unknown",
            sponsorship_policy="unclear",
            status="unverified",
            verification_source="email",
        )
        db.add(job)
        db.flush()
    url = row.gmail_url
    if db.scalar(select(JobSource.id).where(JobSource.url == url)) is None:
        db.add(JobSource(job_id=job.id, site_id="email", url=url, last_seen_at=row.received_at))
        db.flush()
    return job


def _set(row: EmailMessage, d: Decision) -> Decision:
    row.outcome, row.job_id, row.reason = d.outcome, d.job_id, d.reason
    row.candidates = [str(c) for c in d.candidates] or None
    return d


def _to_job(db: Session, job: Job, row: EmailMessage, kind: str) -> Decision:
    """对到唯一一个职位之后：已删除、还没投递（非确认信）→ 需要确认；不是往前 → 只记证据。"""
    current = _status(db, job)
    if current == "dismissed":
        return Decision("needs_review", reason="dismissed", candidates=[job.id])
    if kind != "application_received" and current not in SUBMITTED:
        return Decision("needs_review", reason="not_applied", candidates=[job.id])
    if current is not None and not forward(current, TARGET[kind]):
        return Decision("evidence_only", job_id=job.id)
    frm, to = _apply(db, job, row, kind)
    return Decision("updated", job_id=job.id, from_status=frm, to_status=to)


def _decide(db: Session, row: EmailMessage, cls: MailClassification) -> Decision:
    kind = cls.kind
    if kind == "not_evidence":
        return Decision("ignored")
    if not cls.company.strip():
        return Decision("needs_review", reason="no_company")
    jobs = company_jobs(db, cls.company)
    exact = [j for j in jobs if _exact(j, cls.title, cls.requisition_id)]
    if len(exact) == 1:
        return _to_job(db, exact[0], row, kind)
    if len(exact) > 1:
        return Decision("needs_review", reason="same_title_many", candidates=[j.id for j in exact])

    if kind == "application_received":
        if not cls.title.strip():
            # 很多确认信只写公司。公司只有一个职位、而且已经投递：这封信就是它的证据；其他情况让用户决定
            if len(jobs) == 1 and _status(db, jobs[0]) in SUBMITTED:
                return Decision("evidence_only", job_id=jobs[0].id)
            return Decision("needs_review", reason="no_title", candidates=[j.id for j in jobs])
        similar = [j for j in jobs if similar_title(j, cls.title)]
        if similar:
            return Decision("needs_review", reason="similar", candidates=[j.id for j in similar])
        job = create_email_job(db, row, cls.company, cls.title, cls.requisition_id)
        frm, to = _apply(db, job, row, kind)
        return Decision("created", job_id=job.id, from_status=frm, to_status=to)

    if kind == "interview":
        return Decision("needs_review", reason="interview_no_match", candidates=[j.id for j in jobs])
    # 拒信 / offer
    submitted = [j for j in jobs if _status(db, j) in SUBMITTED]
    if not cls.title.strip():
        # 没写职位：公司只有一个已投递的职位才算
        if len(submitted) == 1:
            return _to_job(db, submitted[0], row, kind)
        reason = "many_submitted" if len(submitted) > 1 else "no_job"
        return Decision("needs_review", reason=reason, candidates=[j.id for j in (submitted or jobs)])
    similar = [j for j in jobs if similar_title(j, cls.title)]
    if similar:
        return Decision("needs_review", reason="similar", candidates=[j.id for j in similar])
    if kind == "rejection":
        # 拒信写明公司与职称、库里没有这个职位：拒信能证明投过，自动建出来记「被拒」；
        # 什么时候投的不知道，投递时间留空（作者 2026-11-18 决定）。offer 仍由用户确认
        job = create_email_job(db, row, cls.company, cls.title, cls.requisition_id)
        frm, to = _apply(db, job, row, kind)
        return Decision("created", job_id=job.id, from_status=frm, to_status=to)
    return Decision("needs_review", reason="no_job", candidates=[j.id for j in (submitted or jobs)])


def can_bulk_create(db: Session, row: EmailMessage) -> bool:
    """可以不逐封看就新建成职位：信里写明公司与职称（核对过）、找不到对应职位、同公司也没有名称相近的。"""
    if row.reason != "no_job" or not (row.company and row.title):
        return False
    return not any(similar_title(j, row.title) for j in company_jobs(db, row.company))


def recheck_company(db: Session, company_norm: str, skip_id: str) -> int:
    """用户处理完一封之后，同公司其他还没处理、内容可信的信按同一套规则再判一次
    （例如刚建出的职位现在对得上了）。回传跟着处理掉几封。"""
    done = 0
    q = select(EmailMessage).where(EmailMessage.outcome == "needs_review", EmailMessage.id != skip_id)
    for r in db.scalars(q.order_by(EmailMessage.received_at)).all():
        if r.kind == "not_evidence" or r.reason not in REASONS or r.reason in UNTRUSTED:
            continue
        if normalize_company(r.company or "") != company_norm:
            continue
        cls = MailClassification(
            kind=r.kind, company=r.company or "", title=r.title or "", requisition_id=r.requisition_id or ""
        )
        if _set(r, _decide(db, r, cls)).outcome != "needs_review":
            r.resolved_at = datetime.now(UTC)
            done += 1
    return done


def decide_and_apply(db: Session, row: EmailMessage, cls: MailClassification, review_reason: str | None) -> Decision:
    if review_reason and cls.kind != "not_evidence":
        jobs = company_jobs(db, cls.company)
        return _set(row, Decision("needs_review", reason=review_reason, candidates=[j.id for j in jobs]))
    return _set(row, _decide(db, row, cls))


def resolve(
    db: Session,
    row: EmailMessage,
    action: Literal["link", "create", "ignore"],
    job_id: uuid.UUID | None = None,
    company: str = "",
    title: str = "",
) -> Decision:
    """用户在 summary 处理需要确认的信。用户决定的，所以可以对到还没投递或已删除的职位；仍然只往前。"""
    row.resolved_at = datetime.now(UTC)
    if action == "ignore" or row.kind == "not_evidence":
        row.outcome = "ignored"
        return Decision("ignored")
    if action == "create":
        job = create_email_job(db, row, company, title, row.requisition_id or "")
    else:
        job = db.get(Job, job_id)
        if job is None:
            raise LookupError(tr("找不到这个职位"))
    app = _app(db, job.id)
    current = app.status if app else None
    base = (app.previous_status or "saved") if current == "dismissed" else current
    d = Decision("resolved", job_id=job.id)
    if base is None or forward(base, TARGET[row.kind]):
        d.from_status, d.to_status = _apply(db, job, row, row.kind)
    elif current == "dismissed":
        change_status(db, app, base, email=row)  # 还原到删除前的状态
        app.previous_status = None
        d.from_status, d.to_status = current, base
    row.outcome, row.job_id, row.reason = "resolved", job.id, None
    db.flush()
    d.rechecked = recheck_company(db, job.company.normalized_name, row.id)
    db.flush()
    return d
