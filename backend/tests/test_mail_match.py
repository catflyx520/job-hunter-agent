"""邮件对上职位的规则：只往前改、不编造投递时间、看不准的列为需要确认。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.applications import change_status
from app.mail.classify import MailClassification
from app.mail.match import create_email_job, decide_and_apply, forward, resolve
from app.models import Application, ApplicationEvent, Company, EmailMessage, EmailSync, Job, JobSource, Resume

RECEIVED = datetime(2026, 11, 10, 15, 30, tzinfo=UTC)
_n = 0


def _job(db, title="Backend Engineer", company="Northwind Labs", status=None, req=None, applied_at=None):
    global _n
    _n += 1
    c = db.scalar(select(Company).where(Company.normalized_name == company.lower()))
    if c is None:
        c = Company(display_name=company, normalized_name=company.lower())
        db.add(c)
        db.flush()
    job = Job(company_id=c.id, canonical_key=f"k{_n}", title=title, requisition_id=req, work_mode="unknown",
              employment_type="unknown", sponsorship_policy="unclear", status="active")  # fmt: skip
    db.add(job)
    db.flush()
    if status:
        db.add(Application(job_id=job.id, status=status, applied_at=applied_at,
                           previous_status="saved" if status == "dismissed" else None))  # fmt: skip
        db.flush()
    return job


def _mail(db, kind, company="Northwind Labs", title="Backend Engineer", req=""):
    global _n
    _n += 1
    sync = db.scalar(select(EmailSync)) or EmailSync(status="running", window_after=RECEIVED - timedelta(days=30))
    db.add(sync)
    db.flush()
    row = EmailMessage(id=f"m{_n}", account="me@example.com", rfc822_id=f"<{_n}@x>", thread_id="t", sync_id=sync.id,
                       received_at=RECEIVED, from_addr="jobs@northwind.test", subject="Your application",
                       kind=kind, company=company, title=title, requisition_id=req, outcome="needs_review")  # fmt: skip
    db.add(row)
    db.flush()
    cls = MailClassification(kind=kind, company=company, title=title, requisition_id=req, evidence="x")
    return row, cls


def _app(db, job):
    return db.scalar(select(Application).where(Application.job_id == job.id))


def test_forward_rules():
    assert forward("saved", "applied") and forward("ghosted", "interviewing") and forward("applied", "rejected")
    assert not forward("interviewing", "applied") and not forward("offer", "rejected")
    assert not forward("rejected", "offer")


def test_receipt_exact_match_sets_applied_with_receipt_time(db_session):
    job = _job(db_session, status="saved")
    row, cls = _mail(db_session, "application_received", title="Backend  engineer")
    d = decide_and_apply(db_session, row, cls, None)
    app = _app(db_session, job)
    assert d.outcome == "updated" and (d.from_status, d.to_status) == ("saved", "applied")
    assert app.status == "applied" and app.applied_at == RECEIVED and app.resume_id is None
    ev = app.events[-1]
    assert ev.source == "email" and ev.email_message_id == row.id and ev.at == RECEIVED
    assert row.outcome == "updated" and row.job_id == job.id


def test_receipt_without_application_creates_one(db_session):
    job = _job(db_session)
    row, cls = _mail(db_session, "application_received", req="")
    assert decide_and_apply(db_session, row, cls, None).outcome == "updated"
    app = _app(db_session, job)
    assert app.status == "applied" and app.applied_at == RECEIVED and app.events[0].source == "email"


def test_receipt_matches_by_requisition(db_session):
    job = _job(db_session, title="Software Engineer II", req="R-123", status="saved")
    row, cls = _mail(db_session, "application_received", title="SWE 2 Platform", req="r-123")
    assert decide_and_apply(db_session, row, cls, None).job_id == job.id


def test_receipt_on_interviewing_is_evidence_only(db_session):
    earlier = RECEIVED - timedelta(days=5)
    job = _job(db_session, status="interviewing", applied_at=earlier)
    row, cls = _mail(db_session, "application_received")
    d = decide_and_apply(db_session, row, cls, None)
    app = _app(db_session, job)
    assert d.outcome == "evidence_only" and row.job_id == job.id
    assert app.status == "interviewing" and app.applied_at == earlier and app.events == []


def test_receipt_similar_title_needs_review(db_session):
    job = _job(db_session, title="Senior Backend Engineer")
    row, cls = _mail(db_session, "application_received", title="Backend Engineer")
    d = decide_and_apply(db_session, row, cls, None)
    assert d.outcome == "needs_review" and str(job.id) in row.candidates and _app(db_session, job) is None


def test_receipt_new_company_creates_job(db_session):
    _job(db_session, title="Data Analyst")  # 同公司但不相近
    row, cls = _mail(db_session, "application_received", title="Platform Engineer")
    d = decide_and_apply(db_session, row, cls, None)
    job = db_session.get(Job, d.job_id)
    assert d.outcome == "created" and job.title == "Platform Engineer"
    assert job.verification_source == "email" and job.status == "unverified"
    src = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))
    assert src.site_id == "email" and "rfc822msgid" in src.url
    app = _app(db_session, job)
    assert app.status == "applied" and app.applied_at == RECEIVED


def test_receipt_missing_title_needs_review(db_session):
    row, cls = _mail(db_session, "application_received", title="")
    assert decide_and_apply(db_session, row, cls, None).outcome == "needs_review"
    assert db_session.scalar(select(Job)) is None


def test_review_reason_wins(db_session):
    _job(db_session, status="saved")
    row, cls = _mail(db_session, "application_received")
    d = decide_and_apply(db_session, row, cls, "quote_missing")
    assert d.outcome == "needs_review" and row.reason == "quote_missing"


def test_not_evidence_ignored(db_session):
    row, cls = _mail(db_session, "not_evidence")
    assert decide_and_apply(db_session, row, cls, None).outcome == "ignored"


def test_rejection_unique_submitted_job(db_session):
    earlier = RECEIVED - timedelta(days=9)
    job = _job(db_session, status="applied", applied_at=earlier)
    _job(db_session, title="Data Analyst", status="saved")  # 没投递的不算
    row, cls = _mail(db_session, "rejection", title="")
    d = decide_and_apply(db_session, row, cls, None)
    app = _app(db_session, job)
    assert d.outcome == "updated" and app.status == "rejected" and app.applied_at == earlier


def test_rejection_two_submitted_jobs_needs_review(db_session):
    _job(db_session, status="applied")
    _job(db_session, title="Data Engineer", status="applied")
    row, cls = _mail(db_session, "rejection", title="")
    d = decide_and_apply(db_session, row, cls, None)
    assert d.outcome == "needs_review" and len(row.candidates) == 2


def test_interview_without_title_needs_review(db_session):
    _job(db_session, status="applied")  # 公司唯一的已投递职位也不行
    row, cls = _mail(db_session, "interview", title="")
    assert decide_and_apply(db_session, row, cls, None).outcome == "needs_review"


def test_interview_exact_title(db_session):
    job = _job(db_session, status="applied")
    row, cls = _mail(db_session, "interview")
    decide_and_apply(db_session, row, cls, None)
    assert _app(db_session, job).status == "interviewing"


def test_dismissed_job_needs_review(db_session):
    job = _job(db_session, status="dismissed")
    row, cls = _mail(db_session, "application_received")
    assert decide_and_apply(db_session, row, cls, None).outcome == "needs_review"
    assert _app(db_session, job).status == "dismissed"


def test_rejection_on_saved_needs_review(db_session):
    job = _job(db_session, status="saved")
    row, cls = _mail(db_session, "rejection")
    assert decide_and_apply(db_session, row, cls, None).outcome == "needs_review"
    assert _app(db_session, job).status == "saved"


def test_offer_not_overwritten_by_rejection(db_session):
    job = _job(db_session, status="offer")
    row, cls = _mail(db_session, "rejection")
    assert decide_and_apply(db_session, row, cls, None).outcome == "evidence_only"
    assert _app(db_session, job).status == "offer"


def test_ghosted_moves_to_interviewing(db_session):
    job = _job(db_session, status="ghosted")
    row, cls = _mail(db_session, "interview")
    decide_and_apply(db_session, row, cls, None)
    assert _app(db_session, job).status == "interviewing"


def test_rejection_creates_no_applied_at(db_session):
    row, _ = _mail(db_session, "rejection", title="")
    d = resolve(db_session, row, "create", company="Contoso", title="QA Engineer")
    app = _app(db_session, db_session.get(Job, d.job_id))
    assert app.status == "rejected" and app.applied_at is None and row.outcome == "resolved"


def test_resolve_link_dismissed_job(db_session):
    job = _job(db_session, status="dismissed")
    row, _ = _mail(db_session, "application_received")
    d = resolve(db_session, row, "link", job_id=job.id)
    app = _app(db_session, job)
    assert d.to_status == "applied" and app.status == "applied" and app.previous_status is None
    assert app.applied_at == RECEIVED and row.resolved_at is not None


def test_resolve_ignore(db_session):
    row, _ = _mail(db_session, "interview", title="")
    resolve(db_session, row, "ignore")
    assert row.outcome == "ignored" and row.resolved_at is not None


def test_create_email_job_reuses_same_key(db_session):
    row, _ = _mail(db_session, "application_received")
    a = create_email_job(db_session, row, "Contoso", "QA Engineer")
    b = create_email_job(db_session, row, "Contoso", "QA Engineer")
    assert a.id == b.id


def test_user_change_status_unchanged(db_session):
    resume = Resume(
        label="r",
        filename="r.pdf",
        mime="application/pdf",
        file_path="x",
        sha256="abc",
        raw_text="r",
        parsed={},
        is_active=True,
    )
    db_session.add(resume)
    job = _job(db_session, status="saved")
    db_session.flush()
    app = _app(db_session, job)
    change_status(db_session, app, "applied")
    db_session.flush()
    assert app.applied_at is not None and app.resume_id == resume.id
    ev = db_session.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id))
    assert ev.source == "user"


def test_reasons_are_codes_with_text(db_session):
    from app.mail.match import reason_text

    row, cls = _mail(db_session, "interview", title="")
    decide_and_apply(db_session, row, cls, None)
    assert row.reason == "interview_no_match" and "面试信" in reason_text(row.reason)
    assert reason_text("unclassified: boom") == "模型无法判断这封信是什么：boom"
    assert reason_text(None) is None and reason_text("旧的文字原因") == "旧的文字原因"


def test_receipt_without_title_unique_submitted_job_is_evidence(db_session):
    earlier = RECEIVED - timedelta(days=3)
    job = _job(db_session, status="applied", applied_at=earlier)
    row, cls = _mail(db_session, "application_received", title="")
    d = decide_and_apply(db_session, row, cls, None)
    app = _app(db_session, job)
    assert d.outcome == "evidence_only" and row.job_id == job.id
    assert app.status == "applied" and app.applied_at == earlier and app.events == []


def test_receipt_without_title_unique_saved_job_needs_review(db_session):
    job = _job(db_session, status="saved")
    row, cls = _mail(db_session, "application_received", title="")
    d = decide_and_apply(db_session, row, cls, None)
    assert d.outcome == "needs_review" and row.reason == "no_title" and row.candidates == [str(job.id)]
    assert _app(db_session, job).status == "saved"


def test_resolve_rechecks_same_company(db_session):
    a, cls_a = _mail(db_session, "interview", company="MSI", title="Software Programmer II")
    b, cls_b = _mail(db_session, "interview", company="MSI", title="Software Programmer II")
    c, cls_c = _mail(db_session, "rejection", company="MSI", title="Software Programmer II")
    other, cls_o = _mail(db_session, "interview", company="Contoso", title="Software Programmer II")
    for row, cls in ((a, cls_a), (b, cls_b), (other, cls_o)):
        assert decide_and_apply(db_session, row, cls, None).outcome == "needs_review"
    assert decide_and_apply(db_session, c, cls_c, "not_in_email").outcome == "needs_review"  # 没核对过的不自动处理

    d = resolve(db_session, a, "create", company="MSI", title="Software Programmer II")
    assert d.rechecked == 1 and b.outcome == "evidence_only" and b.job_id == d.job_id and b.resolved_at
    assert c.outcome == "needs_review" and other.outcome == "needs_review"
    assert _app(db_session, db_session.get(Job, d.job_id)).status == "interviewing"


def test_rejection_with_title_and_no_job_creates_rejected_job(db_session):
    _job(db_session, title="Data Analyst", status="applied")  # 同公司但职称不相近
    row, cls = _mail(db_session, "rejection", title="Platform Engineer")
    d = decide_and_apply(db_session, row, cls, None)
    job = db_session.get(Job, d.job_id)
    app = _app(db_session, job)
    assert d.outcome == "created" and job.title == "Platform Engineer" and job.verification_source == "email"
    assert app.status == "rejected" and app.applied_at is None and app.resume_id is None  # 不编造投递时间
    assert [(e.to_status, e.source, e.email_message_id) for e in app.events] == [("rejected", "email", row.id)]


def test_rejection_similar_title_needs_review(db_session):
    job = _job(db_session, title="Senior Backend Engineer", status="applied")
    row, cls = _mail(db_session, "rejection", title="Backend Engineer")
    d = decide_and_apply(db_session, row, cls, None)
    assert d.outcome == "needs_review" and row.reason == "similar" and row.candidates == [str(job.id)]
    assert _app(db_session, job).status == "applied"


def test_offer_without_job_still_needs_review(db_session):
    row, cls = _mail(db_session, "offer", title="Platform Engineer")
    d = decide_and_apply(db_session, row, cls, None)
    assert d.outcome == "needs_review" and row.reason == "no_job" and db_session.scalar(select(Job)) is None


def test_untrusted_rejection_is_not_auto_created(db_session):
    row, cls = _mail(db_session, "rejection", title="Platform Engineer")
    assert decide_and_apply(db_session, row, cls, "not_in_email").outcome == "needs_review"
    assert db_session.scalar(select(Job)) is None


def test_candidates_include_companies_with_same_leading_name(db_session):
    from app.mail.sync import needs_review

    job = _job(db_session, title="Software Engineer I", company="Innova Electronics", status="applied")
    _job(db_session, title="Support Engineer", company="Aurora Innovation", status="applied")
    row, cls = _mail(db_session, "interview", company="Innova", title="")
    decide_and_apply(db_session, row, cls, None)
    assert row.outcome == "needs_review" and row.candidates is None  # 自动规则只认公司名完全相同的
    item = needs_review(db_session)[0]
    assert [c["job_id"] for c in item["candidates"]] == [str(job.id)]  # 候选名单放宽，让用户选


def test_candidates_from_sender_domain_when_no_company(db_session):
    from app.mail.sync import needs_review

    job = _job(db_session, title="Software Engineer I", company="Innova Electronics", status="applied")
    row, cls = _mail(db_session, "interview", company="", title="")
    row.company, row.from_addr = None, "Sam Lee <sam.lee@innova.com>"
    decide_and_apply(db_session, row, cls, None)
    assert [c["job_id"] for c in needs_review(db_session)[0]["candidates"]] == [str(job.id)]
    row.from_addr = "Sam Lee <sam.lee@gmail.com>"  # 一般信箱、求职平台的网域不拿来猜公司
    assert needs_review(db_session)[0]["candidates"] == []
