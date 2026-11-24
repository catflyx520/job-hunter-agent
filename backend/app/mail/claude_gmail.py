"""经由用户本机 `claude` 已连好的 claude.ai Gmail 连接器读信（只读）。
app 不碰任何 token：以子进程呼叫 `claude -p`，只放行搜索与读 thread 两个工具，写入类工具一律禁用；
信件内容直接从输出流里的工具回传 JSON 解析，不经模型转述。模型只负责呼叫工具。"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.i18n import tr
from app.llm.cli_providers import find_executable, run_cli
from app.mail.gmail import GmailError, MailMessage, either_parts, pick_body

PREFIX = "mcp__claude_ai_Gmail__"
SEARCH, THREAD = f"{PREFIX}search_threads", f"{PREFIX}get_thread"
ALLOWED = (SEARCH, THREAD)
# 明列写入类工具：就算用户设定里放行过，这里也禁用（deny 优先）
DENIED = tuple(
    PREFIX + t
    for t in (
        "send_message", "reply", "forward", "create_draft", "update_draft", "delete_draft", "trash_message",
        "trash_thread", "untrash_message", "untrash_thread", "mark_message_spam", "mark_thread_spam",
        "unmark_message_spam", "unmark_thread_spam", "label_message", "label_thread", "unlabel_message",
        "unlabel_thread", "update_message_labels", "create_label", "update_label", "delete_label",
        "apply_sensitive_message_label", "apply_sensitive_thread_label", "download_gmail_attachment",
    )
)  # fmt: skip
CONNECTOR = "claude.ai Gmail"
WHO = "Claude Code CLI"
MAX_ROUNDS = 10  # 切段搜索最多几轮（每轮一次 CLI）
PAGE = 50  # 连接器一次最多回几串（2026-11-21 实测：没有下一页）
SPLIT_TO = 35  # 切段时每段估计几串，留余地免得又拿满
SLICES = 8  # 一次 CLI 最多搜几段
BATCH = 10
META_KEYS = ("internalDate", "labelIds", "viewUrl", "snippet", "sender", "subject")  # 整串信里补进搜索结果的栏位
TIMEOUT = 600
# 工具回传太大时，Claude Code 存成档案、只回一句提示：从提示取路径，读完就删
SAVED = re.compile(r"Output has been saved to (.+?\.txt)\.?\s")
SAVED_NAME = re.compile(r"mcp-claude_ai_Gmail-(search_threads|get_thread)-\d+\.txt")


def cli_args(exe: str) -> list[str]:
    return [
        exe,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        "",  # 不开任何内建工具（读档、执行指令、上网）
        "--allowedTools",
        ",".join(ALLOWED),
        "--disallowedTools",
        ",".join(DENIED),
        # 不能用 --setting-sources ""：那会连 claude.ai 连接器一起关掉；改成关掉 hooks
        "--settings",
        json.dumps({"disableAllHooks": True}),
        "--no-session-persistence",
        "--model",
        "haiku",  # 只用来呼叫工具，用最便宜的模型
    ]


def _saved_output(text: str) -> dict | None:
    """只读 ~/.claude/projects 底下、Gmail 工具存的档案；读完就删，不在硬盘留下信件内容。"""
    m = SAVED.search(text)
    if not m:
        return None
    try:
        path = Path(m.group(1).strip()).resolve()
        root = (Path.home() / ".claude" / "projects").resolve()
    except OSError:
        return None
    if root not in path.parents or not SAVED_NAME.fullmatch(path.name) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    finally:
        path.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None


def _tool_results(stream: str) -> list[tuple[str, dict, dict]]:
    """从 stream-json 取出 (工具名, 回传的 JSON, 呼叫参数)。出现名单外的工具就停止；连接器没连上就请用户去连。"""
    names: dict[str, tuple[str, dict]] = {}
    out: list[tuple[str, dict, dict]] = []
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            status = {s.get("name"): s.get("status") for s in ev.get("mcp_servers") or []}
            if status.get(CONNECTOR) != "connected":
                raise GmailError(
                    tr("Claude CLI 没有连上 Gmail：请到 claude.ai 的「设定 → Connectors」连接 Gmail，再回来测试。")
                )
        for c in (ev.get("message") or {}).get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                if c.get("name") not in ALLOWED:
                    raise GmailError(tr("Claude CLI 试图使用读信以外的工具（{name}），已停止。", name=c.get("name")))
                names[c.get("id")] = (c["name"], c.get("input") or {})
            elif c.get("type") == "tool_result" and not c.get("is_error"):
                content = c.get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else "".join(x.get("text", "") for x in content or [] if isinstance(x, dict))
                )
                try:
                    data = json.loads(text)
                except ValueError:
                    data = _saved_output(text)
                if isinstance(data, dict):
                    name, inp = names.get(c.get("tool_use_id"), ("", {}))
                    out.append((name, data, inp))
    return out


def _window(query: str) -> tuple[int, int | None]:
    after = re.search(r"after:(\d+)", query)
    before = re.search(r"before:(\d+)", query)
    return (int(after.group(1)) if after else 0), (int(before.group(1)) if before else None)


def _slice_query(base: str, start: date, end: date) -> str:
    # 连接器不认 after:/before: 的秒数，一封都搜不到（2026-11-21 实测），只认日期；after:D 含 D 当天，before:D 不含
    return f"after:{start:%Y/%m/%d} before:{end:%Y/%m/%d} {base}".strip()


def _cuts(start: date, end: date, estimate: int) -> list[tuple[date, date]]:
    days = (end - start).days
    parts = min(days, max(2, -(-estimate // SPLIT_TO)))
    edges = [start + timedelta(days=round(days * k / parts)) for k in range(parts)] + [end]
    return [(a, b) for a, b in zip(edges, edges[1:], strict=False) if a < b]


def _received(meta: dict) -> datetime:
    return datetime.fromtimestamp(int(meta.get("internalDate") or 0) / 1000, UTC)


class ClaudeGmail:
    """和 GmailClient 一样的介面（list_ids、get），给 sync 用。"""

    def __init__(self) -> None:
        self._meta: dict[str, dict] = {}  # message id → 搜索结果里的资料
        self._order: list[str] = []
        self._bodies: dict[str, dict] = {}  # message id → get_thread 里的完整资料
        self.more = False  # 有一段日期拿满了、切不下去（一天就超过 PAGE 串），没读完

    def _run(self, prompt: str) -> list[tuple[str, dict, dict]]:
        exe = find_executable("claude")
        if not exe:
            raise GmailError(tr("找不到本机 `claude`，请先安装 Claude Code 并在终端登录。"))
        with tempfile.TemporaryDirectory(prefix="jha-mail-", ignore_cleanup_errors=True) as workdir:
            try:
                out = run_cli(cli_args(exe), prompt, WHO, cwd=workdir, cli="claude", timeout=TIMEOUT)
                return _tool_results(out)
            finally:
                # Claude Code 依工作目录在 ~/.claude/projects 建的资料夹（含存下的工具回传）：这次的临时目录专用，删掉
                project = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", workdir)
                if "jha-mail-" in project.name:
                    shutil.rmtree(project, ignore_errors=True)

    def check(self) -> None:
        self._run(
            f"Call {SEARCH} once with query 'in:inbox' and pageSize 1. Do not call any other tool. Reply only: done"
        )

    def _search(self, queries: list[str]) -> dict[str, dict]:
        """一次 CLI 跑几条搜索，用呼叫参数里的查询对回结果（模型漏掉的那条就没有）。"""
        calls = " ".join(f"Call {SEARCH} with query {json.dumps(q)} and pageSize {PAGE}." for q in queries)
        prompt = (
            f"Make exactly these {len(queries)} tool calls, one per query, in order. {calls} "
            "Do not call any other tool. Reply only: done"
        )
        return {inp.get("query"): data for name, data, inp in self._run(prompt) if name == SEARCH}

    def list_ids(self, query: str, limit: int = 2000) -> list[tuple[str, str]]:
        """连接器一次最多回 PAGE 串、没有下一页，顺序也不是新到旧：拿满的那段日期切小再搜，直到每段都不满。"""
        after, before = _window(query)
        base = re.sub(r"\b(?:after|before):\S+\s*", "", query).strip()
        # Gmail 按账号的时区解读日期：放宽成前一天、后两天，精确的范围下面用 internalDate 过滤
        start = datetime.fromtimestamp(after, UTC).date() - timedelta(days=1)
        end = (datetime.fromtimestamp(before, UTC) if before else datetime.now(UTC)).date() + timedelta(days=2)
        listed: dict[str, dict] = {}
        self.more = False
        pending = [(part, start, end) for part in either_parts(base)]
        for _ in range(MAX_ROUNDS):
            if not pending:
                break
            batch, pending = pending[:SLICES], pending[SLICES:]
            queries = {_slice_query(part, a, b): (part, a, b) for part, a, b in batch}
            got = self._search(list(queries))
            for q, (part, a, b) in queries.items():
                data = got.get(q)
                if data is None:
                    pending.append((part, a, b))  # 模型漏掉这条：下一轮再搜
                    continue
                threads = data.get("threads") or []
                full = len(threads) >= PAGE or bool(data.get("nextPageToken"))
                if full and (b - a).days > 1:
                    pending += [(part, x, y) for x, y in _cuts(a, b, int(data.get("resultCountEstimate") or 0))]
                    continue
                # shortcut: 一天之内就超过 PAGE 串时只拿得到 PAGE 串；求职信不会这么多，真的碰到再按小时切
                self.more |= full
                for thread in threads:
                    for m in thread.get("messages") or []:
                        listed[m["id"]] = m
        self.more |= bool(pending)
        # 连接器的搜索结果现在只有编号、寄件人、主旨（2026-11-21 实测）：时间与标签要读整串信才有。
        # 读过的放进 _bodies，之后 get() 直接用，不会多读。
        bare = list(dict.fromkeys(m.get("threadId") for m in listed.values() if not m.get("internalDate")))
        for i in range(0, len(bare), BATCH):
            self._read_threads([t for t in bare[i : i + BATCH] if t])
        found: dict[str, dict] = {}
        for mid, m in listed.items():
            m = {**m, **{k: v for k, v in (self._bodies.get(mid) or {}).items() if k in META_KEYS}}
            t = int(m.get("internalDate") or 0) / 1000
            if "SENT" in (m.get("labelIds") or []) or t < after or (before and t >= before):
                continue  # 自己寄出的、窗口外的（同一个 thread 里的其他信）
            found[mid] = m
        ordered = sorted(found.values(), key=lambda m: int(m.get("internalDate") or 0), reverse=True)[:limit]
        self._meta.update({m["id"]: m for m in ordered})
        self._order = [m["id"] for m in ordered]
        return [(m["id"], m.get("threadId", "")) for m in ordered]

    def received_at(self, message_id: str) -> datetime:
        return _received(self._meta.get(message_id) or {})

    def _fetch(self, first: str, alone: bool = False) -> None:
        """读这封信所在的 thread，顺便读接下来（较旧）还没读的，一次最多 BATCH 个 thread。"""
        pending = (
            [first] if alone else [first] + [m for m in reversed(self._order) if m not in self._bodies and m != first]
        )
        threads: list[str] = []
        for mid in pending:
            tid = (self._meta.get(mid) or {}).get("threadId")
            if tid and tid not in threads:
                threads.append(tid)
            if len(threads) >= BATCH:
                break
        self._read_threads(threads)

    def _read_threads(self, threads: list[str]) -> None:
        if not threads:
            return
        prompt = (
            f"Call {THREAD} once for each of these threadId values: {json.dumps(threads)}. "
            "Do not call any other tool. Reply only: done"
        )
        for name, data, _ in self._run(prompt):
            if name == THREAD:
                for m in data.get("messages") or []:
                    self._bodies[m["id"]] = m

    def get(self, message_id: str) -> MailMessage:
        if message_id not in self._bodies:
            self._fetch(message_id)
        if message_id not in self._bodies:
            self._fetch(message_id, alone=True)  # 这批漏掉了：单独再读一次
        full = self._bodies.get(message_id) or {}
        meta = {**self._meta.get(message_id, {}), **full}
        # 还是读不到就用搜索结果的摘要；摘要多半核对不过，会列为需要确认，但不挡住整次同步
        # 连接器回传的主旨、寄件人、摘要带 HTML 转义（R&amp;A）
        text = pick_body(meta.get("plaintextBody") or "", meta.get("htmlBody") or "") or html.unescape(
            meta.get("snippet", "")
        )
        return MailMessage(
            id=message_id,
            thread_id=meta.get("threadId", ""),
            rfc822_id=None,
            received_at=_received(meta),
            from_addr=html.unescape(meta.get("sender", "")),
            subject=html.unescape(meta.get("subject", "")),
            text=text,
            view_url=meta.get("viewUrl"),
        )
