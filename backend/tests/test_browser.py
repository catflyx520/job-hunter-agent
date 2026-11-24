"""登录浏览器搜索（LinkedIn）。一律用假的浏览器，不开真实浏览器。"""

from __future__ import annotations

import pytest

from app.schemas.profile import JobPreferences
from app.search import browser as b
from app.search import linkedin as li
from app.search import sites


def test_site_can_be_stored_as_browser_and_integration_kind_exists(client):
    from app.core.db import get_sessionmaker
    from app.models import Integration, JobSite

    with get_sessionmaker()() as db:
        db.get(JobSite, "linkedin").access_method = "browser"
        db.add(Integration(kind="browser", config={}, enabled=True))
        db.commit()  # 两个 check constraint 都要放行
        assert db.get(JobSite, "linkedin").access_method == "browser"


@pytest.fixture(autouse=True)
def forget_login_state():
    b.logged_in.clear()  # 登录状态只放记忆体：每个测试从「还没检查」开始


# ---------- 浏览器介面与验证页等待 ----------


def page(url="https://www.linkedin.com/jobs/view/1/", title="A job | LinkedIn", text="x"):
    return b.BrowserPage(url=url, title=title, text=text, links=[])


@pytest.mark.parametrize(
    ("p", "blocked"),
    [
        (page("https://www.linkedin.com/login?session_redirect=x"), True),
        (page("https://www.linkedin.com/checkpoint/challenge/abc"), True),
        (page("https://www.linkedin.com/authwall?trk=x"), True),
        (page("https://www.linkedin.com/uas/login"), True),
        (page(title="Just a moment..."), True),
        (page(title="Security Verification | LinkedIn"), True),
        (page("https://www.linkedin.com/jobs/view/1/"), False),
        (page("https://www.linkedin.com/jobs/search-results/?keywords=login"), False),  # 关键字里有 login 不算
    ],
)
def test_is_blocked(p, blocked):
    assert b.is_blocked(p) is blocked


class FakeBrowser:
    """pages：网址 → BrowserPage；unblock_after：current() 被叫几次后，登录页 / 验证页消失。"""

    def __init__(self, pages, unblock_after=None):
        self.pages, self.unblock_after, self.opened, self.polls = pages, unblock_after, [], 0
        self._url = ""

    def _page(self):
        if self.unblock_after is not None and self.polls >= self.unblock_after:
            return page(self._url)
        return self.pages[self._url]

    def open(self, url, *, scroll=False):
        self.opened.append(url)
        self._url = url
        return self._page()

    def current(self):
        self.polls += 1
        return self._page()

    def close(self): ...


@pytest.fixture
def fake_browser(monkeypatch):
    def use(pages, unblock_after=None):
        fb = FakeBrowser(pages, unblock_after)
        monkeypatch.setattr(b, "get_browser", lambda: fb)
        monkeypatch.setattr(b.time, "sleep", lambda s: None)
        return fb

    return use


LOGIN = page("https://www.linkedin.com/login")


def test_open_checked_waits_for_the_user_then_opens_the_page_again(fake_browser):
    fb = fake_browser({"https://x/1": LOGIN}, unblock_after=2)
    assert b.open_checked(None, "https://x/1").url == "https://x/1"
    assert fb.polls == 2 and b.logged_in["linkedin"] is True
    assert fb.opened == ["https://x/1", "https://x/1"]  # 登录完会被带到首页，所以要重新打开原来的网址


def test_open_checked_gives_up_after_the_wait_limit(fake_browser):
    fb = fake_browser({"https://x/1": LOGIN})
    with pytest.raises(b.BrowserBlocked):
        b.open_checked(None, "https://x/1")
    assert fb.polls == b.WAIT_MAX // b.WAIT_POLL and b.logged_in["linkedin"] is False


