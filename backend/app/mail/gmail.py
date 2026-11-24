"""Gmail 只读连接：OAuth（用户自己的 Desktop client，PKCE）与读信。
只呼叫 users.getProfile、users.messages.list、users.messages.get；不发信、不删信、不改标签。"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlsplit

import httpx

from app.core.fetch import html_to_text
from app.core.i18n import tr
from app.llm.base import LLMError

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
STATE_TTL = 600
# 只读主旨符合这些词的信，私人邮件不会被读到也不会送去模型
SUBJECT_WORDS = (
    "application", "applying", "applied", "interview", "offer", "candidacy", '"next steps"', '"thank you for"',
    '"your interest"',
)  # fmt: skip
# 约面试的信主旨常常没有上面的词（「Schedule a call with your recruiter」、日历邀请）：正文有这些词的也读
BODY_WORDS = (
    "interview", '"phone screen"', '"schedule a call"', '"your availability"', '"technical screen"',
    '"hiring manager"',
)  # fmt: skip
# 查询条件改了就加一：下一次同步会重读最近 30 天（处理过的信照样跳过）
# 3：经 Claude CLI 读信时日期改用年/月/日（之前用秒数，连接器一封都搜不到，那几次同步等于没读）
# 4：经 Claude CLI 读信时按日期切段（连接器一次最多 50 串，之前只读到其中一部分）
# 5：经 Claude CLI 读信时主旨词、正文词分开搜（合在一起时连接器只认正文词，漏掉大部分投递确认信）
QUERY_VERSION = 5


class GmailError(LLMError):
    pass


class GmailReconnect(GmailError):
    pass


@dataclass
class MailMessage:
    id: str
    thread_id: str
    rfc822_id: str | None
    received_at: datetime
    from_addr: str
    subject: str
    text: str
    view_url: str | None = None  # 经 Claude CLI 读信时，连接器给的 Gmail 链接


# state → 授权进行中的资料（单机单进程；10 分钟过期）
_pending: dict[str, dict] = {}


def start_auth(client_id: str, client_secret: str, redirect_uri: str) -> str:
    if urlsplit(redirect_uri).hostname not in LOCAL_HOSTS:
        raise GmailError(tr("回传网址必须是本机（localhost）。"))
    now = time.time()
    for k in [k for k, v in _pending.items() if v["expires"] < now]:
        del _pending[k]
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    _pending[state] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "verifier": verifier,
        "expires": now + STATE_TTL,
    }
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def pending_redirect(state: str) -> str | None:
    p = _pending.get(state)
    return p["redirect_uri"] if p else None


def _post(url: str, data: dict) -> httpx.Response:
    try:
        return httpx.post(url, data=data, timeout=30)
    except httpx.HTTPError as exc:
        raise GmailError(tr("无法连线到 Google。")) from exc


def _get(url: str, token: str, params: dict | None = None) -> dict:
    try:
        r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except httpx.HTTPError as exc:
        raise GmailError(tr("无法连线到 Gmail。")) from exc
    if r.status_code == 401:
        raise GmailReconnect(tr("Gmail 授权已失效，请到 Settings 重新连接 Gmail。"))
    if r.status_code == 403:
        raise GmailError(tr("Gmail 拒绝了请求（403）：请确认已在 Google Cloud 启用 Gmail API。"))
    if r.status_code != 200:
        raise GmailError(tr("Gmail 回应 {status_code}。", status_code=r.status_code))
    return r.json()


def finish_auth(state: str, code: str) -> dict:
    p = _pending.pop(state, None)
    if p is None or p["expires"] < time.time():
        raise GmailError(tr("授权已过期或无效，请重新按「连接 Gmail」。"))
    r = _post(
        TOKEN_URL,
        {
            "code": code,
            "client_id": p["client_id"],
            "client_secret": p["client_secret"],
            "redirect_uri": p["redirect_uri"],
            "grant_type": "authorization_code",
            "code_verifier": p["verifier"],
        },
    )
    body = _json(r)
    if r.status_code != 200 or not body.get("access_token"):
        raise GmailError(
            tr("Google 拒绝了授权：{e}", e=body.get("error_description") or body.get("error") or r.status_code)
        )
    if set(body.get("scope", "").split()) != {SCOPE}:
        if body.get("refresh_token"):
            revoke(body["refresh_token"])  # 权限不对：不保存，也撤销 Google 已经发出的授权
        raise GmailError(tr("授权的权限不是只有「读取邮件」，已拒绝保存。请重新连接，只勾选读取权限。"))
    if not body.get("refresh_token"):
        raise GmailError(tr("Google 没有给长期授权，请到 Google 帐号移除这个 app 的权限后重新连接。"))
    profile = _get(f"{API}/profile", body["access_token"])
    return {
        "client_id": p["client_id"],
        "client_secret": p["client_secret"],
        "refresh_token": body["refresh_token"],
        "email": profile.get("emailAddress") or "",
    }


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def revoke(token: str) -> None:
    try:
        httpx.post(REVOKE_URL, data={"token": token}, timeout=15)
    except Exception:  # noqa: BLE001 - 撤销失败也要删掉本机授权
        pass


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _body(payload: dict) -> str:
    plain, html = [], []

    def walk(part: dict) -> None:
        mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    return pick_body("\n".join(plain), "\n".join(html))


def pick_body(plain: str, html: str) -> str:
    """有些信的纯文字版只有一两行，内容（例如职称）只在 HTML 版里：HTML 转出的文字明显比较多就用它。"""
    text = html_to_text(html)[0] if html else ""
    return text if len(text) > 2 * len(plain) else plain


class GmailClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self._token: str | None = None

    def access_token(self) -> str:
        if self._token:
            return self._token
        r = _post(
            TOKEN_URL,
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        error = _json(r).get("error") if r.status_code in (400, 401) else None
        if error == "invalid_grant":
            raise GmailReconnect(tr("Gmail 授权已失效，请到 Settings 重新连接 Gmail。"))
        if error in ("invalid_client", "unauthorized_client"):
            raise GmailReconnect(tr("Google 不认得保存的 client ID / client secret，请到 Settings 重新连接 Gmail。"))
        if r.status_code != 200:
            raise GmailError(tr("Google 回应 {status_code}。", status_code=r.status_code))
        self._token = _json(r).get("access_token")
        if not self._token:
            raise GmailError(tr("Google 没有回传 access token。"))
        return self._token

    def _api(self, url: str, params: dict | None = None) -> dict:
        """access token 大约一小时过期：遇到 401 先换新的再试一次，换不到才请用户重新连接。"""
        try:
            return _get(url, self.access_token(), params)
        except GmailReconnect:
            self._token = None
            return _get(url, self.access_token(), params)

    def profile_email(self) -> str:
        return self._api(f"{API}/profile").get("emailAddress") or ""

    def list_ids(self, query: str, limit: int = 2000) -> list[tuple[str, str]]:
        """回传 (message id, thread id)，Gmail 的顺序是新到旧。"""
        out: list[tuple[str, str]] = []
        page: str | None = None
        while len(out) < limit:
            params = {"q": query, "maxResults": 500}
            if page:
                params["pageToken"] = page
            data = self._api(f"{API}/messages", params)
            out += [(m["id"], m.get("threadId", "")) for m in data.get("messages") or []]
            page = data.get("nextPageToken")
            if not page:
                break
        return out[:limit]

    def get(self, message_id: str) -> MailMessage:
        data = self._api(f"{API}/messages/{message_id}", {"format": "full"})
        payload = data.get("payload") or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers") or []}
        return MailMessage(
            id=data["id"],
            thread_id=data.get("threadId", ""),
            rfc822_id=headers.get("message-id"),
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, UTC),
            from_addr=headers.get("from", ""),
            subject=headers.get("subject", ""),
            text=_body(payload),
        )


def search_query(after: datetime, before: datetime | None = None) -> str:
    # -in:sent：不读自己寄出的信（例如内推请求），那些不是雇主的回复
    window = f"after:{int(after.timestamp())}" + (f" before:{int(before.timestamp())}" if before else "")
    # 推广、社交分类多半是职位提醒与广告，不读
    words = " OR ".join(SUBJECT_WORDS)
    either = f"{{subject:({words}) {' '.join(BODY_WORDS)}}}"  # Gmail 的 {a b}：符合任一个
    return f"{window} -in:chats -in:sent -category:promotions -category:social {either}"


def either_parts(query: str) -> list[str]:
    """把 search_query 结尾的「主旨词或正文词」拆成两条。Claude 的 Gmail 连接器把两种合在一起时只认正文那一半，
    主旨词全被忽略（2026-11-21 实测：只用主旨词列得出 259 串，合在一起只剩 100 串）。其他查询原样回传。"""
    m = re.fullmatch(r"(.*?)\s*\{subject:\((.*)\) [^{}]*\}", query)
    if not m:
        return [query]
    return [f"{m.group(1)} subject:({m.group(2)})", f"{m.group(1)} ({' OR '.join(BODY_WORDS)})"]


def gmail_url(account: str, rfc822_id: str | None, thread_id: str) -> str:
    base = f"https://mail.google.com/mail/?authuser={quote(account, safe='')}"
    if rfc822_id:
        return f"{base}#search/{quote('rfc822msgid:' + rfc822_id, safe='')}"
    return f"{base}#all/{thread_id}"
