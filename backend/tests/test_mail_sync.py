"""邮件同步：时间窗口、重叠不重复、200 封上限、授权失效、中断复原、summary。"""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.llm.base import LLMError
from app.llm.fake import FakeProvider
from app.mail import sync as mail_sync
from app.mail.gmail import GmailError, GmailReconnect, MailMessage
from app.models import Company, EmailMessage, EmailSync, Integration, Job

NOW = datetime.now(UTC)


class FakeGmail:
    def __init__(self, msgs: list[MailMessage], error: Exception | None = None, fail_get: set[str] = frozenset()):
        self.msgs = {m.id: m for m in msgs}
        self.order = sorted(msgs, key=lambda m: m.received_at, reverse=True)  # Gmail：新到旧
        self.queries: list[str] = []
        self.error = error
        self.fail_get = fail_get

    def list_ids(self, query, limit=2000):
        """照 Gmail 的规则：after / before（秒）过滤，新到旧，最多 limit 个。"""
        self.queries.append(query)
        if self.error:
            raise self.error
        after = int(re.search(r"after:(\d+)", query).group(1))
        m = re.search(r"before:(\d+)", query)
        before = int(m.group(1)) if m else None
        hits = [
            x
            for x in self.order
            if x.received_at.timestamp() >= after and (before is None or x.received_at.timestamp() < before)
        ]
        return [(x.id, x.thread_id) for x in hits][:limit]

    def get(self, mid):
        if mid in self.fail_get:
            raise GmailError("Gmail 回应 500。")
        return self.msgs[mid]


def _mail(i: int, subject="Thanks for applying", text=None, days_ago=1.0):
    text = text or f"Thank you for applying to Role {i} at Northwind Labs."
    return MailMessage(f"m{i:03d}", f"t{i}", f"<{i}@x>", NOW - timedelta(days=days_ago), "jobs@nw.test", subject, text)


def _responder(messages, json_mode):
    """一批信（=== Email N === 分隔）逐封套用 _one，回 {results: [...]}；一封的就直接回。"""
    body = messages[-1].content
    parts = re.split(r"=== Email (\d+) ===", body)
    if len(parts) == 1:
        return _one(body)
    if "BROKEN" in body:
        raise LLMError("model returned garbage")
    results = [{**json.loads(_one(text)), "index": int(i)} for i, text in zip(parts[1::2], parts[2::2], strict=True)]
    return json.dumps({"results": results})


def _one(body):
    """依信的内容回分类：Role N 的确认信；含 'unfortunately' 的是拒信；含 'interview' 的是没写职位的面试信。"""
    if "BROKEN" in body:
        raise LLMError("model returned garbage")
    if "FAKEQUOTE" in body:
        return json.dumps({"kind": "application_received", "company": "Northwind Labs", "title": "",
                           "evidence": "We loved your application so much"})  # fmt: skip
    if "unfortunately" in body:
        return json.dumps({"kind": "rejection", "company": "Northwind Labs", "title": "",
                           "evidence": "unfortunately we will not move forward"})  # fmt: skip
    if "interview" in body:
        role = re.search(r"interview for (Role \d+)", body)
        return json.dumps({"kind": "interview", "company": "Northwind Labs", "title": role.group(1) if role else "",
                           "evidence": "we would like to schedule an interview"})  # fmt: skip
    role = body.split("applying to ")[1].split(" at ")[0]
    return json.dumps({"kind": "application_received", "company": "Northwind Labs", "title": role,
                       "evidence": f"Thank you for applying to {role}"})  # fmt: skip


@pytest.fixture
def setup(db_session, monkeypatch):
    db_session.add(
        Integration(
            kind="gmail",
            config={"client_id": "cid", "email": "me@example.com"},
            secret_encrypted=encrypt_secret(json.dumps({"client_secret": "s", "refresh_token": "r"})),
            enabled=True,
        )
    )
    db_session.commit()
    fake = FakeProvider(_responder)
    monkeypatch.setattr(mail_sync, "provider_for_task", lambda db, task: fake)

    def run(msgs, error=None, fail_get=frozenset()):
        gm = FakeGmail(msgs, error, fail_get)
        monkeypatch.setattr(mail_sync, "gmail_client", lambda db: (gm, "me@example.com"))
        with mail_sync.get_sessionmaker()() as db:
            s = mail_sync.create_sync(db)
            db.commit()
            sid = s.id
        mail_sync.execute_sync(sid)
        db_session.expire_all()
        return db_session.get(EmailSync, sid), gm

    run.fake = fake
    return run


