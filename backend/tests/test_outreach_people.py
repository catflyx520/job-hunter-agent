"""Reach out：找内推人（网址过滤、查询、候选人整理）。"""

import json

from app.outreach import people
from app.outreach.people import Hit, clean_linkedin_url, people_queries
from tests.samples import make_jd


def test_clean_linkedin_url():
    assert (
        clean_linkedin_url("https://uk.linkedin.com/in/Jane-Doe-123?trk=x")
        == "https://www.linkedin.com/in/jane-doe-123"
    )
    assert clean_linkedin_url("linkedin.com/in/jane-doe/") == "https://www.linkedin.com/in/jane-doe"
    for bad in (
        "https://www.linkedin.com/company/acme",
        "https://www.linkedin.com/jobs/view/1",
        "https://www.linkedin.com/posts/x",
        "https://www.linkedin.com/pub/dir/a/b",
        "https://www.linkedin.com/in/",
        "https://example.com/in/x",
        "https://notlinkedin.com/in/x",
        "",
    ):
        assert clean_linkedin_url(bad) is None, bad


def test_people_queries():
    q = people_queries("Acme", "Senior Backend Engineer", ["Backend Engineer"])
    assert q == [
        'site:linkedin.com/in "Acme" Backend Engineer',
        'site:linkedin.com/in "Acme" engineering manager',
        'site:linkedin.com/in "Acme" recruiter',
    ]
    assert len(people_queries("Acme", "Senior Backend Engineer", ["Data Engineer"])) == 4
    assert people_queries("Acme", "Staff", [])[0] == 'site:linkedin.com/in "Acme" software engineer'


def _job(client, company="Northwind Labs"):
    r = client.post("/api/jobs/ingest", json={"jd_text": make_jd("Senior Backend Engineer", company, "Remote - US")})
    assert r.status_code == 201, r.text
    return r.json()["job"]["id"]


def _hits(monkeypatch, urls):
    monkeypatch.setattr(people, "search_people", lambda db, company, queries: [Hit(url=u) for u in urls])


