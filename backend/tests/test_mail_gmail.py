"""Gmail 只读：OAuth（PKCE、只接受 gmail.readonly）、refresh 失败、列信分页、解析信件。不打真实 API。"""

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.mail import gmail


def _resp(status: int, body: dict, url: str = "https://example.test") -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", url))


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_start_auth_rejects_non_local_redirect():
    with pytest.raises(gmail.GmailError):
        gmail.start_auth("cid", "secret", "https://evil.example/api/email/gmail/callback")


def test_start_auth_url_has_readonly_scope_and_pkce():
    url = gmail.start_auth("cid", "secret", "http://localhost:5173/api/email/gmail/callback")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["scope"] == gmail.SCOPE == "https://www.googleapis.com/auth/gmail.readonly"
    assert q["code_challenge_method"] == "S256" and q["code_challenge"]
    assert q["access_type"] == "offline" and q["response_type"] == "code"
    assert q["client_id"] == "cid" and q["state"] in gmail._pending


def _token_then_profile(monkeypatch, token_body: dict):
    posts = []

    def fake_post(url, data=None, **kw):
        posts.append((url, data))
        return _resp(200, token_body, url)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _resp(200, {"emailAddress": "me@example.com"}, url))
    return posts


def test_finish_auth_stores_refresh_token(monkeypatch):
    url = gmail.start_auth("cid", "secret", "http://127.0.0.1:5173/api/email/gmail/callback")
    state = parse_qs(urlsplit(url).query)["state"][0]
    posts = _token_then_profile(monkeypatch, {"access_token": "a", "refresh_token": "r", "scope": gmail.SCOPE})
    out = gmail.finish_auth(state, "code-1")
    assert out["refresh_token"] == "r" and out["email"] == "me@example.com" and out["client_secret"] == "secret"
    assert posts[0][1]["code_verifier"] and posts[0][1]["grant_type"] == "authorization_code"
    assert state not in gmail._pending  # 只能用一次


def test_finish_auth_rejects_extra_scope(monkeypatch):
    url = gmail.start_auth("cid", "secret", "http://localhost:5173/cb")
    state = parse_qs(urlsplit(url).query)["state"][0]
    body = {
        "access_token": "a",
        "refresh_token": "r",
        "scope": f"{gmail.SCOPE} https://www.googleapis.com/auth/gmail.modify",
    }
    _token_then_profile(monkeypatch, body)
    with pytest.raises(gmail.GmailError):
        gmail.finish_auth(state, "code-1")


def test_finish_auth_unknown_state():
    with pytest.raises(gmail.GmailError):
        gmail.finish_auth("nope", "code")


def test_refresh_invalid_grant(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _resp(400, {"error": "invalid_grant"}, url))
    with pytest.raises(gmail.GmailReconnect, match="重新连接"):
        gmail.GmailClient("cid", "s", "r").access_token()


def test_list_ids_follows_pages(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _resp(200, {"access_token": "a"}, url))
    pages = {
        None: {"messages": [{"id": "m3", "threadId": "t3"}, {"id": "m2", "threadId": "t2"}], "nextPageToken": "p2"},
        "p2": {"messages": [{"id": "m1", "threadId": "t1"}]},
    }
    seen = []

    def fake_get(url, params=None, **kw):
        seen.append(params)
        return _resp(200, pages[params.get("pageToken")], url)

    monkeypatch.setattr(httpx, "get", fake_get)
    ids = gmail.GmailClient("cid", "s", "r").list_ids("after:1")
    assert ids == [("m3", "t3"), ("m2", "t2"), ("m1", "t1")]
    assert seen[0]["q"] == "after:1"


def test_get_parses_plain_and_html(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _resp(200, {"access_token": "a"}, url))
    body = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": "1762000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Acme Careers <jobs@acme.test>"},
                {"name": "Subject", "value": "Thanks for applying"},
                {"name": "Message-ID", "value": "<abc@acme.test>"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>Thank you for applying to <b>Backend Engineer</b></p>")},
                }
            ],
        },
    }
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _resp(200, body, url))
    m = gmail.GmailClient("cid", "s", "r").get("m1")
    assert m.subject == "Thanks for applying" and m.from_addr == "Acme Careers <jobs@acme.test>"
    assert m.rfc822_id == "<abc@acme.test>" and m.thread_id == "t1"
    assert "Thank you for applying to Backend Engineer" in m.text
    assert m.received_at == datetime.fromtimestamp(1762000000, UTC)


