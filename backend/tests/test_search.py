"""M3 自动搜索：网址规则、ATS 解析、搜索批次流程（假模型 + 假网页，不连网）。"""

from __future__ import annotations

import pytest

from app.core.fetch import FetchedPage, FetchError
from app.llm.cli_providers import ClaudeCliProvider, parse_codex_output
from app.schemas.profile import JobPreferences
from app.search import ats, sites
from app.search.web import FoundJob, collect
from tests.samples import GREENHOUSE_BOARD, PAGES, make_pdf

# ---------- 纯逻辑 ----------


@pytest.mark.parametrize(
    "site, url, job_id",
    [
        ("linkedin", "https://www.linkedin.com/jobs/view/backend-engineer-at-acme-4012345678", "4012345678"),
        ("linkedin", "https://www.linkedin.com/jobs/view/4012345678/?refId=x", "4012345678"),
        ("linkedin", "https://www.linkedin.com/company/acme", None),
        ("linkedin", "https://www.linkedin.com/jobs/search?keywords=python", None),
        ("indeed", "https://www.indeed.com/viewjob?jk=0123456789abcdef&from=serp", "0123456789abcdef"),
        ("indeed", "https://www.indeed.com/q-python-jobs.html", None),
        ("builtin", "https://www.builtinla.com/job/full-stack-engineer/1234567", "1234567"),
        ("builtin", "https://builtin.com/company/acme", None),
        ("yc", "https://www.ycombinator.com/companies/acme/jobs/AbC123x-full-stack-engineer", "AbC123x"),
        ("yc", "https://www.ycombinator.com/companies/acme", None),
        ("wellfound", "https://wellfound.com/jobs/1234567-software-engineer", "1234567"),
        ("dice", "https://www.dice.com/job-detail/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b", "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"),
        ("wttj", "https://www.welcometothejungle.com/en/companies/acme/jobs/software-engineer_ny", "software-engineer_ny"),
        ("wwr", "https://weworkremotely.com/remote-jobs/acme-full-stack-engineer", "acme-full-stack-engineer"),
        ("wwr", "https://weworkremotely.com/categories/remote-full-stack-programming-jobs", None),
    ],
)  # fmt: skip
def test_job_page_rules(site, url, job_id):
    assert sites.match_job_url(site, url) == job_id


def test_clean_url_strips_tracking_but_keeps_indeed_jk():
    assert (
        sites.clean_url("https://www.linkedin.com/jobs/view/123456789/?trk=abc&utm_source=x#top")
        == "https://linkedin.com/jobs/view/123456789"
    )
    assert sites.clean_url("https://www.indeed.com/viewjob?from=serp&jk=abcdef01&vjs=3") == (
        "https://indeed.com/viewjob?jk=abcdef01"
    )


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://job-boards.greenhouse.io/acme-co", ("greenhouse", "acme-co")),
        ("https://boards.greenhouse.io/embed/job_app?for=acme&token=1", ("greenhouse", "acme")),
        ("https://jobs.lever.co/acme/1b2c3d", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/Acme/abc", ("ashby", "Acme")),
        ("https://www.linkedin.com/jobs/view/1", None),
    ],
)
def test_ats_from_url(url, expected):
    assert sites.ats_from_url(url) == expected


def test_title_matching_uses_distinctive_role_words():
    prefs = JobPreferences(target_roles=["Full Stack Engineer", "Backend Engineer"])
    assert sites.title_matches("Software Engineer, Full-Stack", prefs)
    assert sites.title_matches("Senior Backend Developer", prefs)
    assert not sites.title_matches("Account Executive", prefs)
    assert not sites.title_matches("Frontend Engineer", prefs)


def test_collect_keeps_only_job_pages_and_dedupes():
    found = [
        FoundJob(url="https://www.linkedin.com/jobs/view/111111111?trk=a", title="A"),
        FoundJob(url="https://linkedin.com/jobs/view/111111111", title="A again"),
        FoundJob(url="https://www.linkedin.com/company/acme"),
        FoundJob(url="https://www.linkedin.com/jobs/view/222222222"),
    ]
    leads, dropped = collect("linkedin", found, limit=5)
    assert [lead.url for lead in leads] == [
        "https://linkedin.com/jobs/view/111111111",
        "https://linkedin.com/jobs/view/222222222",
    ]
    assert dropped == 1
    assert len(collect("linkedin", found, limit=1)[0]) == 1


