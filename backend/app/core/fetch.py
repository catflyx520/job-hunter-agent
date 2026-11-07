"""安全读取公开网页（SPEC F4「安全」）：只允许公开 HTTP/HTTPS，阻挡内网 / localhost / 保留 IP，
逐次检查重导向，连线固定到已检查过的 IP（防 DNS rebinding）。遇到登录或验证页就停止，不绕过。"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import certifi

MAX_BYTES = 1024 * 1024
MAX_JSON_BYTES = 12 * 1024 * 1024
ATS_LINK = re.compile(r"^https?://(?:[\w-]+\.)*(?:greenhouse\.io|lever\.co|ashbyhq\.com)/", re.I)
MAX_REDIRECTS = 5
TIMEOUT = 12
USER_AGENT = "job-hunter-agent/0.1 (local job search assistant)"
BLOCK_PAGE = re.compile(
    r"^(?:just a moment|access denied|attention required|verify you are human|are you a robot|security check|"
    r"captcha|sign in|sign up|log in|login|please enable javascript)",
    re.I | re.M,
)
SHORT_PAGE = 1500  # 正常职位页的文字远多于这个长度；页首导航里的「Sign in」不算登录页


# 用 certifi 的根证书（与 httpx 相同）：Windows 系统证书库里的旧根证书可能已过期，会让正常网站验证失败
_TLS = ssl.create_default_context(cafile=certifi.where())


class FetchError(ValueError):
    """可以直接显示给用户的错误。blocked=True 代表网站要求登录 / 验证或拒绝自动读取（不绕过）。"""

    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


@dataclass
class FetchedPage:
    url: str
    text: str
    title: str
    retrieved_at: datetime
    links: list[str] = field(default_factory=list)  # 页面里指向 ATS（Greenhouse / Lever / Ashby）的链接


class _PageText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol"}
    HIDDEN = {"script", "style", "noscript", "svg", "template", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.in_title = False
        self.title = ""
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if ATS_LINK.match(href) and href not in self.links and len(self.links) < 20:
                self.links.append(href)
        if tag in self.HIDDEN:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.HIDDEN and self.hidden:
            self.hidden -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        out, blank = [], False
        for line in lines:
            if line:
                out.append(line)
                blank = False
            elif not blank and out:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def html_to_text(html: str) -> tuple[str, str]:
    text, title, _ = _parse_html(html)
    return text, title


def _parse_html(html: str) -> tuple[str, str, list[str]]:
    parser = _PageText()
    parser.feed(html)
    return parser.text(), parser.title.strip(), parser.links


def public_target(url: str) -> tuple[object, int, str]:
    if not isinstance(url, str) or len(url) > 2500 or re.search(r"[\x00-\x20\\]", url):
        raise FetchError("网址无效。")
    p = urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise FetchError("请使用公开的 http / https 职位网址。")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError as exc:
        raise FetchError("网址的端口无效。") from exc
    if port not in (80, 443):
        raise FetchError("只支援公开网站的标准端口（80 / 443）。")
    try:
        addresses = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError("找不到这个网站，请检查网址，或直接贴上 JD。") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0].split("%")[0]).is_global for a in addresses):
        raise FetchError("不读取 localhost、内网或保留位址；请使用公开的职位网址。")
    return p, port, addresses[0][4][0]


def _pinned(ip: str, port: int):
    def connect(address, timeout=TIMEOUT, source_address=None, **kw):
        return socket.create_connection((ip, port), timeout, source_address)

    return connect


def _get(url: str, accept: str, limit: int) -> tuple[str, str, bytes]:
    """安全 GET：回传 (最终网址, Content-Type, 内容)。"""
    for _ in range(MAX_REDIRECTS + 1):
        p, port, ip = public_target(url)
        if p.scheme == "https":
            conn = http.client.HTTPSConnection(p.hostname, port, timeout=TIMEOUT, context=_TLS)
        else:
            conn = http.client.HTTPConnection(p.hostname, port, timeout=TIMEOUT)
        # 连线固定到刚检查过的公开 IP；TLS 仍用原 hostname 做 SNI 与凭证验证
        conn._create_connection = _pinned(ip, port)  # type: ignore[attr-defined]
        try:
            path = quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~") + ("?" + p.query if p.query else "")
            conn.request(
                "GET", path, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"}
            )
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                target = resp.getheader("Location")
                if not target:
                    raise FetchError("网站的重导向无效。")
                url = urljoin(url, target)
                continue
            if resp.status in (401, 403, 429, 999):
                raise FetchError(
                    f"网站回应 {resp.status}（需要登录或拒绝自动读取）。请直接贴上 JD；本工具不绕过验证。", blocked=True
                )
            if resp.status == 404 or resp.status == 410:
                raise FetchError(f"网站回应 {resp.status}（职位可能已下架）。")
            if resp.status != 200:
                raise FetchError(f"网站回应 {resp.status}，请直接贴上 JD。")
            raw = resp.read(limit + 1)
            if len(raw) > limit:
                raise FetchError("网页内容过大，请贴上 JD 的相关段落。")
            return url, resp.getheader("Content-Type", "") or "", raw
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError("网站暂时无法读取，请直接贴上 JD。") from exc
        finally:
            conn.close()
    raise FetchError("网站重导向次数过多，请直接贴上 JD。")


def _decode(raw: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype)
    try:
        return raw.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_page(url: str) -> FetchedPage:
    url, ctype, raw = _get(url, "text/html,text/plain,application/xhtml+xml", MAX_BYTES)
    if not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
        raise FetchError("这个网址不是文字网页，请直接贴上 JD。")
    body = _decode(raw, ctype)
    text, title, links = _parse_html(body) if "html" in ctype else (body, "", [])
    if len(text) < 200 or BLOCK_PAGE.search(title) or (len(text) < SHORT_PAGE and BLOCK_PAGE.search(text[:400])):
        raise FetchError("网页读不到完整的 JD（可能需要登录、验证或由 JavaScript 产生）。请直接贴上 JD。", blocked=True)
    return FetchedPage(url=url, text=text[:40_000], title=title, retrieved_at=datetime.now(UTC), links=links)


def fetch_json(url: str) -> Any:
    """读取公开 JSON API（Greenhouse / Lever / Ashby 的公开职位板）。同样的 SSRF 防护。"""
    _, ctype, raw = _get(url, "application/json", MAX_JSON_BYTES)
    try:
        return json.loads(_decode(raw, ctype))
    except ValueError as exc:
        raise FetchError("回传的内容不是 JSON。") from exc
