"""Reach out：联系人、消息、referred 状态规则、Hunter 查邮箱。"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.samples import make_jd

ADA = "https://www.linkedin.com/in/ada-sample"


def _job(client, company="Northwind Labs", title="Backend Engineer"):
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd(title, company, "Remote - US")})
    assert r.status_code == 201, r.text
    return r.json()["job"]


def _contact(client, **kw):
    body = {"full_name": "Ada Sample", "company_name": "Northwind Labs", **kw}
    r = client.post("/api/contacts", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _send(client, cid, **kw):
    body = {"direction": "out", "channel": "connect_note", "body": "Hi Ada, could you refer me?", **kw}
    r = client.post(f"/api/contacts/{cid}/messages", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_contact_dedupes_url_variants(client):
    _job(client)
    first = client.post(
        "/api/contacts", json={"full_name": "Ada Sample", "linkedin_url": ADA, "company_name": "Northwind Labs"}
    )
    assert first.status_code == 201 and first.json()["linkedin_url"] == ADA
    assert first.json()["company_name"] == "Northwind Labs"
    again = client.post(
        "/api/contacts", json={"full_name": "Ada S.", "linkedin_url": "https://uk.linkedin.com/in/Ada-Sample/?trk=a"}
    )
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


def test_create_contact_rejects_non_profile_url(client):
    r = client.post("/api/contacts", json={"full_name": "Ada", "linkedin_url": "https://www.linkedin.com/company/x"})
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("start", "end"),
    [(None, "referred"), ("saved", "referred"), ("dismissed", "referred"), ("applied", "applied"),
     ("interviewing", "interviewing"), ("referred", "referred")],
)  # fmt: skip
def test_mark_sent_sets_referred(client, start, end):
    job = _job(client)
    if start:
        assert client.put(f"/api/jobs/{job['id']}/application", json={"status": start}).status_code == 200
    c = _contact(client)
    out = _send(client, c["id"], job_id=job["id"], style="technical")
    assert out["application_status"] == end
    app = client.get(f"/api/jobs/{job['id']}/application").json()
    assert app["status"] == end
    if end == "referred" and start != "referred":
        assert "Ada Sample" in app["events"][-1]["note"] and app["applied_at"] is not None


def test_message_without_job_keeps_status(client):
    job = _job(client)
    c = _contact(client)
    assert _send(client, c["id"])["application_status"] is None
    assert client.get(f"/api/jobs/{job['id']}/application").json() is None


def test_incoming_message_never_changes_status(client):
    job = _job(client)
    client.put(f"/api/jobs/{job['id']}/application", json={"status": "saved"})
    c = _contact(client)
    _send(client, c["id"], direction="in", channel="linkedin_message", body="Sure!", job_id=job["id"])
    assert client.get(f"/api/jobs/{job['id']}/application").json()["status"] == "saved"


def test_blank_message_rejected(client):
    c = _contact(client)
    r = client.post(f"/api/contacts/{c['id']}/messages", json={"direction": "out", "channel": "email", "body": "   "})
    assert r.status_code == 422


def test_inbox_filters_and_order(client):
    now = datetime.now(UTC)
    a = _contact(client, full_name="A", linkedin_url="https://www.linkedin.com/in/a")
    b = _contact(client, full_name="B", linkedin_url="https://www.linkedin.com/in/b")
    c = _contact(client, full_name="C", linkedin_url="https://www.linkedin.com/in/c")
    _send(client, b["id"], sent_at=(now - timedelta(days=3)).isoformat())
    _send(
        client,
        b["id"],
        direction="in",
        channel="linkedin_message",
        body="ok",
        sent_at=(now - timedelta(days=2)).isoformat(),
    )
    _send(client, a["id"], sent_at=(now - timedelta(days=1)).isoformat())

    rows = client.get("/api/contacts").json()
    assert [r["full_name"] for r in rows] == ["A", "B", "C"]
    assert rows[1]["last_direction"] == "in" and rows[1]["message_count"] == 2 and rows[2]["last_message_at"] is None
    assert [r["full_name"] for r in client.get("/api/contacts?filter=waiting").json()] == ["A"]
    assert [r["full_name"] for r in client.get("/api/contacts?filter=replied").json()] == ["B"]
    assert c["company_id"] is not None
    by_company = client.get(f"/api/contacts?company_id={c['company_id']}").json()
    assert len(by_company) == 3


def test_contact_detail_lists_jobs_from_messages(client):
    j1 = _job(client)
    _job(client, title="Data Engineer")  # 同公司但没提过：不列
    c = _contact(client)
    _send(client, c["id"], job_id=j1["id"])
    d = client.get(f"/api/contacts/{c['id']}").json()
    assert [j["id"] for j in d["jobs"]] == [j1["id"]] and d["jobs"][0]["application_status"] == "referred"
    assert len(d["messages"]) == 1


def test_delete_last_sent_message_warns(client):
    job = _job(client)
    c = _contact(client)
    m1 = _send(client, c["id"], job_id=job["id"])
    m2 = _send(client, c["id"], job_id=job["id"], channel="linkedin_message", body="Following up")
    assert client.delete(f"/api/messages/{m2['id']}").json() == {"warning": None}
    w = client.delete(f"/api/messages/{m1['id']}").json()["warning"]
    assert w and "已请求内推" in w
    assert client.get(f"/api/jobs/{job['id']}/application").json()["status"] == "referred"


def test_patch_message_and_contact(client):
    c = _contact(client)
    m = _send(client, c["id"])
    r = client.patch(f"/api/messages/{m['id']}", json={"body": "Edited"})
    assert r.status_code == 200 and r.json()["body"] == "Edited"
    r = client.patch(f"/api/contacts/{c['id']}", json={"email": "ada@example.com", "role_kind": "engineer"})
    assert r.json()["email"] == "ada@example.com" and r.json()["email_source"] == "user"
    assert client.patch(f"/api/contacts/{c['id']}", json={"email": "not-an-email"}).status_code == 422
    assert client.delete(f"/api/contacts/{c['id']}").status_code == 204
    assert client.get(f"/api/contacts/{c['id']}").status_code == 404


class _Resp:
    status_code = 200

    def json(self):
        return {"data": {"email": "ada@example.com", "score": 88}}


def test_email_lookup_needs_domain(client, monkeypatch):
    job = _job(client)
    c = _contact(client)
    assert client.post(f"/api/contacts/{c['id']}/email-lookup", json={}).status_code == 422  # 还没启用 Hunter
    client.put("/api/outreach/hunter", json={"enabled": True, "api_key": "hunter-key-1"})
    r = client.post(f"/api/contacts/{c['id']}/email-lookup", json={})
    assert r.status_code == 422 and "公司网址" in r.json()["detail"]

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    r = client.post(f"/api/contacts/{c['id']}/email-lookup", json={"domain": "https://www.northwind.example/"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["found"] is True and out["contact"]["email"] == "ada@example.com"
    assert out["contact"]["email_source"] == "hunter" and out["contact"]["email_confidence"] == 88
    assert job["company"]["id"] == out["contact"]["company_id"]
    # 网域存回公司，下次不用再填
    assert client.post(f"/api/contacts/{c['id']}/email-lookup", json={}).status_code == 200


def test_mark_sent_on_dismissed_applied_job_restores_applied(client):
    job = _job(client)
    for s in ("applied", "dismissed"):
        client.put(f"/api/jobs/{job['id']}/application", json={"status": s})
    c = _contact(client)
    assert _send(client, c["id"], job_id=job["id"])["application_status"] == "applied"
    app = client.get(f"/api/jobs/{job['id']}/application").json()
    assert app["status"] == "applied" and app["previous_status"] is None