def test_greenhouse_lever_ashby_parsing_and_filter():
    gh = ats.parse_greenhouse(GREENHOUSE_BOARD, "acmeco", "Acmeco")
    assert gh[0].url == "https://job-boards.greenhouse.io/acmeco/jobs/101"
    assert "Design Python APIs" in gh[0].jd_text and "<p>" not in gh[0].jd_text
    assert gh[0].posted_at.year == 2026 and gh[0].ats == ("greenhouse", "acmeco")

    lever = ats.parse_lever(
        [
            {
                "id": "abc",
                "text": "Backend Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/abc",
                "categories": {"location": "Los Angeles, CA", "commitment": "Full-time"},
                "createdAt": 1762000000000,
                "descriptionPlain": "Build things.",
                "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
                "salaryRange": {"min": 150000, "max": 180000, "currency": "USD", "interval": "per-year-salary"},
            }
        ],
        "acme",
        "Acme",
    )
    assert "Requirements" in lever[0].jd_text and "Python" in lever[0].jd_text and "150000" in lever[0].jd_text

    ashby = ats.parse_ashby(
        {
            "jobs": [
                {"id": "1", "title": "Backend Engineer", "location": "Remote", "isRemote": True,
                 "jobUrl": "https://jobs.ashbyhq.com/acme/1", "descriptionPlain": "Do work.", "isListed": True},
                {"id": "2", "title": "Hidden", "location": "Remote", "isListed": False},
            ]
        },
        "acme",
        "Acme",
    )  # fmt: skip
    assert [a.title for a in ashby] == ["Backend Engineer"]

    prefs = JobPreferences(target_roles=["Backend Engineer"], locations=["Los Angeles", "Remote"])
    picked = ats.filter_leads(gh + lever + ashby, prefs, limit=10)
    assert [p.title for p in picked] == ["Backend Engineer"] + ["Backend Engineer, Platform", "Backend Engineer"]
    assert picked[0].location == "Los Angeles, CA"  # 地点优先顺序第一级排最前


def test_claude_cli_search_mode_only_allows_websearch():
    p = ClaudeCliProvider("sonnet")
    normal = p.build_args("claude")
    search = p.build_args("claude", search=True)
    assert normal[normal.index("--tools") + 1] == ""
    assert search[search.index("--tools") + 1] == "WebSearch"
    assert search[search.index("--allowedTools") + 1] == "WebSearch"
    assert "--strict-mcp-config" in search


def test_codex_web_search_event_only_allowed_in_search_mode():
    out = (
        '{"type":"item.completed","item":{"type":"web_search","query":"x"}}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}\n'
    )
    with pytest.raises(Exception, match="工具"):
        parse_codex_output(out)
    assert parse_codex_output(out, allow_search=True)[0] == "{}"


# ---------- 搜索批次（需要数据库） ----------

PREFS = {
    "target_roles": ["Backend Engineer"],
    "locations": ["Los Angeles", "Remote"],
    "work_modes": ["onsite", "hybrid", "remote"],
    "work_authorization": {"authorized_in_us": True, "needs_sponsorship_now": False, "needs_sponsorship_future": True},
}


@pytest.fixture
def search_client(client, monkeypatch):
    import app.api.search as search_api
    import app.search.ats as ats_mod
    import app.search.process as process_mod

    client.fake._capabilities.web_search = True
    fetched: list[str] = []

    def fake_fetch(url):
        fetched.append(url)
        key = sites.clean_url(url)
        if key in PAGES:
            return FetchedPage(url=url, text=PAGES[key], title="", retrieved_at=__import__("datetime").datetime.now())
        raise FetchError("网站回应 999（需要登录或拒绝自动读取）", blocked=True)

    monkeypatch.setattr(process_mod, "fetch_page", fake_fetch)
    monkeypatch.setattr(ats_mod, "fetch_json", lambda url: GREENHOUSE_BOARD)
    monkeypatch.setattr(search_api.runner, "spawn", lambda target, run_id: target(run_id))  # 同步执行
    client.fetched = fetched

    rid = client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).json()["resume"]["id"]
    parsed = client.get(f"/api/resumes/{rid}").json()["parsed"]
    client.put(f"/api/resumes/{rid}/parsed", json={"parsed": parsed, "confirm": True})
    client.put("/api/preferences", json=PREFS)
    for sid in ("linkedin", "indeed", "greenhouse"):
        assert client.patch(f"/api/job-sites/{sid}", json={"enabled": True}).status_code == 200
    r = client.post("/api/ats-boards", json={"url": "https://job-boards.greenhouse.io/acmeco"})
    assert r.status_code == 201 and r.json()["company"] == "Acmeco"
    return client


