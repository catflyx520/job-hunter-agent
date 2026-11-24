"""Reach out：内推请求草稿（风格、三个版本、附言长度、跟进、真实性核对）。草稿不写进资料库。"""

import json

from app.outreach.drafts import default_style, note_limit
from app.schemas.profile import JobPreferences
from tests.samples import make_jd, make_pdf


def test_default_style():
    assert default_style("engineer") == "technical" and default_style("eng_manager") == "technical"
    assert default_style("recruiter") == "general" and default_style("other") == "general"


def test_note_limit():
    assert note_limit(JobPreferences()) == 200
    assert note_limit(JobPreferences(linkedin_premium=True)) == 300


def _setup(client, email=None, role_kind="engineer"):
    assert client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).status_code == 201
    job = client.post(
        "/api/jobs/ingest", json={"jd_text": make_jd("Backend Engineer", "Northwind Labs", "Remote - US")}
    )
    job = job.json()["job"]["id"]
    c = client.post(
        "/api/contacts",
        json={"full_name": "Ada Sample", "company_name": "Northwind Labs", "email": email, "role_kind": role_kind},
    ).json()
    return job, c["id"]


def _draft(text, ids=()):
    return {
        "text": text,
        "citations": [{"sentence": text, "evidence_ids": list(ids)}] if ids else [],
        "needs_confirmation": [],
    }


def _responder(client, note_texts):
    """OutreachDrafts 回传固定内容；连接附言依序取 note_texts（第一次生成、重写）。"""
    base = client.fake._responses
    notes = list(note_texts)
    calls = {"rewrite": 0}

    def respond(messages, json_mode):
        title = (json_mode or {}).get("title")
        if title == "OutreachDrafts":
            return json.dumps(
                {
                    "connect_note": _draft(notes.pop(0)),
                    "long_message": _draft("Hi Ada, I saw the Backend Engineer role on your team."),
                    "email_subject": "Referral for Backend Engineer",
                    "email": _draft("Hi Ada, I am applying for the Backend Engineer role."),
                }
            )
        if title == "Draft":
            calls["rewrite"] += 1
            return json.dumps(_draft(notes.pop(0)))
        return base(messages, json_mode)

    client.fake._responses = respond
    return calls


def _count_messages(client):
    from sqlalchemy import func, select

    from app.core.db import get_sessionmaker
    from app.models import OutreachMessage

    with get_sessionmaker()() as s:
        return s.scalar(select(func.count()).select_from(OutreachMessage))


def test_drafts_three_versions_no_db_write(client):
    job, cid = _setup(client, email="ada@example.com")
    _responder(client, ["Hi Ada, would you refer me for the Backend Engineer role?"])
    r = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["style"] == "technical" and out["language"] == "en"
    assert [v["channel"] for v in out["versions"]] == ["connect_note", "inmail", "email"]
    note, _, email = out["versions"]
    assert note["limit"] == 200 and note["over_limit"] is False and note["length"] == len(note["body"])
    assert email["subject"] == "Referral for Backend Engineer"
    assert out["material_meta"]["style"] == "technical" and out["material_meta"]["resume_id"]
    assert _count_messages(client) == 0


def test_drafts_without_email_skip_email_version(client):
    job, cid = _setup(client, role_kind="recruiter")
    _responder(client, ["Hi Ada"])
    out = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).json()
    assert out["style"] == "general"
    assert [v["channel"] for v in out["versions"]] == ["connect_note", "inmail"]


def test_connect_note_limit_retry(client):
    job, cid = _setup(client)
    calls = _responder(client, ["x" * 250, "y" * 180])
    note = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).json()["versions"][0]
    assert calls["rewrite"] == 1 and note["length"] == 180 and note["over_limit"] is False

    calls = _responder(client, ["x" * 250, "z" * 250])
    note = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).json()["versions"][0]
    assert note["over_limit"] is True and len(note["body"]) == 250  # 不截断

    prefs = client.get("/api/preferences").json()
    client.put("/api/preferences", json={**prefs["data"], "linkedin_premium": True})
    calls = _responder(client, ["x" * 250])
    note = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).json()["versions"][0]
    assert calls["rewrite"] == 0 and note["limit"] == 300 and note["over_limit"] is False