def test_after_giving_up_once_the_same_search_does_not_wait_again(fake_browser):
    """一次搜索里有几十个职位页：第一次等到逾时后，后面的不能每个再等 3 分钟。"""
    fb = fake_browser({"https://x/1": LOGIN, "https://x/2": LOGIN, "https://x/3": page("https://x/3")})
    with pytest.raises(b.BrowserBlocked):
        b.open_checked("r3", "https://x/1")
    polls = fb.polls
    with pytest.raises(b.BrowserBlocked):
        b.open_checked("r3", "https://x/2")
    assert fb.polls == polls and fb.opened[-1] == "https://x/2"  # 还是会开一次：用户可能已经登录了
    assert b.open_checked("r3", "https://x/3").url == "https://x/3"  # 没被挡就照常读
    with pytest.raises(b.BrowserBlocked):
        b.open_checked("r4", "https://x/1")  # 另一次搜索重新等
    assert fb.polls == polls * 2


def test_open_checked_stops_waiting_when_the_search_is_cancelled(fake_browser):
    from app.search import progress

    fb = fake_browser({"https://x/1": LOGIN})
    progress.begin("r1", ["linkedin"])
    progress.cancel("r1")
    try:
        with pytest.raises(b.BrowserBlocked):
            b.open_checked("r1", "https://x/1")
        assert fb.polls <= 1
    finally:
        progress.finish("r1")


def test_wait_note_is_shown_and_cleared(fake_browser):
    from app.search import progress

    seen = []
    fb = fake_browser({"https://x/1": LOGIN}, unblock_after=2)
    progress.begin("r2", ["linkedin"])
    real = fb.current
    fb.current = lambda: (seen.append(progress.snapshot("r2")["note"]), real())[1]
    try:
        b.open_checked("r2", "https://x/1")
        assert seen and all(seen) and progress.snapshot("r2")["note"] is None
    finally:
        progress.finish("r2")


# ---------- 在 LinkedIn 找职位 ----------

CARD = (
    "Full Stack Software Engineer (Verified job)\nFull Stack Software Engineer \n\nCorgi\n\n"
    "Los Angeles, CA (On-site)\n\nYou’d be a top applicant\n\nPosted 2 days ago\n2 days ago\n\n · \n\nEasy Apply"
)
CARD_PM = "Product Manager\nProduct Manager\n\nAcme\n\nLos Angeles, CA (On-site)\n\nPosted 5 minutes ago\n5 minutes ago"
CARD_NY = "Backend Engineer\nBackend Engineer\n\nFarco\n\nNew York, NY (On-site)\n\nPosted 1 day ago"
PREFS_LA = JobPreferences.model_validate(
    {"target_roles": ["Full Stack Engineer", "Backend Engineer"], "locations": ["Los Angeles", "Remote"]}
)
SITE = {"id": "linkedin", "name": "LinkedIn", "access_method": "browser", "max_results": 20}


def test_search_urls_put_role_and_location_in_keywords():
    urls = li.search_urls(PREFS_LA)
    assert urls[0] == (
        "https://www.linkedin.com/jobs/search-results/?keywords=Full%20Stack%20Engineer%20Los%20Angeles&f_TPR=r604800"
    )
    assert len(urls) == 4  # 2 个职位 × 2 个地点
    assert "Backend%20Engineer%20Los%20Angeles" in urls[1]  # 先把每个职位在第一优先的地点搜过
    many = JobPreferences.model_validate({"target_roles": ["A", "B", "C", "D"], "locations": ["X", "Y"]})
    assert len(li.search_urls(many)) == li.MAX_SEARCHES