def test_search_run_end_to_end(search_client):
    c = search_client
    assert c.get("/api/search/source").json()["ready"] is True
    r = c.post("/api/search-runs", json={})
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    assert run_id.endswith("-A")

    run = c.get(f"/api/search-runs/{run_id}").json()
    assert run["status"] == "completed", run["error"]
    by_site = {s["site_id"]: s for s in run["sites"]}
    assert by_site["linkedin"]["status"] == "partial"  # 一个读到、一个被登录页挡住
    assert by_site["linkedin"]["found_count"] == 2 and by_site["linkedin"]["kept_count"] == 1
    assert "不是该网站的职位页" in by_site["linkedin"]["message"]
    assert "读不到" in by_site["linkedin"]["message"]
    assert by_site["indeed"]["status"] == "ok" and by_site["indeed"]["kept_count"] == 0
    assert by_site["greenhouse"]["found_count"] == 1 and by_site["greenhouse"]["kept_count"] == 1

    jobs = run["jobs"]
    assert [j["outcome"] for j in jobs] == ["kept", "kept", "excluded"]
    kept_titles = {j["title"] for j in jobs if j["outcome"] == "kept"}
    assert kept_titles == {"Backend Engineer", "Backend Engineer, Platform"}
    assert jobs[0]["location_tier"] == 1  # Los Angeles 排在 Remote 前面
    assert all(j["score"] is not None for j in jobs if j["outcome"] == "kept")
    excluded = jobs[2]
    assert excluded["exclusion_reasons"][0]["code"] == "explicit_no_sponsorship"
    assert excluded["score"] is None  # 被排除的不花模型额度评分
    assert run["counts"] == {"kept": 2, "excluded": 1}

    gh = next(j for j in jobs if j["title"] == "Backend Engineer, Platform")
    detail = c.get(f"/api/jobs/{gh['id']}").json()
    assert detail["verification_source"] == "ats_api" and detail["company"]["display_name"] == "Acmeco"


def test_second_run_marks_duplicates_and_keeps_first_batch(search_client):
    c = search_client
    first = c.post("/api/search-runs", json={}).json()["id"]
    before = c.get(f"/api/search-runs/{first}").json()
    c.fetched.clear()

    second = c.post("/api/search-runs", json={}).json()["id"]
    assert second.endswith("-B")
    run = c.get(f"/api/search-runs/{second}").json()
    assert {j["outcome"] for j in run["jobs"]} == {"duplicate"}
    assert len(run["jobs"]) == 3
    # 已知网址不再读取；只有之前被挡住的那一页会再试一次
    assert c.fetched == ["https://linkedin.com/jobs/view/2222222222"]

    after = c.get(f"/api/search-runs/{first}").json()
    assert [(j["id"], j["outcome"]) for j in after["jobs"]] == [(j["id"], j["outcome"]) for j in before["jobs"]]
    assert [r["id"] for r in c.get("/api/search-runs").json()] == [second, first]


def test_search_without_web_search_capability_skips_sites(search_client):
    c = search_client
    c.fake._capabilities.web_search = False
    src = c.get("/api/search/source").json()
    assert src["ready"] is False and "没有网页搜索能力" in src["label"]
    run = c.get(f"/api/search-runs/{c.post('/api/search-runs', json={}).json()['id']}").json()
    by_site = {s["site_id"]: s for s in run["sites"]}
    assert by_site["linkedin"]["status"] == "skipped" and "Tavily" in by_site["linkedin"]["message"]
    assert by_site["greenhouse"]["kept_count"] == 1  # ATS API 不需要网页搜索，照常运作


def test_run_requires_roles_and_sites(client):
    rid = client.post("/api/resumes", files={"file": ("r.pdf", make_pdf(), "application/pdf")}).json()["resume"]["id"]
    assert rid
    r = client.post("/api/search-runs", json={})
    assert r.status_code == 422 and "目标职位" in r.json()["detail"]
    client.put("/api/preferences", json=PREFS)
    r = client.post("/api/search-runs", json={})
    assert r.status_code == 422 and "勾选" in r.json()["detail"]


def test_site_settings_and_integration(client):
    sites_list = client.get("/api/job-sites").json()
    assert "manual" not in {s["id"] for s in sites_list}
    assert client.patch("/api/job-sites/handshake", json={"enabled": True}).status_code == 422
    r = client.patch("/api/job-sites/linkedin", json={"enabled": True, "max_results": 5})
    assert r.json()["enabled"] is True and r.json()["max_results"] == 5

    assert client.put("/api/search/integration", json={"kind": "tavily"}).status_code == 422
    out = client.put("/api/search/integration", json={"kind": "tavily", "api_key": "tvly-secret-1234"}).json()
    assert out["ready"] is True and out["label"] == "Tavily"
    assert out["integration"] == {"kind": "tavily", "base_url": None, "key_last4": "1234"}
    assert "secret" not in str(client.get("/api/search/source").json())

    out = client.put("/api/search/integration", json={"kind": "searxng", "base_url": "http://localhost:8888/"}).json()
    assert out["label"] == "SearXNG" and out["integration"]["base_url"] == "http://localhost:8888"
    out = client.put("/api/search/integration", json={"kind": "none"}).json()
    assert out["integration"] is None


