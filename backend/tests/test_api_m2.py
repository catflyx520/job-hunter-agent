"""M2 API 流程：贴 JD → 职位 → 排除 → 匹配评分 → 签证状态；cover letter / 问答（假 provider）。"""

import io

from PIL import Image

from app.llm.base import Capabilities
from tests.samples import SYNTHETIC_JD, make_pdf

PREFS = {
    "target_roles": ["Backend Engineer"],
    "locations": ["Los Angeles", "Remote"],
    "work_modes": ["hybrid", "remote"],
    "min_salary": 140000,
    "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False, "needs_sponsorship_future": True},
}


def _setup(client, chunks=True):
    rid = client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).json()["resume"]["id"]
    if chunks:
        parsed = client.get(f"/api/resumes/{rid}").json()["parsed"]
        client.put(f"/api/resumes/{rid}/parsed", json={"parsed": parsed, "confirm": True})
        assert client.post(f"/api/resumes/{rid}/chunks").json()["chunk_count"] > 0
    client.put("/api/preferences", json=PREFS)
    return rid


def _ingest(client, **extra):
    r = client.post(
        "/api/jobs/ingest", json={"jd_text": SYNTHETIC_JD, "url": "https://www.linkedin.com/jobs/view/42", **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_ingest_extracts_and_flags_exclusion(client):
    _setup(client)
    body = _ingest(client)
    job = body["job"]
    assert job["title"] == "Senior Backend Engineer"
    assert job["company"]["display_name"] == "Example Robotics, Inc."
    assert job["location_tier"] == 1 and job["work_mode"] == "hybrid"
    assert job["sponsorship_policy"] == "explicit_no"
    assert job["sponsorship_evidence"] == "We are unable to sponsor visas for this position."
    assert job["status"] == "unverified" and job["verification_source"] == "pasted"
    assert job["sources"] == [{"site_id": "linkedin", "url": "https://www.linkedin.com/jobs/view/42"}]
    assert job["excluded"] is True
    assert [r["code"] for r in job["exclusion"]["reasons"]] == ["explicit_no_sponsorship"]
    assert job["sponsor"]["status"] == "not_checked"  # 还没导入官方资料
    assert any("贴上的 JD" in n for n in body["notes"])

    # 同一个职位再贴一次 → 更新，不重复
    again = _ingest(client)
    assert again["created"] is False and again["job"]["id"] == job["id"]
    assert len(client.get("/api/jobs").json()) == 1


def test_match_scores_with_citations(client):
    _setup(client)
    job = _ingest(client)["job"]
    r = client.post(f"/api/jobs/{job['id']}/match")
    assert r.status_code == 200, r.text
    m = r.json()["match"]
    assert set(m["breakdown"]) == {"role", "tech", "experience", "location", "recency"}
    assert m["breakdown"]["location"]["score"] == 10
    assert m["score"] == sum(p["score"] for p in m["breakdown"].values())
    assert m["recommendation"] == "skip"  # 硬性排除优先于分数
    assert m["exclusion_reasons"] == ["explicit_no_sponsorship"]
    assert len(m["reasons"]) == 1  # 没有有效证据的理由被删掉
    assert m["reasons"][0]["chunk_ids"][0] in r.json()["evidence"]
    assert any("没有引用有效的履历证据" in g["text"] for g in m["gaps"])


def test_match_without_chunks_uses_parsed_resume(client):
    _setup(client, chunks=False)
    job = _ingest(client)["job"]
    detail = client.post(f"/api/jobs/{job['id']}/match").json()
    m = detail["match"]
    ref = m["reasons"][0]["chunk_ids"][0]
    assert ref.startswith("ref:")
    assert detail["evidence"][ref].startswith("Full-stack engineer")  # 显示履历原文，不是位置代号
    assert any("尚未建立检索切块" in g["text"] for g in m["gaps"])


def test_ingest_requires_input_and_resume(client):
    assert client.post("/api/jobs/ingest", json={}).status_code == 422
    job = _ingest(client)["job"]
    r = client.post(f"/api/jobs/{job['id']}/match")
    assert r.status_code == 409 and "履历" in r.json()["detail"]


def test_ingest_blocks_private_url(client):
    r = client.post("/api/jobs/ingest", json={"url": "http://127.0.0.1:8000/admin"})
    assert r.status_code == 422


def test_company_staffing_flag_changes_sponsor_status(client):
    job = _ingest(client)["job"]
    r = client.patch(
        f"/api/companies/{job['company']['id']}", json={"is_staffing_agency": True, "website": "acme.test"}
    )
    assert r.json()["status"] == "not_checked"  # 没资料时永远是「未查」


# ---------- materials ----------


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, "PNG")
    return buf.getvalue()


def test_cover_letter_with_truth_check(client):
    _setup(client)
    client.post("/api/facts", json={"key": "notice_period", "question": "Notice?", "value": "2 weeks", "confirm": True})
    client.post("/api/facts", json={"key": "desired_salary", "question": "Salary?", "value": "150k"})  # 未确认
    job = _ingest(client)["job"]
    r = client.post("/api/materials", data={"kind": "cover_letter", "job_id": job["id"]})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "done" and m["jd_source"] == "stored"
    assert "2M events" in m["output_text"]
    items = " ".join(n["item"] for n in m["needs_confirmation"])
    assert "40" in items  # 来源不明的数字
    assert "start date" in items  # 占位符
    assert any(c["supported"] is False for c in m["citations"])
    # 只有已确认的事实会给模型
    prompt = client.fake.calls[-1][0][-1].content
    assert "2 weeks" in prompt and "150k" not in prompt

    # 编辑另存，保留原文
    r = client.patch(f"/api/materials/{m['id']}", json={"edited_text": "My edited letter."})
    assert r.json()["edited_text"] == "My edited letter." and r.json()["output_text"] == m["output_text"]
    dl = client.get(f"/api/materials/{m['id']}/download")
    assert dl.text == "My edited letter." and "attachment" in dl.headers["content-disposition"]


def test_cover_letter_needs_jd(client):
    _setup(client)
    r = client.post("/api/materials", data={"kind": "cover_letter"})
    assert r.status_code == 422 and "JD" in r.json()["detail"]


def test_qa_with_screenshot_and_vision_check(client):
    _setup(client)
    r = client.post(
        "/api/materials",
        data={"kind": "qa", "jd_text": SYNTHETIC_JD},
        files=[("images", ("q.png", _png(), "image/png"))],
    )
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["images"][0]["mime"] == "image/png"
    assert client.get(f"/api/materials/{m['id']}/images/1").content == _png()
    assert client.fake.calls[-1][1]  # 图片有传给模型

    # 伪装成 PNG 的 SVG → 拒绝
    bad = client.post(
        "/api/materials",
        data={"kind": "qa", "question": "Why us?"},
        files=[("images", ("x.png", b"<svg/>", "image/png"))],
    )
    assert bad.status_code == 422

    # 模型不支援图片 → 清楚说明
    client.fake._capabilities = Capabilities(vision=False)
    r = client.post("/api/materials", data={"kind": "qa"}, files=[("images", ("q.png", _png(), "image/png"))])
    assert r.status_code == 422 and "不支援图片" in r.json()["detail"]


def test_question_bank_similar(client):
    _setup(client)
    client.post("/api/materials", data={"kind": "qa", "question": "Why are you a good fit for this role?"})
    found = client.get("/api/materials/similar", params={"q": "Why are you a good fit?"}).json()
    assert found and found[0]["question"].startswith("Why are you")
