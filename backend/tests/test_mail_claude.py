"""经由本机 Claude CLI 的 Gmail 连接器读信：只放行读信工具、直接解析工具回传的 JSON、跳过自己寄出的信。不打真实 CLI。"""

import json
import re
from datetime import UTC, datetime

import pytest

from app.mail import claude_gmail as cg
from app.mail.gmail import GmailError

G = "mcp__claude_ai_Gmail__"
T0 = 1_762_000_000_000  # 毫秒


def _init(connected=True):
    servers = [{"name": "claude.ai Gmail", "status": "connected" if connected else "needs-auth"}]
    return {"type": "system", "subtype": "init", "mcp_servers": servers}


def _call(name, result, i=0, inp=None):
    use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp or {}}]},
    }
    res = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": [{"type": "text", "text": json.dumps(result)}]}
    ]}}  # fmt: skip
    return [use, res]


def _stream(*events):
    lines = [_init()] + [e for ev in events for e in (ev if isinstance(ev, list) else [ev])]
    lines.append({"type": "result", "subtype": "success"})
    return "\n".join(json.dumps(x) for x in lines)


def _answer(*results):
    """回应一次搜索：依提示里查询的顺序配上结果，工具呼叫带上那条查询（程序靠它对回是哪一段日期）。"""

    def respond(prompt):
        queries = [json.loads(q) for q in re.findall(r'query ("(?:[^"\\]|\\.)*")', prompt)]
        assert len(queries) == len(results), (queries, len(results))
        return _stream(
            *[
                _call(f"{G}search_threads", r, i, {"query": q})
                for i, (q, r) in enumerate(zip(queries, results, strict=True))
            ]
        )

    return respond


def _queries(prompt):
    return [json.loads(q) for q in re.findall(r'query ("(?:[^"\\]|\\.)*")', prompt)]


def _meta(mid, tid, ms, labels=("INBOX",), sender="Acme <jobs@acme.test>", subject="Thanks for applying"):
    return {"id": mid, "threadId": tid, "internalDate": str(ms), "labelIds": list(labels), "sender": sender,
            "subject": subject, "snippet": "x", "viewUrl": f"https://mail.google.com/mail/u/0/#all/{tid}"}  # fmt: skip


@pytest.fixture
def cli(monkeypatch):
    """假的 run_cli：依序回传准备好的输出，记下每次的参数与提示。"""
    calls = []
    outputs = []

    def fake_run_cli(args, stdin_text, who, cwd=None, cli="", timeout=None):
        calls.append((args, stdin_text))
        out = outputs.pop(0)
        return out(stdin_text) if callable(out) else out

    monkeypatch.setattr(cg, "run_cli", fake_run_cli)
    monkeypatch.setattr(cg, "find_executable", lambda name: "claude")
    return calls, outputs


def test_args_are_read_only(cli):
    args = cg.cli_args("claude")
    allowed = args[args.index("--allowedTools") + 1].split(",")
    assert sorted(allowed) == [f"{G}get_thread", f"{G}search_threads"]
    denied = args[args.index("--disallowedTools") + 1].split(",")
    for tool in ("send_message", "create_draft", "trash_message", "update_message_labels", "forward", "reply"):
        assert f"{G}{tool}" in denied
    assert args[args.index("--tools") + 1] == ""
    assert "--setting-sources" not in args  # 会关掉 claude.ai 连接器
    assert json.loads(args[args.index("--settings") + 1]) == {"disableAllHooks": True}
    assert args[args.index("--model") + 1] == "haiku"


def test_other_tool_use_stops(cli):
    _, outputs = cli
    outputs.append(_stream(_call(f"{G}send_message", {"ok": True})))
    with pytest.raises(GmailError, match="读信以外"):
        cg.ClaudeGmail().list_ids("after:1")


def test_missing_connector(cli):
    _, outputs = cli
    lines = [_init(connected=False), {"type": "result", "subtype": "success"}]
    outputs.append("\n".join(json.dumps(x) for x in lines))
    with pytest.raises(GmailError, match="Connectors"):
        cg.ClaudeGmail().list_ids("after:1")