def test_interrupted_runs_are_marked_failed(search_client):
    from app.core.db import get_sessionmaker
    from app.models import SearchRun
    from app.search.runner import recover_interrupted

    c = search_client
    run_id = c.post("/api/search-runs", json={}).json()["id"]
    with get_sessionmaker()() as db:
        db.get(SearchRun, run_id).status = "running"
        db.commit()
    recover_interrupted()
    run = c.get(f"/api/search-runs/{run_id}").json()
    assert run["status"] == "failed" and "重启" in run["error"]


@pytest.mark.parametrize(
    "title, body, blocked",
    [
        (
            "Backend Engineer at Acme | LinkedIn",
            "Skip to main content\nSign in\nJoin now\n" + "Build APIs. " * 300,
            False,
        ),
        ("Sign In | LinkedIn", "Sign in\nEmail\nPassword\n" + "x " * 200, True),
        ("Acme", "Just a moment...\nChecking your browser\n" + "x " * 150, True),
        ("Acme careers", "Log in to continue\n" + "y " * 200, True),
    ],
)
def test_block_page_detection_ignores_nav_sign_in(monkeypatch, title, body, blocked):
    from app.core import fetch

    html = (
        f"<html><head><title>{title}</title></head><body>"
        + "".join(f"<p>{line}</p>" for line in body.split("\n"))
        + "</body></html>"
    )
    monkeypatch.setattr(fetch, "_get", lambda url, accept, limit: (url, "text/html; charset=utf-8", html.encode()))
    if blocked:
        with pytest.raises(FetchError) as exc:
            fetch.fetch_page("https://example.com/job/1")
        assert exc.value.blocked
    else:
        assert "Build APIs" in fetch.fetch_page("https://example.com/job/1").text


@pytest.mark.parametrize(
    "text, closed",
    [
        ("Senior Engineer\nSorry, this job was removed at 06:40 p.m. (UTC) on Monday", True),
        ("Backend Engineer\nThis position has been filled.", True),
        ("Backend Engineer\nWe are no longer accepting applications for this role.", True),
        ("Backend Engineer\nWe are hiring! Apply now.", False),
    ],
)
def test_closed_posting_detection(text, closed):
    from app.jobs.exclusion import closed_posting

    assert bool(closed_posting(text)) is closed


def test_removed_job_page_is_excluded_as_expired(search_client, monkeypatch):
    PAGES["https://linkedin.com/jobs/view/backend-engineer-at-northwind-1111111111"] = (
        "Backend Engineer\nCompany: Northwind Labs\nLocation: Los Angeles, CA\n\n"
        "Sorry, this job was removed on Monday.\n" + "Old description text. " * 30
    )
    try:
        c = search_client
        run = c.get(f"/api/search-runs/{c.post('/api/search-runs', json={}).json()['id']}").json()
        northwind = next(j for j in run["jobs"] if j["company"]["display_name"] == "Northwind Labs")
        assert northwind["outcome"] == "excluded" and northwind["status"] == "expired"
        assert [r["code"] for r in northwind["exclusion_reasons"]] == ["expired"]
    finally:
        from tests.samples import make_jd

        PAGES["https://linkedin.com/jobs/view/backend-engineer-at-northwind-1111111111"] = make_jd(
            "Backend Engineer", "Northwind Labs", "Los Angeles, CA"
        )


# ---------- 目标可投职位数 ----------


def _graph_process(monkeypatch, outcomes, first, more=(), target=2, cap=100):
    """不碰数据库地跑 process 节点：outcomes 是网址 → 结果；more 是每一轮补搜找到的网址。"""
    import app.graphs.search as g

    processed, excludes = [], []
    rounds = iter(more)

    def fake_process(run_id, lead, prefs, sponsor):
        processed.append(lead.url)
        return g.LeadResult(lead.site_id, lead.url, outcomes[lead.url], job_id=lead.url)

    def fake_discover(site, prefs, exclude=()):
        excludes.append(set(exclude))
        urls = next(rounds, [])
        return g.SiteReport(site["id"], "ok", [g.Lead(site["id"], u) for u in urls])

    monkeypatch.setattr(g, "process_lead", fake_process)
    monkeypatch.setattr(g, "discover_site", fake_discover)
    out = g.process(
        {
            "run_id": "t",
            "params": {
                "sites": [{"id": "linkedin", "name": "LinkedIn", "access_method": "web_search", "max_results": 20}],
                "preferences": PREFS,
                "total_limit": cap,
                "target_jobs": target,
            },
            "reports": [g.SiteReport("linkedin", "ok", [g.Lead("linkedin", u) for u in first])],
        }
    )
    return processed, excludes, out