def test_parse_card():
    lead = li.parse_card("4492516814", CARD)
    assert (lead.site_id, lead.site_job_id, lead.via_browser) == ("linkedin", "4492516814", True)
    assert lead.url == "https://www.linkedin.com/jobs/view/4492516814/"
    assert (lead.title, lead.company, lead.location) == (
        "Full Stack Software Engineer",
        "Corgi",
        "Los Angeles, CA (On-site)",
    )
    assert lead.posted_text == "2 days ago"
    # 目前选中的那张卡前面多了 "Selected, "；有的卡职称只出现一次
    selected = li.parse_card(
        "1", "Selected, Full-Stack Developer (Verified job)\nFull-Stack Developer \n\nAkima\n\nRichland, WA"
    )
    assert (selected.title, selected.company, selected.location) == ("Full-Stack Developer", "Akima", "Richland, WA")
    once = li.parse_card("2", "Software Engineer II \n\nMetronet\n\nWisconsin, United States\n\nPosted 2 hours ago")
    assert (once.title, once.company, once.posted_text) == ("Software Engineer II", "Metronet", "2 hours ago")
    assert li.parse_card("3", "").title == ""  # 空的卡不出错，之后会被职称过滤掉


def results(*cards):
    return b.BrowserPage(
        url="https://www.linkedin.com/jobs/search-results/",
        title="Jobs | LinkedIn",
        text="x",
        links=[],
        cards=list(cards),
    )


def test_browser_leads_keep_matching_titles_and_locations(fake_browser):
    urls = li.search_urls(PREFS_LA)
    fb = fake_browser({u: results(("1000001", CARD), ("1000002", CARD_PM), ("1000003", CARD_NY)) for u in urls})
    report = li.browser_leads(None, SITE, PREFS_LA)
    # 同一张卡在几次搜索里出现只算一次；职称或地点不符的不留
    assert report.status == "ok" and [x.site_job_id for x in report.leads] == ["1000001"]
    assert fb.opened == urls and "3 张职位卡" in report.message
    fb.opened.clear()
    again = li.browser_leads(None, SITE, PREFS_LA, exclude={sites.clean_url(report.leads[0].url)})
    assert again.status == "ok" and again.leads == [] and fb.opened == []  # 补搜不再搜 LinkedIn


def test_no_cards_at_all_is_reported_as_a_layout_change(fake_browser):
    fake_browser({u: results() for u in li.search_urls(PREFS_LA)})
    report = li.browser_leads(None, SITE, PREFS_LA)
    assert report.status == "failed" and "页面结构可能改了" in report.message


def test_login_page_that_is_never_cleared_blocks_the_site(fake_browser):
    fb = fake_browser({u: LOGIN for u in li.search_urls(PREFS_LA)})
    report = li.browser_leads(None, SITE, PREFS_LA)
    assert report.status == "blocked" and "登录" in report.message
    assert len(fb.opened) == 1  # 第一页就挡住，不再往下开


def test_blocked_after_some_results_keeps_what_was_found(fake_browser):
    urls = li.search_urls(PREFS_LA)
    fb = fake_browser({urls[0]: results(("1000001", CARD)), **{u: LOGIN for u in urls[1:]}})
    report = li.browser_leads(None, SITE, PREFS_LA)
    assert report.status == "partial" and len(report.leads) == 1 and len(fb.opened) == 2


def test_window_closed_mid_search_fails_the_site(fake_browser, monkeypatch):
    fake_browser({})

    def closed(*args, **kwargs):
        raise b.BrowserError("窗口被关掉了")

    monkeypatch.setattr(li, "open_checked", closed)
    report = li.browser_leads(None, SITE, PREFS_LA)
    assert report.status == "failed" and "窗口被关掉了" in report.message


# ---------- 接进搜索流程 ----------

from tests.test_search import GREENHOUSE, LINKEDIN, PREFS, _graph_process, search_client  # noqa: E402, F401

JOB_URL = "https://www.linkedin.com/jobs/view/1111111111/"
JOB_TEXT_KEY = "https://linkedin.com/jobs/view/backend-engineer-at-northwind-1111111111"