def test_list_ids_from_search_results(cli):
    calls, outputs = cli
    found = {"threads": [
        {"id": "ta", "messages": [_meta("m1", "ta", T0 + 3000), _meta("m2", "ta", T0 + 4000, labels=("SENT",))]},
        {"id": "tb", "messages": [_meta("m3", "tb", T0 + 5000), _meta("m0", "tb", T0 - 99_000_000)]},
    ]}  # fmt: skip
    outputs.append(_answer(found))
    ids = cg.ClaudeGmail().list_ids(f"after:{T0 // 1000} -in:chats", limit=10)
    assert ids == [("m3", "tb"), ("m1", "ta")]  # 新到旧；跳过 SENT 与窗口外的信
    assert f"{G}search_threads" in calls[0][1]


def test_connector_gets_dates_not_seconds(cli):
    """连接器不认 after:/before: 的秒数，一封都搜不到（2026-11-21 实测）：要换成日期，前后各放宽一天。"""
    calls, outputs = cli
    outputs.append(_answer({"threads": []}))
    after = int(datetime(2026, 11, 4, 9, 0, tzinfo=UTC).timestamp())
    before = int(datetime(2026, 11, 20, 23, 0, tzinfo=UTC).timestamp())
    cg.ClaudeGmail().list_ids(f"after:{after} before:{before} -in:chats subject:(applying)")
    prompt = calls[0][1]
    assert "after:2026/11/03" in prompt and "before:2026/11/22" in prompt and "-in:chats subject:(applying)" in prompt
    assert str(after) not in prompt and str(before) not in prompt


def test_get_reads_thread_body_in_batches(cli):
    calls, outputs = cli
    metas = [_meta(f"m{i}", f"t{i}", T0 + i * 1000) for i in range(12)]
    outputs.append(_answer({"threads": [{"id": m["threadId"], "messages": [m]} for m in metas]}))
    threads = [
        _call(
            f"{G}get_thread", {"id": m["threadId"], "messages": [{**m, "plaintextBody": f"Body {m['id']} at Acme"}]}, i
        )
        for i, m in enumerate(metas)
    ]
    outputs.append(_stream(*threads[:10]))
    outputs.append(_stream(*threads[10:]))
    client = cg.ClaudeGmail()
    ids = client.list_ids(f"after:{T0 // 1000}")
    first = client.get(ids[-1][0])  # 最旧的一封
    assert first.text == "Body m0 at Acme" and first.subject == "Thanks for applying"
    assert first.received_at == datetime.fromtimestamp(T0 / 1000, UTC) and first.from_addr == "Acme <jobs@acme.test>"
    assert first.view_url == "https://mail.google.com/mail/u/0/#all/t0"
    for mid, _ in ids:
        client.get(mid)
    assert len(calls) == 3  # 1 次搜索 + 2 批读信（10 + 2）


def test_html_only_body(cli):
    _, outputs = cli
    m = _meta("m1", "t1", T0 + 1000)
    outputs.append(_answer({"threads": [{"id": "t1", "messages": [m]}]}))
    body = {"id": "t1", "messages": [{**m, "plaintextBody": "", "htmlBody": "<p>Hello <b>Acme</b></p>"}]}
    outputs.append(_stream(_call(f"{G}get_thread", body)))
    client = cg.ClaudeGmail()
    client.list_ids(f"after:{T0 // 1000}")
    assert "Hello Acme" in client.get("m1").text


def _bare(m):
    """连接器现在的搜索结果（2026-11-21 实测）：只有编号、寄件人、主旨，没有时间与标签。"""
    return {k: m[k] for k in ("id", "threadId", "sender", "subject")}