def test_excluded_jobs_do_not_count_toward_target(monkeypatch):
    outcomes = {"https://a/1": "excluded", "https://a/2": "kept", "https://a/3": "excluded", "https://a/4": "kept", "https://a/5": "kept"}  # fmt: skip
    processed, excludes, out = _graph_process(monkeypatch, outcomes, list(outcomes))
    assert processed == ["https://a/1", "https://a/2", "https://a/3", "https://a/4"]  # 凑到 2 个就停
    assert [r.outcome for r in out["results"]].count("kept") == 2
    assert [r.url for r in out["results"] if r.outcome == "not_needed"] == ["https://a/5"]
    assert excludes == []  # 够了就不再搜


def test_searches_again_when_leads_run_out(monkeypatch):
    outcomes = {"https://a/1": "excluded", "https://a/2": "kept", "https://a/3": "kept"}
    processed, excludes, out = _graph_process(
        monkeypatch, outcomes, ["https://a/1", "https://a/2"], more=[["https://a/3"]]
    )
    assert processed == ["https://a/1", "https://a/2", "https://a/3"]
    assert excludes == [{"https://a/1", "https://a/2"}]  # 补搜时避开看过的
    assert [len(r.leads) for r in out["reports"]] == [1]


def test_stops_when_search_finds_nothing_new_or_hits_cap(monkeypatch):
    outcomes = {f"https://a/{i}": "excluded" for i in range(5)}
    processed, excludes, _ = _graph_process(monkeypatch, outcomes, ["https://a/0"], more=[["https://a/0"]])
    assert processed == ["https://a/0"] and len(excludes) == 1  # 没有新线索就结束，不会空转

    processed, _, out = _graph_process(monkeypatch, outcomes, list(outcomes), cap=3)
    assert len(processed) == 3  # 安全上限
    assert [r.outcome for r in out["results"]].count("over_limit") == 2


def test_extra_rounds_are_limited(monkeypatch):
    outcomes = {f"https://a/{i}": "excluded" for i in range(9)}
    more = [[f"https://a/{i}"] for i in range(1, 9)]
    processed, excludes, _ = _graph_process(monkeypatch, outcomes, ["https://a/0"], more=more)
    assert len(excludes) == 2 and len(processed) == 3


def test_interleave_takes_turns_between_sites():
    import app.graphs.search as g

    reports = [
        g.SiteReport("a", "ok", [g.Lead("a", "https://a/1"), g.Lead("a", "https://a/2")]),
        g.SiteReport("b", "ok", [g.Lead("b", "https://b/1"), g.Lead("b", "https://a/1")]),
    ]
    assert [x.url for x in g.interleave(reports, set())] == ["https://a/1", "https://b/1", "https://a/2"]


def test_merge_reports_keeps_one_row_per_site():
    import app.graphs.search as g

    merged = g.merge_reports(
        [g.SiteReport("a", "ok", [g.Lead("a", "u1")], "first"), g.SiteReport("a", "ok", [g.Lead("a", "u2")], "more")]
    )
    assert len(merged) == 1 and len(merged[0].leads) == 2 and merged[0].message == "first"


def test_target_limits_kept_jobs_end_to_end(search_client):
    c = search_client
    c.put("/api/preferences", json={**PREFS, "search": {"target_jobs": 1}})
    run_id = c.post("/api/search-runs", json={}).json()["id"]
    run = c.get(f"/api/search-runs/{run_id}").json()
    assert run["status"] == "completed", run["error"]
    assert run["counts"]["kept"] == 1 and run["target_jobs"] == 1


def test_search_workers_use_the_request_language(search_client):
    c = search_client
    c.fake.calls.clear()
    c.post("/api/search-runs", json={}, headers={"X-UI-Lang": "zh"})  # 预设是英文，用中文才验得出来
    prompts = [
        m.content for msgs, _, _ in c.fake.calls for m in msgs if m.role == "system" and "fits a job" in m.content
    ]
    assert prompts and all("in Simplified Chinese" in p for p in prompts)