@pytest.fixture
def linkedin_browser(search_client, fake_browser):  # noqa: F811
    """LinkedIn 改用登录浏览器；只开 LinkedIn 一个网站。"""
    from app.core.db import get_sessionmaker
    from app.models import Integration, JobSite

    with get_sessionmaker()() as db:
        db.get(JobSite, "linkedin").access_method = "browser"
        for sid in ("indeed", "greenhouse"):
            db.get(JobSite, sid).enabled = False
        db.add(Integration(kind="browser", config={}, enabled=True))
        db.commit()
    card = "Backend Engineer\nBackend Engineer\n\nNorthwind\n\nLos Angeles, CA (On-site)\n\nPosted 1 day ago"

    def setup(job_page):
        pages = {u: results(("1111111111", card)) for u in li.search_urls(JobPreferences.model_validate(PREFS))}
        pages[JOB_URL] = job_page
        return fake_browser(pages)

    return search_client, setup


def run(c):
    return c.get(f"/api/search-runs/{c.post('/api/search-runs', json={}).json()['id']}").json()


def test_linkedin_job_is_read_through_the_browser(linkedin_browser):
    from tests.samples import PAGES

    c, setup = linkedin_browser
    fb = setup(b.BrowserPage(url=JOB_URL, title="Backend Engineer | LinkedIn", text=PAGES[JOB_TEXT_KEY], links=[]))
    out = run(c)
    assert out["status"] == "completed", out["error"]
    site = out["sites"][0]
    assert (site["site_id"], site["status"], site["kept_count"]) == ("linkedin", "ok", 1), site["message"]
    assert fb.opened[-1] == JOB_URL and c.fetched == []  # 不走一般的网页读取
    # 整页文字里还有「类似职位」等别的职称：卡片上的职称要当成提示交给模型
    assert any(
        "hints" in m.content and "title: Backend Engineer" in m.content for msgs, _, _ in c.fake.calls for m in msgs
    )
    assert c.get(f"/api/jobs/{out['jobs'][0]['id']}").json()["verification_source"] == "job_board"


def test_job_page_that_asks_for_login_is_blocked_not_failed(linkedin_browser):
    c, setup = linkedin_browser
    setup(LOGIN)
    site = run(c)["sites"][0]
    assert site["status"] == "blocked" and "读不到" in site["message"]


def test_job_page_redirected_to_the_search_page_is_expired(linkedin_browser):
    c, setup = linkedin_browser
    setup(b.BrowserPage(url="https://www.linkedin.com/jobs/search-results/", title="Jobs", text="x", links=[]))
    assert "已下架 1" in run(c)["sites"][0]["message"]


def test_window_closed_while_reading_a_job_fails_that_job_only(linkedin_browser, monkeypatch):
    import app.search.process as process_mod

    c, setup = linkedin_browser
    setup(LOGIN)

    def closed(*args, **kwargs):
        raise b.BrowserError("窗口被关掉了")

    monkeypatch.setattr(process_mod, "open_checked", closed)
    out = run(c)
    assert out["status"] == "completed" and "窗口被关掉了" in out["sites"][0]["message"]


def test_browser_site_is_skipped_when_the_feature_is_off(linkedin_browser):
    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.models import Integration

    c, setup = linkedin_browser
    fb = setup(LOGIN)
    with get_sessionmaker()() as db:
        db.scalar(select(Integration).where(Integration.kind == "browser")).enabled = False
        db.commit()
    site = run(c)["sites"][0]
    assert site["status"] == "skipped" and "登录浏览器" in site["message"] and fb.opened == []


def test_browser_sites_are_searched_last(monkeypatch):
    """模型搜索和浏览器搜索共用搜索名额：浏览器可能要等用户处理验证，排最后才不会挡住别的网站。"""
    import app.graphs.search as g

    order = []

    def search(site):
        order.append(site["id"])
        return g.SiteReport(site["id"], "ok")

    all_sites = ({**LINKEDIN, "access_method": "browser"}, {**LINKEDIN, "id": "indeed"}, GREENHOUSE)
    _graph_process(monkeypatch, {}, [], sites=all_sites, search=search)
    assert order == ["greenhouse", "indeed", "linkedin"]


# ---------- 设定 API ----------


