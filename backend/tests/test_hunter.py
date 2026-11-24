"""Hunter 邮箱查找：设置独立于搜索服务、回应解析、错误讯息、公司域名推断。"""

import httpx
import pytest

from app.outreach import hunter


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def _fake_get(status, body, calls=None):
    def get(url, params=None, headers=None, timeout=None):
        if calls is not None:
            calls.append((url, params, headers))
        return _Resp(status, body)

    return get


def test_hunter_does_not_replace_search_integration(client):
    assert (
        client.put("/api/search/integration", json={"kind": "tavily", "api_key": "tvly-secret-1234"}).status_code == 200
    )
    assert client.put("/api/outreach/hunter", json={"enabled": True}).status_code == 422  # 第一次要给 key
    out = client.put("/api/outreach/hunter", json={"enabled": True, "api_key": "hunter-key-9876"}).json()
    assert out == {"enabled": True, "key_last4": "9876"}
    assert client.get("/api/search/source").json()["integration"]["kind"] == "tavily"

    client.put("/api/search/integration", json={"kind": "none"})
    assert client.get("/api/outreach/hunter").json() == {"enabled": True, "key_last4": "9876"}
    assert client.get("/api/search/source").json()["integration"] is None


def test_find_email_parses_response(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get", _fake_get(200, {"data": {"email": "jane@example.com", "score": 91}}, calls))
    h = hunter.HunterClient("k-1")
    assert h.find_email("example.com", "Jane", "Doe") == ("jane@example.com", 91)
    url, params, headers = calls[0]
    assert url == "https://api.hunter.io/v2/email-finder"
    assert params == {"domain": "example.com", "first_name": "Jane", "last_name": "Doe"}
    assert headers == {"X-API-KEY": "k-1"}  # key 不放进网址

    monkeypatch.setattr(httpx, "get", _fake_get(200, {"data": {"email": None, "score": None}}))
    assert h.find_email("example.com", "Jane", "Doe") is None


def test_domain_people(monkeypatch):
    body = {
        "data": {
            "emails": [
                {"value": "a@example.com", "confidence": 90, "first_name": "Ann", "last_name": "Lee",
                 "position": "Software Engineer", "linkedin": "https://www.linkedin.com/in/ann-lee"},
                {"value": "info@example.com", "confidence": 50, "first_name": None, "last_name": None,
                 "position": None, "linkedin": None},
            ]
        }
    }  # fmt: skip
    calls = []
    monkeypatch.setattr(httpx, "get", _fake_get(200, body, calls))
    people = hunter.HunterClient("k").domain_people("example.com", ["it", "hr"])
    assert [p.first_name for p in people] == ["Ann", "Ann"]  # 没有名字的通用信箱略过；两个部门各查一次
    assert people[0].linkedin == "https://www.linkedin.com/in/ann-lee" and people[0].email == "a@example.com"
    assert [c[1]["department"] for c in calls] == ["it", "hr"] and all(c[1]["limit"] == 10 for c in calls)


@pytest.mark.parametrize(
    ("status", "words"), [(401, "无效"), (429, "额度"), (403, "频繁")]
)  # fmt: skip
def test_hunter_errors(monkeypatch, status, words):
    monkeypatch.setattr(httpx, "get", _fake_get(status, {"errors": [{"details": "x"}]}))
    with pytest.raises(hunter.HunterError) as e:
        hunter.HunterClient("k").find_email("example.com", "Jane", "Doe")
    assert words in str(e.value)


def test_hunter_connection_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(hunter.HunterError, match="无法连线到 Hunter"):
        hunter.HunterClient("k").check()


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_company_domain():
    cd = hunter.company_domain
    assert cd(_Obj(website="https://www.example.com/about"), None) == "example.com"
    assert cd(_Obj(website="example.com"), None) == "example.com"
    assert cd(_Obj(website=None), _Obj(apply_url="https://jobs.ashbyhq.com/acme/123")) is None
    assert cd(_Obj(website=None), _Obj(apply_url="https://www.linkedin.com/jobs/view/1")) is None
    assert cd(_Obj(website=None), _Obj(apply_url="https://careers.acme.io/jobs/1")) == "careers.acme.io"
    assert cd(None, None) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://weworkremotely.com/remote-jobs/acme-backend",
        "https://www.ycombinator.com/companies/acme/jobs/1",
        "https://www.workatastartup.com/jobs/1",
        "https://www.welcometothejungle.com/en/companies/acme/jobs/x",
        "https://job-boards.greenhouse.io/acme/jobs/1",
    ],
)
def test_company_domain_skips_job_boards(url):
    assert hunter.company_domain(_Obj(website=None), _Obj(apply_url=url)) is None
