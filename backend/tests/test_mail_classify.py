"""邮件分类：假 provider；原句必须出现在信里。"""

import json
from datetime import UTC, datetime

from app.llm.fake import FakeProvider
from app.mail.classify import MAX_BODY, classify, classify_batch
from app.mail.gmail import MailMessage


def _msg(text="Thank you for applying to Backend Engineer at Northwind Labs.", sender="jobs@northwind.test"):
    return MailMessage("m1", "t1", "<a@b>", datetime(2026, 11, 10, tzinfo=UTC), sender, "Thanks", text)


def _fake(**kw):
    body = {"kind": "application_received", "company": "Northwind Labs", "title": "Backend Engineer",
            "requisition_id": "", "evidence": "Thank you for applying to Backend Engineer", **kw}  # fmt: skip
    return FakeProvider([json.dumps(body)])


def test_classify_receipt():
    cls, reason = classify(_fake(), _msg())
    assert cls.kind == "application_received" and cls.company == "Northwind Labs" and reason is None


def test_classify_evidence_missing():
    cls, reason = classify(_fake(evidence="We received your application for Staff Engineer"), _msg())
    assert cls.kind == "application_received" and reason == "quote_missing"


def test_classify_not_evidence_needs_no_quote():
    _, reason = classify(_fake(kind="not_evidence", evidence=""), _msg("New jobs for you: Backend Engineer"))
    assert reason is None


def test_classify_platform_sender():
    fake = _fake()
    classify(fake, _msg(sender="LinkedIn <jobs-noreply@linkedin.com>"))
    system = fake.calls[0][0][0].content
    assert "LinkedIn" in system and "employer" in system and "complete your application" in system


def test_classify_truncates_body():
    fake = _fake(kind="not_evidence", evidence="")
    classify(fake, _msg("x" * 10_000))
    user = fake.calls[0][0][-1].content
    assert user.count("x") == MAX_BODY == 6000


def test_platform_company_needs_review():
    _, reason = classify(_fake(company="LinkedIn", evidence="Thank you for applying"),
                         _msg("Thank you for applying to Backend Engineer. LinkedIn"))  # fmt: skip
    assert reason == "platform"


def test_company_not_in_email_needs_review():
    _, reason = classify(_fake(company="Contoso"), _msg())
    assert reason == "not_in_email"


def test_receipt_title_not_in_email_needs_review():
    _, reason = classify(_fake(title="Staff Engineer"), _msg())
    assert reason == "not_in_email"


def test_company_suffix_still_matches():
    _, reason = classify(_fake(company="Northwind Labs, Inc."), _msg())
    assert reason is None


def test_classify_batch():
    good = _msg()
    bad = _msg("Thank you for applying to Data Engineer at Northwind Labs.")
    third = _msg("Thank you for applying to QA Engineer at Northwind Labs.")
    item = {"kind": "application_received", "company": "Northwind Labs", "requisition_id": ""}
    results = [
        {**item, "index": 1, "title": "Backend Engineer", "evidence": "Thank you for applying to Backend Engineer"},
        {**item, "index": 2, "title": "Data Engineer", "evidence": "We received your application for Staff Engineer"},
    ]  # 第 3 封漏掉
    fake = FakeProvider([json.dumps({"results": results})])
    out = classify_batch(fake, [good, bad, third])
    assert len(fake.calls) == 1 and "=== Email 3 ===" in fake.calls[0][0][-1].content
    assert out[0][0].title == "Backend Engineer" and out[0][1] is None
    assert out[1][1] == "quote_missing"
    assert out[2][0].kind == "not_evidence" and out[2][1] == "skipped"


def test_company_only_in_sender_is_ok():
    msg = _msg("Your appointment is booked: Initial Interview.", sender="Fluz Recruiting <noreply@fluz.app>")
    _, reason = classify(_fake(kind="interview", company="Fluz", title="", evidence="Your appointment is booked"), msg)
    assert reason is None


def test_ampersand_company_is_ok():
    msg = _msg("An update on your application from R&A Risk Professionals for Backend Engineer.")
    fake = _fake(kind="rejection", company="R&A Risk Professionals", evidence="An update on your application")
    assert classify(fake, msg)[1] is None


def test_title_glued_to_next_word_is_ok():
    msg = _msg("We received your application for the Backend Engineerat Northwind Labs.")
    assert classify(_fake(evidence="We received your application"), msg)[1] is None


def test_company_inside_another_word_is_not_ok():
    msg = _msg("Thank you for applying to Backend Engineer. Regards, Potter team")
    fake = _fake(company="Otter", evidence="Thank you for applying to Backend Engineer")
    assert classify(fake, msg)[1] == "not_in_email"


def test_company_glued_in_sender_address_is_ok():
    msg = _msg("Thank you for applying! We have received your application.", sender="Workday <homedepot@myworkday.com>")
    fake = _fake(company="Home Depot", title="", evidence="We have received your application")
    assert classify(fake, msg)[1] is None
    short = _fake(company="AB", title="", evidence="We have received your application")
    assert classify(short, msg)[1] == "not_in_email"  # 太短的名字不用这个宽松比对