def test_sync_first_window_30_days(setup):
    sync, gm = setup([_mail(1)])
    assert abs((sync.window_after - (datetime.now(UTC) - timedelta(days=30))).total_seconds()) < 60
    assert gm.queries[0].startswith(f"after:{int(sync.window_after.timestamp())}")
    assert sync.status == "completed" and sync.processed == 1, sync.error


def test_sync_overlap_3_days(setup):
    first, _ = setup([_mail(1)])
    second, _ = setup([_mail(1)])
    assert second.window_after == first.window_before - timedelta(days=3)


def test_sync_twice_no_duplicates(setup, db_session):
    setup([_mail(1), _mail(2)])
    calls = len(setup.fake.calls)
    second, _ = setup([_mail(1), _mail(2)])
    assert len(setup.fake.calls) == calls and second.processed == 0 and second.fetched == 0
    assert len(db_session.scalars(select(Job)).all()) == 2


def test_sync_cap_200_oldest_first(setup, db_session):
    msgs = [_mail(i, days_ago=20 - i * 0.05) for i in range(250)]  # i 越大越新
    sync, _ = setup(msgs)
    assert sync.processed == 200 and sync.fetched == 200 and sync.truncated
    assert sync.window_before == msgs[199].received_at
    assert db_session.get(EmailMessage, "m000") is not None and db_session.get(EmailMessage, "m249") is None


def test_sync_reconnect_error(setup):
    sync, _ = setup([], error=GmailReconnect("Gmail 授权已失效，请到 Settings 重新连接 Gmail。"))
    assert sync.status == "failed" and "重新连接" in sync.error and sync.finished_at


def test_failed_sync_does_not_move_window(setup):
    first, _ = setup([_mail(1)])
    setup([], error=GmailReconnect("x"))
    third, _ = setup([_mail(1)])
    assert third.window_after == first.window_before - timedelta(days=3)


def test_sync_running_blocks_second(db_session):
    db_session.add(EmailSync(status="running", window_after=NOW))
    db_session.flush()
    with pytest.raises(mail_sync.GmailError):
        mail_sync.create_sync(db_session)


def test_recover_interrupted_syncs(db_session):
    db_session.add(EmailSync(status="running", window_after=NOW))
    db_session.commit()
    mail_sync.recover_interrupted_syncs()
    db_session.expire_all()
    s = db_session.scalar(select(EmailSync))
    assert s.status == "failed" and "再按一次" in s.error


def test_summary_lists_created_updated_review(setup, db_session):
    first, _ = setup([_mail(1)])
    assert [c["title"] for c in first.summary["created"]] == ["Role 1"]
    rejection = _mail(
        2, "Update", "Hello, unfortunately we will not move forward with your application at Northwind Labs.", 0.5
    )
    interview = _mail(3, "Next steps", "Hi! we would like to schedule an interview at Northwind Labs next week.", 0.4)
    alert = _mail(4, "New jobs", "Thank you for applying to Role 9 at Northwind Labs.", 0.3)
    second, _ = setup([rejection, interview, alert])
    s = second.summary
    assert [(u["from"], u["to"]) for u in s["updated"]] == [("applied", "rejected")]
    assert s["updated"][0]["message"]["gmail_url"].startswith("https://mail.google.com/")
    assert [c["title"] for c in s["created"]] == ["Role 9"]
    review = mail_sync.needs_review(db_session)
    assert [r["message"]["id"] for r in review] == ["m003"] and review[0]["candidates"][0]["title"] == "Role 1"
    assert db_session.scalar(select(Company)).display_name == "Northwind Labs"


def test_failed_sync_keeps_summary(setup):
    msgs = [_mail(i, days_ago=10 - i * 0.1) for i in range(11)]
    sync, _ = setup(msgs, fail_get={"m010"})  # 第二批读信失败：第一批 10 封已经处理
    assert sync.status == "failed" and len(sync.summary["created"]) == 10