def test_follow_up_after_connect_note_uses_message_channel(client):
    job, cid = _setup(client, role_kind="recruiter")
    client.post(
        f"/api/contacts/{cid}/messages",
        json={"direction": "out", "channel": "connect_note", "body": "Hi Ada", "style": "technical", "job_id": job},
    )
    base = client.fake._responses
    seen = {}

    def respond(messages, json_mode):
        if (json_mode or {}).get("title") == "FollowUpDraft":
            seen["prompt"] = messages[-1].content
            return json.dumps({"message": _draft("Thanks for connecting, Ada!"), "subject": ""})
        return base(messages, json_mode)

    client.fake._responses = respond
    out = client.post("/api/outreach/drafts", json={"contact_id": cid, "follow_up": True}).json()
    assert [v["channel"] for v in out["versions"]] == ["linkedin_message"]
    assert out["style"] == "technical"  # 沿用原本那条
    assert "Hi Ada" in seen["prompt"]  # 依据包含之前的对话


def test_follow_up_needs_a_sent_message(client):
    job, cid = _setup(client)
    r = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job, "follow_up": True})
    assert r.status_code == 422


def test_drafts_flag_unverified_claims(client):
    job, cid = _setup(client)
    base = client.fake._responses

    def respond(messages, json_mode):
        if (json_mode or {}).get("title") == "OutreachDrafts":
            bad = {"text": "I led a team of 40 engineers.", "citations": [{"sentence": "I led a team of 40 engineers.",
                   "evidence_ids": ["not-real"]}], "needs_confirmation": []}  # fmt: skip
            return json.dumps({"connect_note": bad, "long_message": bad, "email_subject": "", "email": bad})
        return base(messages, json_mode)

    client.fake._responses = respond
    note = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).json()["versions"][0]
    items = " ".join(n["item"] for n in note["needs_confirmation"])
    assert "40" in items and note["citations"][0]["supported"] is False


def test_drafts_need_active_resume(client):
    job = client.post("/api/jobs/ingest", json={"jd_text": make_jd("Backend Engineer", "Northwind Labs", "Remote")})
    cid = client.post("/api/contacts", json={"full_name": "Ada", "company_name": "Northwind Labs"}).json()["id"]
    r = client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job.json()["job"]["id"]})
    assert r.status_code == 422 and "履历" in r.json()["detail"]


def test_drafts_prompt_asks_for_the_fit_case_from_jd_and_resume(client):
    """消息的重点是「为什么我适合这个职位」：模型拿到 JD 与履历证据，并被要求用具体事实对上 JD 的要求。"""
    job, cid = _setup(client)
    base = client.fake._responses
    seen = {}

    def respond(messages, json_mode):
        if (json_mode or {}).get("title") == "OutreachDrafts":
            seen["system"], seen["user"] = messages[0].content, messages[-1].content
            d = _draft("Hi Ada")
            return json.dumps({"connect_note": d, "long_message": d, "email_subject": "", "email": d})
        return base(messages, json_mode)

    client.fake._responses = respond
    assert client.post("/api/outreach/drafts", json={"contact_id": cid, "job_id": job}).status_code == 200
    assert "strong fit" in seen["system"] and "looking for" in seen["system"]
    jd, evidence = seen["user"].split("Resume evidence (cite by ID):")
    assert "Northwind Labs" in jd and evidence.strip() != "(none)"
    assert "strongest match" in seen["user"]  # 每个版本要写几条对应
    assert "Jordan Rivera" in seen["user"]  # 落款用履历上的姓名，不留占位符