def test_candidates_endpoint_filters_and_dedupes(client, monkeypatch):
    job = _job(client)
    _hits(
        monkeypatch,
        [
            "https://www.linkedin.com/in/ada-sample",
            "https://uk.linkedin.com/in/Ada-Sample?trk=a",
            "https://www.linkedin.com/company/northwind",
        ],
    )
    r = client.post(f"/api/jobs/{job}/outreach/candidates", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [c["linkedin_url"] for c in out] == ["https://www.linkedin.com/in/ada-sample"]
    assert out[0]["found_via"] == "web_search" and out[0]["contact_id"] is None


def test_candidates_drop_invented_people(client, monkeypatch):
    job = _job(client)
    _hits(monkeypatch, ["https://www.linkedin.com/in/ada-sample"])
    invented = {
        "candidates": [
            {"full_name": "Ada Sample", "title": "Recruiter", "linkedin_url": "https://www.linkedin.com/in/ada-sample",
             "role_kind": "recruiter", "why": "招聘负责人"},
            {"full_name": "Ghost Person", "title": "Engineer", "linkedin_url": "https://www.linkedin.com/in/ghost",
             "role_kind": "engineer", "why": "模型编的"},
            {"full_name": "Eve Lead", "title": "Engineering Manager", "linkedin_url": "https://www.linkedin.com/in/ada-sample",
             "role_kind": "eng_manager", "why": "借了别人的网址"},
        ]
    }  # fmt: skip
    base = client.fake._responses
    client.fake._responses = lambda m, j: (
        json.dumps(invented) if (j or {}).get("title") == "CandidateList" else base(m, j)
    )
    out = client.post(f"/api/jobs/{job}/outreach/candidates", json={}).json()
    # 编出来的网址不留，没有网址也没有邮箱的人不列；同一个网址只留第一个
    assert [(c["full_name"], c["linkedin_url"]) for c in out] == [
        ("Ada Sample", "https://www.linkedin.com/in/ada-sample")
    ]


def test_candidates_sorted_engineers_first(client, monkeypatch):
    job = _job(client)
    _hits(
        monkeypatch,
        ["https://www.linkedin.com/in/r1", "https://www.linkedin.com/in/e1", "https://www.linkedin.com/in/o1"],
    )
    kinds = {"r1": "recruiter", "e1": "eng_manager", "o1": "other"}
    base = client.fake._responses

    def respond(m, j):
        if (j or {}).get("title") != "CandidateList":
            return base(m, j)
        return json.dumps(
            {"candidates": [
                {"full_name": k, "title": v, "linkedin_url": f"https://www.linkedin.com/in/{k}", "role_kind": v, "why": "x"}
                for k, v in kinds.items()
            ]}
        )  # fmt: skip

    client.fake._responses = respond
    out = client.post(f"/api/jobs/{job}/outreach/candidates", json={}).json()
    assert [c["role_kind"] for c in out] == ["eng_manager", "recruiter", "other"]


def test_candidates_without_search_source(client, monkeypatch):
    job = _job(client)
    monkeypatch.setattr(people, "get_searcher", lambda db: (None, "没有可用的搜索来源"))
    r = client.post(f"/api/jobs/{job}/outreach/candidates", json={})
    assert r.status_code == 422 and r.json()["detail"] == "没有可用的搜索来源"


def test_candidates_mark_existing_contact(client, monkeypatch, database):
    from app.core.db import get_sessionmaker
    from app.models import Contact

    job = _job(client)
    with get_sessionmaker()() as s:
        c = Contact(full_name="Ada Sample", linkedin_url="https://www.linkedin.com/in/ada-sample", found_via="user")
        s.add(c)
        s.commit()
        cid = str(c.id)
    _hits(monkeypatch, ["https://www.linkedin.com/in/ada-sample"])
    out = client.post(f"/api/jobs/{job}/outreach/candidates", json={}).json()
    assert out[0]["contact_id"] == cid


def test_candidates_with_hunter_need_domain(client, monkeypatch):
    job = _job(client)
    client.put("/api/outreach/hunter", json={"enabled": True, "api_key": "hunter-key-1"})
    _hits(monkeypatch, [])
    r = client.post(f"/api/jobs/{job}/outreach/candidates", json={"use_hunter": True})
    assert r.status_code == 422 and "公司网址" in r.json()["detail"]


def test_search_people_with_model_search(monkeypatch):
    from app.llm.base import Capabilities
    from app.llm.fake import FakeProvider
    from app.search.web import LLMSearcher
    from tests.samples import PEOPLE_URLS, fake_responder

    fake = FakeProvider(fake_responder, capabilities=Capabilities(structured_output=True, web_search=True))
    monkeypatch.setattr(people, "get_searcher", lambda db: (LLMSearcher(fake), "model"))
    hits = people.search_people(None, "Acme", ["q1", "q2"])
    assert [h.url for h in hits] == PEOPLE_URLS and fake.search_calls == 1
    # 要写明要找几个人、每个结果要带现职：否则模型搜一次就停、只回人名，整理时会全部被丢掉
    system, user = (m.content for m in fake.calls[0][0])
    assert f"about {people.PEOPLE_TARGET} " in user and "q1" in user and "q2" in user
    assert "current role" in system


def test_search_people_with_query_searcher(monkeypatch):
    from app.llm.base import LLMError
    from app.search.web import FoundJob, TavilySearcher

    s = TavilySearcher("k")
    calls = []

    def query(q, domain):
        calls.append((q, domain))
        if q == "bad":
            raise LLMError("x")
        return [FoundJob(url="https://www.linkedin.com/in/ada-sample", title="Ada")]

    monkeypatch.setattr(s, "_query", query)
    monkeypatch.setattr(people, "get_searcher", lambda db: (s, "Tavily"))
    assert len(people.search_people(None, "Acme", ["q1", "bad"])) == 1 and calls[0] == ("q1", "linkedin.com")
    import pytest

    with pytest.raises(LLMError, match="Tavily"):
        people.search_people(None, "Acme", ["bad"])


def test_hunter_people_emails_not_sent_to_model(client, monkeypatch):
    from app.outreach.hunter import HunterPerson

    job = _job(client)
    _hits(monkeypatch, [])
    hp = HunterPerson("Cara", "Demo", "Engineering Manager", "cara.demo@example.com", 92, None)
    monkeypatch.setattr(people, "_hunter_people", lambda db, company, job: [hp])
    base = client.fake._responses
    seen = {}

    def respond(m, j):
        if (j or {}).get("title") != "CandidateList":
            return base(m, j)
        seen["prompt"] = m[-1].content
        return json.dumps({"candidates": [
            {"full_name": "Cara Demo", "title": "Engineering Manager", "hunter_ref": "h1", "role_kind": "eng_manager", "why": "x"},
            {"full_name": "Nobody", "title": "x", "hunter_ref": "h9", "role_kind": "other", "why": "编号不存在"},
        ]})  # fmt: skip

    client.fake._responses = respond
    out = client.post(f"/api/jobs/{job}/outreach/candidates", json={"use_hunter": True}).json()
    assert "cara.demo@example.com" not in seen["prompt"] and "h1" in seen["prompt"]
    assert [(c["full_name"], c["email"], c["email_confidence"], c["found_via"]) for c in out] == [
        ("Cara Demo", "cara.demo@example.com", 92, "hunter")
    ]
