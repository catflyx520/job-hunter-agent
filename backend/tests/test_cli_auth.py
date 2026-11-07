"""页面登录与登录状态（用假的登录脚本，不碰真实 CLI 或凭证）。"""

import json
import sys
import textwrap
import time

import pytest

from app.llm import auth_state, cli_auth
from app.llm.base import LLMError
from app.llm.cli_providers import parse_claude_output

FAKE_LOGIN = textwrap.dedent(
    """
    import sys
    print("\\x1b[1mOpening browser to sign in...\\x1b[0m", flush=True)
    print("If the browser didn't open, visit: https://claude.ai/oauth/authorize?code=true&state=abc.", flush=True)
    sys.stdout.write("Paste code here if prompted > ")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code == "good-code":
        print("Login successful.", flush=True)
        sys.exit(0)
    print("Invalid code", flush=True)
    sys.exit(1)
    """
)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "fake_login.py"
    script.write_text(FAKE_LOGIN, encoding="utf-8")
    monkeypatch.setattr(cli_auth, "find_executable", lambda name: sys.executable)
    monkeypatch.setitem(cli_auth.LOGIN_ARGS, "claude", [str(script)])
    auth_state.clear("claude")
    manager = cli_auth.LoginManager()
    yield manager
    manager.cancel()


def _wait(manager, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        snap = manager.snapshot()
        if snap and cond(snap):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"条件未达成：{manager.snapshot()}")


def test_login_extracts_url_and_submits_code(fake_cli):
    auth_state.mark_invalid("claude")
    fake_cli.start("claude")
    snap = _wait(fake_cli, lambda s: s.url is not None)
    assert snap.url == "https://claude.ai/oauth/authorize?code=true&state=abc"
    assert "\x1b" not in snap.output  # ANSI 已去除
    assert snap.running

    assert fake_cli.submit_code("bad\ncode") == "invalid"
    assert fake_cli.submit_code("good-code") == "submitted"
    snap = _wait(fake_cli, lambda s: not s.running)
    assert snap.exit_code == 0 and snap.message == "登录成功。"
    assert not auth_state.is_invalid("claude")  # 登录成功清除失效标记
    assert fake_cli.submit_code("again") == "inactive"


def test_login_failure_and_cancel(fake_cli):
    fake_cli.start("claude")
    _wait(fake_cli, lambda s: s.url is not None)
    fake_cli.submit_code("wrong")
    snap = _wait(fake_cli, lambda s: not s.running)
    assert snap.exit_code == 1 and "没有完成登录" in snap.message

    fake_cli.start("claude")
    _wait(fake_cli, lambda s: s.url is not None)
    fake_cli.cancel()
    assert _wait(fake_cli, lambda s: not s.running).exit_code != 0


def test_url_whitelist_ignores_other_hosts():
    assert cli_auth.AUTH_URL.search("visit https://evil.example.com/oauth") is None
    assert cli_auth.AUTH_URL.search("visit https://auth.openai.com/oauth/authorize?x=1").group(0).endswith("x=1")


def test_status_parsers():
    out = json.dumps({"loggedIn": True, "email": "someone@example.com", "authMethod": "claude.ai"})
    assert cli_auth.parse_claude_status(out) == (True, "someone@example.com", "claude.ai")
    assert cli_auth.parse_claude_status("not json") == (None, None, None)
    assert cli_auth.parse_codex_status("Logged in using ChatGPT") is True
    assert cli_auth.parse_codex_status("Not logged in") is False
    assert cli_auth.parse_codex_status("???") is None


def test_expired_token_marks_invalid(monkeypatch):
    auth_state.clear("claude")
    expired = json.dumps({"is_error": True, "api_error_status": 401, "result": "OAuth access token has expired"})
    assert auth_state.is_auth_error(expired)
    with pytest.raises(LLMError, match="本机 CLI 登录"):
        parse_claude_output(expired)


def test_auth_info_reports_invalid_over_logged_in(monkeypatch):
    import subprocess

    from app.llm.cli_providers import CliStatus

    monkeypatch.setattr(cli_auth, "detect_cli", lambda n: CliStatus(n, True, version="9.9"))
    monkeypatch.setattr(cli_auth, "find_executable", lambda n: "claude")
    monkeypatch.setattr(
        cli_auth.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"loggedIn": True, "email": "x@example.com"}), ""),
    )
    auth_state.clear("claude")
    assert cli_auth.auth_info("claude").state == "signed_in"
    auth_state.mark_invalid("claude")
    assert cli_auth.auth_info("claude").state == "invalid"
    auth_state.clear("claude")