def test_search_query_window():
    q = gmail.search_query(datetime(2026, 11, 1, tzinfo=UTC))
    assert q.startswith(f"after:{int(datetime(2026, 11, 1, tzinfo=UTC).timestamp())} ")
    assert "-in:chats" in q and "interview" in q


def test_either_parts_split_subject_and_body_words():
    """Claude 的 Gmail 连接器把「主旨词或正文词」合在一起时只认正文那一半（2026-11-21 实测）：拆成两条分别搜。"""
    q = gmail.search_query(datetime(2026, 11, 1, tzinfo=UTC))
    subject, body = gmail.either_parts(q)
    head = q[: q.index("{")].rstrip()
    assert subject == f"{head} subject:({' OR '.join(gmail.SUBJECT_WORDS)})"
    assert body == f"{head} ({' OR '.join(gmail.BODY_WORDS)})"
    assert gmail.either_parts("after:1 subject:application") == ["after:1 subject:application"]


def test_gmail_url():
    assert gmail.gmail_url("me@example.com", "<abc@x>", "t1") == (
        "https://mail.google.com/mail/?authuser=me%40example.com#search/rfc822msgid%3A%3Cabc%40x%3E"
    )
    assert gmail.gmail_url("me@example.com", None, "t1").endswith("#all/t1")


def test_refresh_invalid_client(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _resp(401, {"error": "invalid_client"}, url))
    with pytest.raises(gmail.GmailReconnect, match="client ID"):
        gmail.GmailClient("cid", "s", "r").access_token()


def test_401_refreshes_once_and_retries(monkeypatch):
    tokens = iter(["a1", "a2"])
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _resp(200, {"access_token": next(tokens)}, url))
    seen = []

    def fake_get(url, params=None, headers=None, **kw):
        seen.append(headers["Authorization"])
        if headers["Authorization"] == "Bearer a1":
            return _resp(401, {"error": {"code": 401}}, url)
        return _resp(200, {"messages": [{"id": "m1", "threadId": "t1"}]}, url)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert gmail.GmailClient("cid", "s", "r").list_ids("q") == [("m1", "t1")]
    assert seen == ["Bearer a1", "Bearer a2"]


def test_search_query_excludes_sent_and_has_before():
    after, before = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 5, tzinfo=UTC)
    q = gmail.search_query(after, before)
    assert "-in:sent" in q and f"before:{int(before.timestamp())}" in q
    assert "before:" not in gmail.search_query(after)


def _state():
    url = gmail.start_auth("cid", "secret", "http://localhost:5173/cb")
    return parse_qs(urlsplit(url).query)["state"][0]


def test_finish_auth_scope_rejected_revokes(monkeypatch):
    state = _state()
    body = {"access_token": "a", "refresh_token": "r-1", "scope": f"{gmail.SCOPE} openid"}
    _token_then_profile(monkeypatch, body)
    revoked = []
    monkeypatch.setattr(gmail, "revoke", revoked.append)
    with pytest.raises(gmail.GmailError):
        gmail.finish_auth(state, "code")
    assert revoked == ["r-1"]


def test_profile_403_mentions_gmail_api(monkeypatch):
    state = _state()
    monkeypatch.setattr(
        httpx, "post", lambda url, **kw: _resp(200, {"access_token": "a", "refresh_token": "r", "scope": gmail.SCOPE})
    )
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _resp(403, {"error": {"code": 403}}, url))
    with pytest.raises(gmail.GmailError, match="Gmail API"):
        gmail.finish_auth(state, "code")


def test_finish_auth_non_json_error(monkeypatch):
    state = _state()
    bad = httpx.Response(502, text="<html>bad gateway</html>", request=httpx.Request("POST", gmail.TOKEN_URL))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: bad)
    with pytest.raises(gmail.GmailError):
        gmail.finish_auth(state, "code")


def test_search_query_subject_and_categories():
    q = gmail.search_query(datetime(2026, 11, 1, tzinfo=UTC))
    assert "subject:(" in q and "-category:promotions" in q and "-category:social" in q


def test_search_query_also_matches_interview_words_in_body():
    q = gmail.search_query(datetime(2026, 11, 1, tzinfo=UTC))
    group = q[q.index("{") : q.index("}") + 1]
    assert group.startswith("{subject:(") and ' interview "phone screen"' in group and '"schedule a call"' in group
