"""API 测试（需要 Postgres；LLM 一律用假 provider）。"""

from tests.samples import make_pdf


def _upload(client, data=None, label="Full-stack 版"):
    return client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", data or make_pdf(), "application/pdf")},
        data={"label": label},
    )


# ---------- providers ----------


def test_provider_crud_never_returns_full_key(client):
    r = client.post(
        "/api/providers",
        json={"kind": "openai", "name": "我的 OpenAI", "api_key": "sk-secret-abcd", "default_model": "gpt-x"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key_last4"] == "abcd" and body["has_api_key"] is True
    assert "sk-secret" not in r.text
    assert body["capabilities"]["vision"] is True  # 套用 openai 预设

    listed = client.get("/api/providers")
    assert "sk-secret" not in listed.text

    pid = body["id"]
    r = client.patch(f"/api/providers/{pid}", json={"api_key": ""})
    assert r.json()["has_api_key"] is False
    assert client.delete(f"/api/providers/{pid}").status_code == 204


def test_provider_validation(client):
    r = client.post("/api/providers", json={"kind": "anthropic", "name": "a", "default_model": "m"})
    assert r.status_code == 422
    r = client.post(
        "/api/providers", json={"kind": "openai_compatible", "name": "a", "default_model": "m", "api_key": "k"}
    )
    assert r.status_code == 422


def test_task_routes_and_restrict_delete(client):
    cli = client.post("/api/providers", json={"kind": "claude_cli", "name": "CLI", "default_model": "default"}).json()
    assert cli["base_url"] is None and cli["has_api_key"] is False
    r = client.put("/api/task-routes/embedding", json={"provider_id": cli["id"], "model": "x"})
    assert r.status_code == 422  # CLI 不支援 embedding

    r = client.put("/api/task-routes/cover_letter", json={"provider_id": cli["id"], "model": "opus"})
    assert r.status_code == 200
    routes = {x["task"]: x for x in client.get("/api/task-routes").json()}
    assert routes["cover_letter"]["model"] == "opus" and routes["qa"]["provider_id"] is None

    assert client.delete(f"/api/providers/{cli['id']}").status_code == 409
    client.delete("/api/task-routes/cover_letter")
    assert client.delete(f"/api/providers/{cli['id']}").status_code == 204


def test_ollama_gets_default_url(client):
    r = client.post("/api/providers", json={"kind": "ollama", "name": "本地", "default_model": "llama3"})
    assert r.json()["base_url"] == "http://localhost:11434"


def test_cli_status_has_notice(client):
    body = client.get("/api/cli-status").json()
    assert {c["name"] for c in body["clis"]} == {"claude", "codex"}
    assert "自己的订阅额度" in body["notice"]


# ---------- resumes ----------


def test_upload_parse_confirm_chunk_review_flow(client):
    r = _upload(client)
    assert r.status_code == 201, r.text
    body = r.json()
    resume = body["resume"]
    assert body["parse_error"] is None
    assert body["unverified_items"] == []
    assert resume["is_active"] is True
    assert resume["parsed"]["basics"]["name"] == "Jordan Rivera"
    assert resume["parsed_confirmed_at"] is None
    rid = resume["id"]

    # 未确认前不能建立检索资料
    assert client.post(f"/api/resumes/{rid}/chunks").status_code == 409

    parsed = resume["parsed"]
    parsed["summary"] = "Full-stack engineer."
    r = client.put(f"/api/resumes/{rid}/parsed", json={"parsed": parsed, "confirm": True})
    assert r.json()["parsed_confirmed_at"] is not None

    r = client.post(f"/api/resumes/{rid}/chunks")
    assert r.json()["error"] is None and r.json()["chunk_count"] == 10

    r = client.post(f"/api/resumes/{rid}/reviews", json={"target_role": "Backend Engineer"})
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["content_score"] == 82
    assert review["keyword_score"] == 57
    assert 0 <= review["parse_score"] <= 100
    assert review["model"] == "fake:fake-model"
    assert len(client.get(f"/api/resumes/{rid}/reviews").json()) == 1


def test_duplicate_and_invalid_uploads(client):
    pdf = make_pdf()  # reportlab 每次输出带时间戳，必须用同一份 bytes
    assert _upload(client, pdf).status_code == 201
    assert _upload(client, pdf).status_code == 409
    r = client.post("/api/resumes", files={"file": ("x.pdf", b"<svg/>", "application/pdf")})
    assert r.status_code == 422


def test_only_one_active_resume(client):
    first = _upload(client).json()["resume"]
    second = _upload(client, make_pdf(["Another synthetic resume", "Experience", "Education", "Skills"] * 20)).json()
    assert second["resume"]["is_active"] is False
    client.post(f"/api/resumes/{second['resume']['id']}/activate")
    states = {r["id"]: r["is_active"] for r in client.get("/api/resumes").json()}
    assert states == {first["id"]: False, second["resume"]["id"]: True}


def test_review_uses_preferences_role_by_default(client):
    rid = _upload(client).json()["resume"]["id"]
    client.put("/api/preferences", json={"target_roles": ["AI Engineer"]})
    r = client.post(f"/api/resumes/{rid}/reviews", json={})
    assert r.json()["target_role"] == "AI Engineer"


def test_ats_explained_is_bilingual(client):
    body = client.get("/api/ats-explained").json()
    assert "检查清单" in body["zh"] and "checklist" in body["en"]


# ---------- preferences & facts ----------


def test_preferences_version_bumps_only_on_change(client):
    assert client.get("/api/preferences").json()["version"] == 0
    prefs = {"target_roles": ["Backend", " "], "locations": ["Los Angeles", "Remote (CA)"], "min_salary": 120000}
    r = client.put("/api/preferences", json=prefs).json()
    assert r["version"] == 1 and r["data"]["target_roles"] == ["Backend"]
    assert r["data"]["employment_types"] == ["full_time"]
    assert client.put("/api/preferences", json=prefs).json()["version"] == 1
    prefs["min_salary"] = 130000
    assert client.put("/api/preferences", json=prefs).json()["version"] == 2


def test_facts_confirmation_rules(client):
    templates = client.get("/api/facts/templates").json()
    assert any(t["key"] == "notice_period" for t in templates)

    r = client.post("/api/facts", json={"key": "notice_period", "question": "Notice?", "value": "", "confirm": True})
    assert r.status_code == 422  # 空白答案不能确认

    fact = client.post(
        "/api/facts", json={"key": "notice_period", "question": "Notice?", "value": "2 weeks", "confirm": True}
    ).json()
    assert fact["confirmed_at"] is not None
    assert all(t["key"] != "notice_period" for t in client.get("/api/facts/templates").json())

    # 改答案但没有再次确认 → 变回未确认
    fact = client.patch(f"/api/facts/{fact['id']}", json={"value": "3 weeks"}).json()
    assert fact["confirmed_at"] is None
    fact = client.patch(f"/api/facts/{fact['id']}", json={"confirm": True}).json()
    assert fact["confirmed_at"] is not None

    assert client.post("/api/facts", json={"key": "notice_period", "question": "x"}).status_code == 409
    assert client.post("/api/facts", json={"key": "Bad Key", "question": "x"}).status_code == 422