def test_feature_is_off_by_default_and_can_be_turned_on(client):
    assert client.get("/api/browser").json()["enabled"] is False
    assert client.put("/api/browser", json={"enabled": True}).json()["enabled"] is True
    assert client.get("/api/browser").json()["enabled"] is True


def test_only_linkedin_can_use_the_browser_and_only_when_enabled(client):
    def patch(site, method):
        return client.patch(f"/api/job-sites/{site}", json={"access_method": method})

    assert patch("linkedin", "browser").status_code == 422  # 功能没开
    client.put("/api/browser", json={"enabled": True})
    assert patch("indeed", "browser").status_code == 422  # 这次只做 LinkedIn
    assert patch("greenhouse", "web_search").status_code == 422  # 公司招聘板不能改取得方式
    assert patch("linkedin", "browser").json()["access_method"] == "browser"
    assert patch("linkedin", "web_search").json()["access_method"] == "web_search"


def test_turning_the_feature_off_puts_linkedin_back_on_web_search(client, monkeypatch):
    import app.api.browser as api

    closed = []
    monkeypatch.setattr(api, "close_browser", lambda: closed.append(1))
    client.put("/api/browser", json={"enabled": True})
    client.patch("/api/job-sites/linkedin", json={"access_method": "browser"})
    assert client.put("/api/browser", json={"enabled": False}).json()["enabled"] is False
    by_id = {s["id"]: s for s in client.get("/api/job-sites").json()}
    assert by_id["linkedin"]["access_method"] == "web_search" and closed == [1]


def test_unavailable_browser_cannot_be_enabled(client, monkeypatch):
    import app.api.browser as api

    monkeypatch.setattr(api, "availability", lambda: (False, "没有安装 Playwright"))
    r = client.put("/api/browser", json={"enabled": True})
    assert r.status_code == 422 and "Playwright" in r.json()["detail"]
    assert client.get("/api/browser").json() == {
        "enabled": False,
        "available": False,
        "reason": "没有安装 Playwright",
        "window_open": False,
        "logged_in": {"linkedin": None},
    }


def test_open_window_goes_to_the_login_page_only_when_enabled(client, fake_browser):
    import time as real_time

    fb = fake_browser({"https://www.linkedin.com/login": LOGIN})
    assert client.post("/api/browser/open", json={"site": "linkedin"}).status_code == 409  # 功能没开
    client.put("/api/browser", json={"enabled": True})
    assert client.post("/api/browser/open", json={"site": "indeed"}).status_code == 422
    assert client.post("/api/browser/open", json={"site": "linkedin"}).status_code == 202
    for _ in range(50):  # 在背景打开，不等结果
        if fb.opened:
            break
        real_time.sleep(0.02)
    assert fb.opened == ["https://www.linkedin.com/login"]
    assert client.get("/api/browser").json()["logged_in"] == {"linkedin": False}  # 停在登录页


def test_clearing_the_profile_closes_the_window_and_deletes_the_folder(client, monkeypatch, tmp_path):
    import app.api.browser as api

    closed = []
    folder = tmp_path / "browser-profile"
    folder.mkdir()
    (folder / "Cookies").write_text("x")
    monkeypatch.setattr(api, "profile_dir", lambda: folder)
    monkeypatch.setattr(api, "close_browser", lambda: closed.append(1))
    b.logged_in["linkedin"] = True
    assert client.delete("/api/browser/profile").status_code == 204
    assert closed == [1] and not folder.exists() and b.logged_in == {}


def test_profile_cannot_be_cleared_while_a_search_is_running(client, monkeypatch, tmp_path):
    import app.api.browser as api
    from app.search import progress

    folder = tmp_path / "browser-profile"
    folder.mkdir()
    monkeypatch.setattr(api, "profile_dir", lambda: folder)
    progress.begin("busy", ["linkedin"])
    try:
        assert client.delete("/api/browser/profile").status_code == 409 and folder.exists()
    finally:
        progress.finish("busy")
