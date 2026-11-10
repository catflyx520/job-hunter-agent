"""M4：投递追踪（状态、历史、还原）与统计（view、筛选、下钻）。"""

from tests.samples import SYNTHETIC_JD, make_jd, make_pdf

PREFS = {
    "target_roles": ["Backend Engineer"],
    "locations": ["Los Angeles", "Remote"],
    "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False, "needs_sponsorship_future": True},
}


def _setup(client):
    rid = client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).json()["resume"]["id"]
    client.put("/api/preferences", json=PREFS)
    jobs = {}
    for key, jd, url in (
        ("robotics", SYNTHETIC_JD, None),
        ("northwind", make_jd("Backend Engineer", "Northwind Labs", "Los Angeles, CA"), "https://www.linkedin.com/jobs/view/5550001"),
        ("acme", make_jd("Platform Engineer", "Acme Cloud", "Remote - US"), None),
    ):  # fmt: skip
        r = client.post("/api/jobs/ingest", json={"jd_text": jd, "url": url})
        assert r.status_code == 201, r.text
        jobs[key] = r.json()["job"]["id"]
    assert client.post(f"/api/jobs/{jobs['robotics']}/match").status_code == 200
    return rid, jobs


def _put(client, job_id, status, **extra):
    r = client.put(f"/api/jobs/{job_id}/application", json={"status": status, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_changes_are_recorded_and_applied_time_is_mark_time(client):
    rid, jobs = _setup(client)
    nw = jobs["northwind"]
    assert client.get(f"/api/jobs/{nw}/application").json() is None

    a = _put(client, nw, "saved")
    assert a["applied_at"] is None and [e["to_status"] for e in a["events"]] == ["saved"]
    a = _put(client, nw, "applied", note="用 LinkedIn 投递")
    assert a["applied_at"] is not None and a["resume_id"] == rid
    applied_at = a["applied_at"]
    a = _put(client, nw, "applied")  # 状态没变：不新增历史
    assert len(a["events"]) == 2
    a = _put(client, nw, "interviewing", notes="下周一电话面试")
    assert a["applied_at"] == applied_at  # 投递时间不会被改写
    assert [(e["from_status"], e["to_status"]) for e in a["events"]] == [
        (None, "saved"),
        ("saved", "applied"),
        ("applied", "interviewing"),
    ]
    assert a["events"][1]["note"] == "用 LinkedIn 投递" and a["notes"] == "下周一电话面试"

    summary = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert summary[nw]["application_status"] == "interviewing" and summary[nw]["applied_at"] is not None
    assert summary[jobs["acme"]]["applied_at"] is None
    assert summary[jobs["acme"]]["application_status"] is None


def test_dismiss_and_restore(client):
    _, jobs = _setup(client)
    acme = jobs["acme"]
    _put(client, acme, "applied")
    a = _put(client, acme, "dismissed")
    assert a["status"] == "dismissed" and a["previous_status"] == "applied"
    # 删除的职位留在资料库：列表标成 dismissed，统计算得到、也能下钻
    row = {j["id"]: j for j in client.get("/api/jobs").json()}[acme]
    assert row["application_status"] == "dismissed" and row["status_at"] >= row["applied_at"]  # 已删除按删除时间排序
    assert client.get("/api/stats").json()["totals"]["dismissed"] == 1
    drill = client.get("/api/stats/jobs", params={"dim": "application_status", "value": "dismissed"}).json()
    assert [j["id"] for j in drill] == [acme]
    r = client.post(f"/api/jobs/{acme}/application/restore")
    assert r.status_code == 200 and r.json()["status"] == "applied" and r.json()["previous_status"] is None
    assert client.post(f"/api/jobs/{acme}/application/restore").status_code == 409
    assert (
        client.put(
            f"/api/jobs/{acme}/application",
            json={"status": "applied", "cover_letter_id": "00000000-0000-0000-0000-000000000000"},
        ).status_code
        == 422
    )


def test_deleting_job_removes_its_application(client):
    _, jobs = _setup(client)
    _put(client, jobs["acme"], "saved")
    assert client.delete(f"/api/jobs/{jobs['acme']}").status_code == 204
    assert client.get("/api/applications").json() == []


def test_stats_totals_funnel_and_drill_down(client):
    _, jobs = _setup(client)
    _put(client, jobs["northwind"], "applied")
    _put(client, jobs["northwind"], "interviewing")
    _put(client, jobs["acme"], "applied")
    _put(client, jobs["robotics"], "saved")

    s = client.get("/api/stats").json()
    t = s["totals"]
    assert t["found"] == 3 and t["submitted"] == 2 and t["saved"] == 1 and t["interviewing"] == 1
    assert t["reply_rate"] == 0.5
    assert [(f["stage"], f["count"]) for f in s["funnel"]] == [
        ("found", 3),
        ("saved", 3),
        ("applied", 2),
        ("interviewing", 1),
        ("offer", 0),
    ]
    assert s["sponsorship_policy"] == {"unclear": 2, "explicit_no": 1}
    assert s["exclusions"][0]["code"] == "explicit_no_sponsorship"
    assert {x["site"] for x in s["sources"]} == {"linkedin", "(无来源链接)"}
    assert s["location_tier"]["1"] == 2  # Los Angeles 两个；Remote 一个
    assert s["backlog"]["saved_not_applied"] == 1
    day = s["trend"]["day"]
    assert len(day) == 1 and day[0]["applied"] == 2 and day[0]["interviewing"] == 1

    applied = client.get("/api/stats/jobs", params={"dim": "stage", "value": "applied"}).json()
    assert {j["id"] for j in applied} == {jobs["northwind"], jobs["acme"]}
    excluded = client.get("/api/stats/jobs", params={"dim": "exclusion", "value": "explicit_no_sponsorship"}).json()
    assert [j["id"] for j in excluded] == [jobs["robotics"]]
    assert client.get("/api/stats/jobs", params={"dim": "nope"}).status_code == 422

    # 筛选
    only_linkedin = client.get("/api/stats", params={"site": "linkedin"}).json()
    assert only_linkedin["totals"]["found"] == 1 and only_linkedin["totals"]["interviewing"] == 1
    assert client.get("/api/stats", params={"status": "offer"}).json()["totals"]["found"] == 0
    opts = client.get("/api/stats/options").json()
    assert {c["name"] for c in opts["companies"]} >= {"Northwind Labs", "Acme Cloud"}


def test_trend_fills_missing_days(client):
    from datetime import UTC, datetime, timedelta

    from app.core.db import get_sessionmaker
    from app.models import ApplicationEvent

    _, jobs = _setup(client)
    _put(client, jobs["acme"], "applied")
    with get_sessionmaker()() as db:
        ev = db.query(ApplicationEvent).one()
        ev.at = datetime.now(UTC) - timedelta(days=3)
        db.commit()
    _put(client, jobs["northwind"], "applied")
    day = client.get("/api/stats").json()["trend"]["day"]
    assert [d["applied"] for d in day] == [1, 0, 0, 1], day


def test_delete_resume_keeps_jobs_matches_and_applications(client):
    """被职位评分、投递记录引用的履历版本也能删除；那些记录保留，resume_id 变成空。"""
    rid, jobs = _setup(client)
    _put(client, jobs["robotics"], "applied")
    assert client.delete(f"/api/resumes/{rid}").status_code == 204
    assert client.get("/api/resumes").json() == []
    job = client.get(f"/api/jobs/{jobs['robotics']}").json()
    assert job["match"] is not None and job["match"]["resume_id"] is None
    app = client.get(f"/api/jobs/{jobs['robotics']}/application").json()
    assert app["status"] == "applied" and app["resume_id"] is None
    # 删除后可以再上传
    assert client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).status_code == 201


def test_blacklist_company_and_title(client):
    _, jobs = _setup(client)
    _put(client, jobs["northwind"], "applied")  # 已投递的不删
    r = client.post("/api/blacklist", json={"kind": "title", "value": "backend   engineer"})
    assert r.status_code == 200, r.text
    body = r.json()
    # 「Senior Backend Engineer」（robotics）移到已删除；「Backend Engineer」（northwind）已投递 → 保留
    assert body["dismissed"] == 1 and body["kept_submitted"] == 1
    assert body["blacklist"]["titles"] == ["backend engineer"]
    summary = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert summary[jobs["robotics"]]["application_status"] == "dismissed"
    assert summary[jobs["northwind"]]["application_status"] == "applied"
    assert summary[jobs["acme"]]["application_status"] is None and summary[jobs["acme"]]["excluded"] is False

    r = client.post("/api/blacklist", json={"kind": "company", "value": "ACME CLOUD, INC."})
    assert r.json()["dismissed"] == 1
    detail = client.get(f"/api/jobs/{jobs['acme']}").json()
    assert [x["code"] for x in detail["exclusion"]["reasons"]] == ["blacklisted_company"]  # 之后搜索也会排除
    prefs = client.get("/api/preferences").json()
    assert prefs["data"]["blacklist"] == {"companies": ["ACME CLOUD, INC."], "titles": ["backend engineer"]}
    # 同一项再加一次：不重复
    again = client.post("/api/blacklist", json={"kind": "company", "value": "acme cloud, inc."}).json()
    assert again["blacklist"]["companies"] == ["ACME CLOUD, INC."] and again["dismissed"] == 0
