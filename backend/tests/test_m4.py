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
    assert summary[nw]["application_status"] == "interviewing"
    assert summary[jobs["acme"]]["application_status"] is None


def test_dismiss_and_restore(client):
    _, jobs = _setup(client)
    acme = jobs["acme"]
    _put(client, acme, "applied")
    a = _put(client, acme, "dismissed")
    assert a["status"] == "dismissed" and a["previous_status"] == "applied"
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