def test_search_results_without_dates_are_filled_from_threads(cli):
    calls, outputs = cli
    mine = _meta("m2", "ta", T0 + 4000, labels=("SENT",))
    inbox = [_meta("m1", "ta", T0 + 3000), _meta("m3", "tb", T0 + 5000), _meta("m0", "tb", T0 - 99_000_000)]
    found = {"resultCountEstimate": 4, "threads": [
        {"id": "ta", "messages": [_bare(inbox[0]), _bare(mine)]},
        {"id": "tb", "messages": [_bare(inbox[1]), _bare(inbox[2])]},
    ]}  # fmt: skip
    outputs.append(_answer(found))
    full = lambda tid, ms: {"id": tid, "messages": [{**m, "plaintextBody": f"Body {m['id']}"} for m in ms]}  # noqa: E731
    outputs.append(
        _stream(
            _call(f"{G}get_thread", full("ta", [inbox[0], mine]), 1), _call(f"{G}get_thread", full("tb", inbox[1:]), 2)
        )
    )
    client = cg.ClaudeGmail()
    ids = client.list_ids(f"after:{T0 // 1000}")
    assert ids == [("m3", "tb"), ("m1", "ta")]  # 补上时间后照样跳过自己寄出的、窗口外的
    assert not client.more
    assert client.get("m1").text == "Body m1" and len(calls) == 2  # 读过的整串信直接用，不再读一次


def test_full_search_is_split_into_smaller_date_ranges(cli):
    """连接器一次最多回 50 串、没有下一页，顺序也不是新到旧：拿满就把那段日期切小再搜，直到每段都不满。"""
    calls, outputs = cli
    many = {
        "resultCountEstimate": 70,
        "threads": [{"id": f"x{i}", "messages": [_meta(f"x{i}", f"x{i}", T0 + i)]} for i in range(cg.PAGE)],
    }
    outputs.append(_answer(many))
    halves = [
        {"threads": [{"id": "ta", "messages": [_meta("m1", "ta", T0 + 3000)]}]},
        {"threads": [{"id": "tb", "messages": [_meta("m2", "tb", T0 + 9_000_000_000)]}]},
    ]
    outputs.append(_answer(*halves))
    after = T0 // 1000
    before = after + 20 * 86400
    client = cg.ClaudeGmail()
    ids = client.list_ids(f"after:{after} before:{before} -in:chats")
    assert ids == [("m1", "ta")]  # 拿满的那次结果不用，只用切小后的；m2 在窗口外
    assert not client.more and len(calls) == 2
    first, second = _queries(calls[0][1]), _queries(calls[1][1])
    assert first == ["after:2025/10/31 before:2025/11/23 -in:chats"]
    assert second == ["after:2025/10/31 before:2025/11/12 -in:chats", "after:2025/11/12 before:2025/11/23 -in:chats"]


def test_subject_and_body_words_are_searched_separately(cli):
    from app.mail.gmail import BODY_WORDS, search_query

    calls, outputs = cli
    by_subject = {"threads": [{"id": "ta", "messages": [_meta("m1", "ta", T0 + 3000)]}]}
    by_body = {"threads": [{"id": "tb", "messages": [_meta("m2", "tb", T0 + 4000)]}, by_subject["threads"][0]]}
    outputs.append(_answer(by_subject, by_body))
    ids = cg.ClaudeGmail().list_ids(search_query(datetime.fromtimestamp(T0 / 1000, UTC)))
    assert ids == [("m2", "tb"), ("m1", "ta")]  # 两条的结果合并、去重
    subject_q, body_q = _queries(calls[0][1])
    assert "subject:(application OR" in subject_q and "{" not in subject_q
    assert body_q.endswith("(" + " OR ".join(BODY_WORDS) + ")") and "subject:" not in body_q