def test_classify_failure_does_not_block(setup, db_session):
    broken = _mail(2, "Weird", "BROKEN email body at Northwind Labs", 1)
    sync, _ = setup([_mail(1, days_ago=2), broken])
    assert sync.status == "completed" and sync.processed == 2
    row = db_session.get(EmailMessage, "m002")
    assert row.outcome == "needs_review" and row.reason.startswith("unclassified: ") and row.kind == "not_evidence"


def test_list_limit_shrinks_window(setup, db_session, monkeypatch):
    monkeypatch.setattr(mail_sync, "LIST_LIMIT", 5)
    msgs = [_mail(i, days_ago=29 - 4 * i) for i in range(8)]  # m000 最旧（29 天前），每 4 天一封
    first, _ = setup(msgs)
    first_done = {r.id for r in db_session.scalars(select(EmailMessage))}
    assert first.truncated and first_done == {"m000", "m001", "m002"}  # 先读最旧、列表外的那批
    assert first.window_before == msgs[3].received_at
    second, _ = setup(msgs)
    done = {r.id for r in db_session.scalars(select(EmailMessage))}
    assert done == {f"m{i:03d}" for i in range(8)} and not second.truncated


def test_unverified_quote_not_stored(setup, db_session):
    setup([_mail(5, "Hi", "FAKEQUOTE: thanks for your interest in Northwind Labs.", 1)])
    row = db_session.get(EmailMessage, "m005")
    assert row.outcome == "needs_review" and "loved" not in (row.excerpt or "")
    assert row.excerpt.startswith("FAKEQUOTE")


def test_client_max_new_and_view_url(setup, db_session, monkeypatch):
    msgs = [_mail(i, days_ago=10 - i) for i in range(4)]
    msgs[0].view_url = "https://mail.google.com/mail/u/0/#all/t0"
    monkeypatch.setattr(FakeGmail, "max_new", 2, raising=False)
    sync, _ = setup(msgs)
    assert sync.processed == 2 and sync.truncated and sync.window_before == msgs[1].received_at
    assert db_session.get(EmailMessage, "m000").gmail_url == "https://mail.google.com/mail/u/0/#all/t0"


def test_gmail_client_claude_mode(db_session):
    from app.mail.claude_gmail import ClaudeGmail

    db_session.add(Integration(kind="gmail", config={"mode": "claude_cli"}, enabled=True))
    db_session.flush()
    client, account = mail_sync.gmail_client(db_session)
    assert isinstance(client, ClaudeGmail) and account == ""


def test_classification_is_batched(setup):
    sync, _ = setup([_mail(i, days_ago=10 - i * 0.1) for i in range(12)])
    assert sync.processed == 12 and len(setup.fake.calls) == 2  # 10 + 2
    assert len(sync.summary["created"]) == 12


def test_needs_review_live_candidates_and_bulk_flag(setup, db_session):
    text = "Hello, unfortunately we will not move forward with your application at Northwind Labs."
    setup([_mail(2, "Update", text, 2)])
    item = mail_sync.needs_review(db_session)[0]
    assert item["reason"] == "找不到对应的职位。" and item["candidates"] == []
    assert item["bulk_create"] is False  # 没写职称，不能批量新建
    setup([_mail(1, days_ago=1)])  # 之后同公司有了职位：候选名单跟着更新
    item = mail_sync.needs_review(db_session)[0]
    assert [c["title"] for c in item["candidates"]] == ["Role 1"]


def test_query_change_rescans_30_days(setup, monkeypatch):
    first, _ = setup([_mail(1)])
    assert first.summary["query_version"] == mail_sync.QUERY_VERSION
    monkeypatch.setattr(mail_sync, "QUERY_VERSION", mail_sync.QUERY_VERSION + 1)
    second, _ = setup([_mail(1)])  # 查询条件换了：重读最近 30 天（处理过的信照样跳过）
    assert abs((second.window_after - (datetime.now(UTC) - timedelta(days=30))).total_seconds()) < 60
    assert second.processed == 0
    third, _ = setup([_mail(1)])
    assert third.window_after == second.window_before - timedelta(days=3)
