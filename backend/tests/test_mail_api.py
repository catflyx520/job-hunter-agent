"""邮件同步 API：连接 / 断开、同步、summary、处理需要确认、统计、职位历史的信件证据。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.mail import gmail
from app.mail import sync as mail_sync
from app.models import Integration
from tests.samples import make_jd
from tests.test_mail_sync import FakeGmail, _mail, _responder

REDIRECT = "http://localhost:5173/api/email/gmail/callback"


def _connect(client, monkeypatch):
    url = client.post(
        "/api/email/gmail/auth-url", json={"client_id": "cid", "client_secret": "csecret", "redirect_uri": REDIRECT}
    ).json()["url"]
    state = url.split("state=")[1].split("&")[0]
    got = {"client_id": "cid", "client_secret": "csecret", "refresh_token": "refresh-xyz", "email": "me@example.com"}
    monkeypatch.setattr(gmail, "finish_auth", lambda s, c: gmail._pending.pop(s) and got)
    return client.get(f"/api/email/gmail/callback?state={state}&code=c1", follow_redirects=False)


@pytest.fixture
def synced(client, monkeypatch):
    """连接好 Gmail，背景同步改成直接执行，模型改成假的分类。"""
    _connect(client, monkeypatch)
    from app.llm.fake import FakeProvider

    monkeypatch.setattr(mail_sync, "provider_for_task", lambda db, task: FakeProvider(_responder))
    monkeypatch.setattr(mail_sync, "start_sync", mail_sync.execute_sync)

    def run(msgs):
        monkeypatch.setattr(mail_sync, "gmail_client", lambda db: (FakeGmail(msgs), "me@example.com"))
        r = client.post("/api/email/sync")
        assert r.status_code == 201, r.text
        return client.get(f"/api/email/syncs/{r.json()['id']}").json()

    return run


def test_gmail_status_not_connected(client):
    assert client.get("/api/email/gmail").json()["connected"] is False
    assert client.get("/api/email/syncs/latest").json()["id"] is None


def test_auth_url_requires_client(client):
    r = client.post("/api/email/gmail/auth-url", json={"redirect_uri": REDIRECT})
    assert r.status_code == 422


def test_auth_url_and_callback_store_encrypted(client, monkeypatch):
    r = _connect(client, monkeypatch)
    assert r.status_code == 303 and r.headers["location"] == "http://localhost:5173/settings?view=email&email=connected"
    status = client.get("/api/email/gmail").json()
    assert status["connected"] and status["email"] == "me@example.com" and status["has_client_secret"]
    with get_sessionmaker()() as db:
        row = db.scalar(select(Integration).where(Integration.kind == "gmail"))
        assert b"refresh-xyz" not in row.secret_encrypted and "refresh" not in json.dumps(row.config)
        assert row.config["scope"] == gmail.SCOPE


def test_callback_error_redirects_with_message(client):
    url = client.post(
        "/api/email/gmail/auth-url", json={"client_id": "cid", "client_secret": "s", "redirect_uri": REDIRECT}
    ).json()["url"]
    state = url.split("state=")[1].split("&")[0]
    r = client.get(f"/api/email/gmail/callback?state={state}&error=access_denied", follow_redirects=False)
    assert r.status_code == 303 and "email_error=" in r.headers["location"]
    assert r.headers["location"].startswith("http://localhost:5173/settings")


def test_disconnect_revokes_and_deletes(client, monkeypatch):
    _connect(client, monkeypatch)
    revoked = []
    monkeypatch.setattr(gmail, "revoke", revoked.append)
    assert client.delete("/api/email/gmail").status_code == 204
    assert revoked == ["refresh-xyz"] and client.get("/api/email/gmail").json()["connected"] is False


def test_sync_not_connected_409(client):
    r = client.post("/api/email/sync")
    assert r.status_code == 409 and "连接 Gmail" in r.json()["detail"]


def _existing_job(client, title="Role 1"):
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd(title, "Northwind Labs", "Remote - US")})
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert client.put(f"/api/jobs/{job['id']}/application", json={"status": "applied"}).status_code == 200
    return job


def test_sync_end_to_end(client, synced):
    before = client.get("/api/stats").json()["totals"]["submitted"]
    _existing_job(client, "Data Engineer")
    receipt = _mail(1)  # Role 1：新建
    rejection = _mail(
        2, "Update", "Hello, unfortunately we will not move forward with your application at Northwind Labs.", 0.5
    )
    out = synced([receipt, rejection])
    s = out["summary"]
    assert out["status"] == "completed"
    assert [c["title"] for c in s["created"]] == ["Role 1"]
    assert s["needs_review"] == 1 and len(out["needs_review"]) == 1  # 拒信：两个已投递的职位，看不准
    stats = client.get("/api/stats").json()
    assert stats["totals"]["submitted"] == before + 2
    assert {x["site"]: x["found"] for x in stats["sources"]}.get("email") == 1


def test_resolve_create_and_link(client, synced):
    job = _existing_job(client)
    interview = _mail(3, "Next steps", "Hi! we would like to schedule an interview at Northwind Labs next week.", 0.4)
    other = _mail(4, "Next steps 2", "Hi again, we would like to schedule an interview at Northwind Labs soon.", 0.3)
    out = synced([interview, other])
    review = {r["message"]["id"]: r for r in out["needs_review"]}
    assert review["m003"]["candidates"][0]["job_id"] == job["id"]

    r = client.post("/api/email/messages/m003/resolve", json={"action": "link", "job_id": job["id"]})
    assert r.status_code == 200 and r.json()["decision"]["to"] == "interviewing"
    assert client.post("/api/email/messages/m003/resolve", json={"action": "ignore"}).status_code == 409
    assert client.post("/api/email/messages/m004/resolve", json={"action": "create"}).status_code == 422
    r = client.post(
        "/api/email/messages/m004/resolve", json={"action": "create", "company": "Contoso", "title": "QA Engineer"}
    )
    assert r.status_code == 200 and r.json()["decision"]["to"] == "interviewing"
    assert client.get("/api/email/syncs/latest").json()["needs_review"] == []


def test_event_has_email_evidence(client, synced):
    job = _existing_job(client, "Role 7")
    msg = _mail(7, "Interview for Role 7", "We would like to schedule an interview for Role 7.", 0.2)
    msg.text = "Thank you for applying to Role 7 at Northwind Labs."  # 当成确认信：已投递，只记证据
    synced([msg])
    rej = _mail(
        8,
        "Role 7 update",
        "Hello, unfortunately we will not move forward with your application at Northwind Labs.",
        0.1,
    )
    synced([rej])
    events = client.get(f"/api/jobs/{job['id']}/application").json()["events"]
    last = events[-1]
    assert last["to_status"] == "rejected" and last["source"] == "email"
    assert last["email_message"]["subject"] == "Role 7 update"
    assert last["email_message"]["gmail_url"].startswith("https://mail.google.com/mail/?authuser=me%40example.com")
    assert datetime.fromisoformat(last["at"]) == rej.received_at
    assert datetime.now(UTC) - rej.received_at < timedelta(days=1)


def test_resolve_unclassified_only_ignore(client, synced):
    out = synced([_mail(9, "Weird", "BROKEN email body at Northwind Labs", 0.2)])
    assert [r["message"]["id"] for r in out["needs_review"]] == ["m009"]
    r = client.post("/api/email/messages/m009/resolve", json={"action": "create", "company": "X", "title": "Y"})
    assert r.status_code == 422
    assert client.post("/api/email/messages/m009/resolve", json={"action": "ignore"}).status_code == 200


def test_connect_with_claude_cli(client, monkeypatch):
    from app.mail import claude_gmail

    checked = []
    monkeypatch.setattr(claude_gmail.ClaudeGmail, "check", lambda self: checked.append(1))
    r = client.post("/api/email/gmail/cli")
    assert r.status_code == 200 and r.json()["connected"] and r.json()["mode"] == "claude_cli" and checked
    revoked = []
    monkeypatch.setattr(gmail, "revoke", revoked.append)
    assert client.delete("/api/email/gmail").status_code == 204
    assert revoked == [] and client.get("/api/email/gmail").json()["connected"] is False


def test_connect_with_claude_cli_error(client, monkeypatch):
    from app.mail import claude_gmail

    def boom(self):
        raise gmail.GmailError("Claude CLI 没有连上 Gmail")

    monkeypatch.setattr(claude_gmail.ClaudeGmail, "check", boom)
    r = client.post("/api/email/gmail/cli")
    assert r.status_code == 409 and "没有连上" in r.json()["detail"]
    assert client.get("/api/email/gmail").json()["connected"] is False


def test_posting_found_later_merges_into_email_job(client, synced):
    """邮件先建出职位（只有公司与职称）；之后搜到 / 贴上同公司同职称的职位页，要补进同一个职位，不另建一个。"""
    out = synced([_mail(1)])
    email_job = out["summary"]["created"][0]["job_id"]
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd("Role 1", "Northwind Labs", "Remote - US")})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["job"]["id"] == email_job and body["created"] is False
    assert body["job"]["location_text"] == "Remote - US" and body["job"]["verification_source"] == "pasted"
    assert client.get(f"/api/jobs/{email_job}/application").json()["status"] == "applied"
    assert client.get("/api/stats").json()["totals"]["found"] == 1
    # 同职称、不同地点的第二个职位页：邮件职位已经有 JD 了，照常另建
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd("Role 1", "Northwind Labs", "Austin, TX")})
    assert r.json()["job"]["id"] != email_job


def test_two_email_jobs_same_title_not_merged(client, db_session):
    """同公司同职称有两个邮件职位（一个有编号）：分不出是哪一个，不合并。"""
    from app.mail.match import create_email_job
    from tests.test_mail_match import _mail as _row

    row, _ = _row(db_session, "application_received")
    create_email_job(db_session, row, "Northwind Labs", "Role 1")
    row2, _ = _row(db_session, "application_received")
    create_email_job(db_session, row2, "Northwind Labs", "Role 1", "R-9")
    db_session.commit()
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd("Role 1", "Northwind Labs", "Remote - US")})
    assert r.json()["created"] is True


def test_resolve_bulk(client, synced, db_session):
    from app.models import EmailMessage

    msgs = [
        _mail(
            21, "Update", "Hello, unfortunately we will not move forward with your application at Northwind Labs.", 3
        ),
        _mail(22, "Next steps", "Hi! we would like to schedule an interview at Northwind Labs next week.", 2),
        _mail(23, "Weird", "BROKEN email body at Northwind Labs", 1),
    ]
    out = synced(msgs)
    assert len(out["needs_review"]) == 3
    # 拒信补上职称后才符合「批量新建」的条件：信里写明公司与职称、找不到对应职位
    row = db_session.get(EmailMessage, "m021")
    row.title = "QA Engineer"
    db_session.commit()
    review = {r["message"]["id"]: r for r in client.get("/api/email/syncs/latest").json()["needs_review"]}
    assert review["m021"]["bulk_create"] is True and review["m022"]["bulk_create"] is False

    ids = ["m021", "m022", "m023", "nope"]
    r = client.post("/api/email/messages/resolve-bulk", json={"action": "create", "ids": ids})
    assert r.status_code == 200 and r.json() == {"resolved": 1, "skipped": 3}
    assert client.get("/api/stats").json()["totals"]["rejected"] == 1
    r = client.post("/api/email/messages/resolve-bulk", json={"action": "ignore", "ids": ids})
    assert r.json() == {"resolved": 2, "skipped": 2}
    assert client.get("/api/email/syncs/latest").json()["needs_review"] == []


def _funnel(client):
    return {f["stage"]: f["count"] for f in client.get("/api/stats").json()["funnel"]}


def test_interview_stage_counts_jobs_that_ever_interviewed(client, synced):
    """面试过后被拒的职位仍然算进「面试」；面试信挂在已经被拒的职位上（只记证据）也算。"""
    seven = _existing_job(client, "Role 7")
    eight = _existing_job(client, "Role 8")
    assert client.put(f"/api/jobs/{eight['id']}/application", json={"status": "rejected"}).status_code == 200
    assert _funnel(client)["interviewing"] == 0
    synced(
        [
            _mail(31, "Interview", "Hi, we would like to schedule an interview for Role 7 at Northwind Labs.", 3),
            _mail(32, "Interview", "Hi, we would like to schedule an interview for Role 8 at Northwind Labs.", 2),
        ]
    )
    assert client.get(f"/api/jobs/{seven['id']}/application").json()["status"] == "interviewing"
    assert client.get(f"/api/jobs/{eight['id']}/application").json()["status"] == "rejected"  # 只记证据
    assert _funnel(client)["interviewing"] == 2

    assert client.put(f"/api/jobs/{seven['id']}/application", json={"status": "rejected"}).status_code == 200
    stats = client.get("/api/stats").json()
    assert {f["stage"]: f["count"] for f in stats["funnel"]}["interviewing"] == 2
    assert stats["totals"]["interviewing"] == 0  # 目前状态是面试中的
    assert sum(s["interviews"] for s in stats["sources"]) == 2  # 来源表的「面试」栏也是同一个算法
    drill = client.get("/api/stats/jobs", params={"dim": "stage", "value": "interviewing"}).json()
    assert {j["id"] for j in drill} == {seven["id"], eight["id"]}

    assert client.put(f"/api/jobs/{eight['id']}/application", json={"status": "dismissed"}).status_code == 200
    assert _funnel(client)["interviewing"] == 1  # 已删除的不算