def test_one_day_still_full_is_reported_as_more(cli):
    """一天之内就超过 50 串时切不下去：只能拿到 50 串，标成「还有」让 sync 知道没读完。"""
    calls, outputs = cli
    full = {"threads": [{"id": f"x{i}", "messages": [_meta(f"x{i}", f"x{i}", T0 + i)]} for i in range(cg.PAGE)]}

    def always_full(prompt):
        return _answer(*[full] * len(_queries(prompt)))(prompt)

    outputs.extend([always_full] * cg.MAX_ROUNDS)
    client = cg.ClaudeGmail()
    ids = client.list_ids(f"after:{T0 // 1000} before:{T0 // 1000 + 3600}")
    assert client.more and [i for i, _ in ids][:1] == ["x49"]  # 一天一段还是拿满：留下拿到的，标成还有
    assert all(len(_queries(c[1])) <= cg.SLICES for c in calls)
    for q in _queries(calls[-1][1]):  # 切到一天一段才停
        a, b = (datetime.strptime(x, "%Y/%m/%d") for x in re.findall(r"(?:after|before):(\S+)", q))
        assert (b - a).days == 1


def _notice(path):
    return f"Error: result (51,201 characters) exceeds maximum allowed tokens. Output has been saved to {path}.\nFormat: JSON"


def test_large_result_read_from_saved_file(cli, tmp_path, monkeypatch):
    _, outputs = cli
    monkeypatch.setattr(cg.Path, "home", lambda: tmp_path)
    saved = tmp_path / ".claude" / "projects" / "C--tmp-jha-mail-x" / "s1" / "tool-results"
    saved.mkdir(parents=True)
    m = _meta("m1", "t1", T0 + 1000)
    f = saved / "mcp-claude_ai_Gmail-get_thread-1794971683318.txt"
    f.write_text(json.dumps({"id": "t1", "messages": [{**m, "plaintextBody": "Big body at Acme"}]}), encoding="utf-8")
    outputs.append(_answer({"threads": [{"id": "t1", "messages": [m]}]}))
    use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "x", "name": f"{G}get_thread", "input": {}}]},
    }
    res = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": _notice(f)}]}}
    outputs.append(_stream([use, res]))
    client = cg.ClaudeGmail()
    client.list_ids(f"after:{T0 // 1000}")
    assert client.get("m1").text == "Big body at Acme"
    assert not f.exists()  # 读完就删，不在硬盘留下信件内容


def test_saved_file_outside_claude_projects_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(cg.Path, "home", lambda: tmp_path)
    other = tmp_path / "secret.txt"
    other.write_text('{"id": "t1", "messages": []}', encoding="utf-8")
    use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "x", "name": f"{G}get_thread", "input": {}}]},
    }
    res = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": _notice(other)}]},
    }
    assert cg._tool_results(_stream([use, res])) == [] and other.exists()


def test_missing_thread_retried_then_snippet(cli):
    calls, outputs = cli
    m = {**_meta("m1", "t1", T0 + 1000), "snippet": "Thank you for applying at Acme"}
    outputs.append(_answer({"threads": [{"id": "t1", "messages": [m]}]}))
    outputs.append(_stream())  # 这批没读到 t1
    outputs.append(_stream())  # 单独重读也没有
    client = cg.ClaudeGmail()
    client.list_ids(f"after:{T0 // 1000}")
    msg = client.get("m1")
    assert msg.text == "Thank you for applying at Acme" and len(calls) == 3
    assert '["t1"]' in calls[2][1]


def test_stub_plaintext_uses_html_and_unescapes(cli):
    _, outputs = cli
    m = _meta("m1", "t1", T0 + 1000, subject="Update from R&amp;A Risk", sender="R&amp;A <jobs@ra.test>")
    outputs.append(_answer({"threads": [{"id": "t1", "messages": [m]}]}))
    html = "<p>Your application was sent to Max Tech</p><p>Associate Software Engineer</p><p>Full-time, Remote</p>"
    body = {"id": "t1", "messages": [{**m, "plaintextBody": "Your application was sent to Max Tech", "htmlBody": html}]}
    outputs.append(_stream(_call(f"{G}get_thread", body)))
    client = cg.ClaudeGmail()
    client.list_ids(f"after:{T0 // 1000}")
    msg = client.get("m1")
    assert "Associate Software Engineer" in msg.text
    assert msg.subject == "Update from R&A Risk" and msg.from_addr == "R&A <jobs@ra.test>"
