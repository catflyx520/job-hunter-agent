"""本机 CLI 的登录状态与「页面一键登录」。

做法（参考 agents-office）：以子进程执行 CLI 自己的登录指令（`claude auth login` / `codex login`），
把它输出的官方授权网址转给前端；用户在浏览器授权后，如果 CLI 要求贴验证码，就由页面转交给 CLI 的 stdin。

原则：
- 凭证由 CLI 自己保存；app 不读取、不保存任何 token 或凭证档，验证码只转交、不记录。
- 只转发白名单网域的授权网址。
- 同一时间只允许一个登录程序。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from app.core.i18n import tr
from app.llm import auth_state
from app.llm.cli_providers import _STRIP_ENV, detect_cli, find_executable

CliName = Literal["claude", "codex"]
AuthState = Literal["not_installed", "signed_in", "signed_out", "invalid", "unknown"]

LOGIN_ARGS: dict[str, list[str]] = {"claude": ["auth", "login", "--claudeai"], "codex": ["login"]}
LOGOUT_ARGS: dict[str, list[str]] = {"claude": ["auth", "logout"], "codex": ["logout"]}

AUTH_URL = re.compile(
    r"https://(?:claude\.ai|claude\.com|console\.anthropic\.com|auth\.openai\.com|platform\.claude\.com)/[^\s\"'<>]+"
)
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
MAX_OUTPUT = 8000
LOGIN_TIMEOUT_SECONDS = 600


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    env.update({"PAGER": "cat", "NO_COLOR": "1", "TERM": "dumb"})
    return env


# ---------- 状态 ----------


@dataclass
class CliAuthInfo:
    name: str
    available: bool
    version: str | None = None
    error: str | None = None
    state: AuthState = "unknown"
    email: str | None = None
    auth_method: str | None = None


def parse_claude_status(stdout: str) -> tuple[bool | None, str | None, str | None]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, None, None
    return bool(data.get("loggedIn")), data.get("email"), data.get("authMethod")


def parse_codex_status(output: str) -> bool | None:
    lower = output.lower()
    if "not logged in" in lower:
        return False
    if "logged in" in lower:
        return True
    return None


def auth_info(name: CliName) -> CliAuthInfo:
    status = detect_cli(name)
    info = CliAuthInfo(name=name, available=status.available, version=status.version, error=status.error)
    if not status.available:
        info.state = "not_installed"
        return info
    exe = find_executable(name)
    args = [exe, "auth", "status", "--json"] if name == "claude" else [exe, "login", "status"]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=20, env=_env(), creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return info
    if name == "claude":
        logged_in, info.email, info.auth_method = parse_claude_status(out.stdout)
    else:
        logged_in = parse_codex_status(out.stdout + out.stderr)
    if logged_in is None:
        info.state = "unknown"
    elif not logged_in:
        info.state = "signed_out"
    else:
        # CLI 说已登录，但实际调用曾回报 token 失效 → 以实际调用为准
        info.state = "invalid" if auth_state.is_invalid(name) else "signed_in"
    return info


def logout(name: CliName) -> tuple[bool, str]:
    exe = find_executable(name)
    if not exe:
        return False, tr("找不到 `{name}`。", name=name)
    try:
        out = subprocess.run(
            [exe, *LOGOUT_ARGS[name]], capture_output=True, text=True, timeout=30, env=_env(), creationflags=_flags()
        )
    except (OSError, subprocess.SubprocessError):
        return False, tr("登出指令执行失败。")
    if out.returncode == 0:
        auth_state.clear(name)
        return True, tr("已登出。")
    return False, tr("登出指令回报失败。")


# ---------- 页面登录 ----------


@dataclass
class LoginSnapshot:
    cli: str
    running: bool
    url: str | None
    output: str
    exit_code: int | None
    started_at: float
    message: str


@dataclass
class _Login:
    cli: str
    proc: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    output: str = ""
    url: str | None = None
    exit_code: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class LoginManager:
    def __init__(self, popen=subprocess.Popen):
        self._popen = popen
        self._current: _Login | None = None
        self._lock = threading.Lock()

    def start(self, name: CliName) -> LoginSnapshot:
        exe = find_executable(name)
        if not exe:
            raise RuntimeError(
                tr("找不到本机 `{name}`，请先安装。后端必须直接在本机执行，不能在 docker 容器里。", name=name)
            )
        with self._lock:
            self._stop_locked()
            proc = self._popen(
                [exe, *LOGIN_ARGS[name]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=_env(),
                creationflags=_flags(),
            )
            login = _Login(cli=name, proc=proc)
            self._current = login
        threading.Thread(target=self._pump, args=(login,), daemon=True).start()
        threading.Thread(target=self._watchdog, args=(login,), daemon=True).start()
        return self.snapshot()  # type: ignore[return-value]

    def _pump(self, login: _Login) -> None:
        stream = login.proc.stdout
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            text = ANSI.sub("", chunk.decode("utf-8", errors="replace"))
            with login.lock:
                login.output = (login.output + text)[-MAX_OUTPUT:]
                if login.url is None:
                    m = AUTH_URL.search(login.output)
                    if m:
                        login.url = m.group(0).rstrip(".,;)")
        code = login.proc.wait()
        with login.lock:
            login.exit_code = code
        if code == 0:
            auth_state.clear(login.cli)

    def _watchdog(self, login: _Login) -> None:
        deadline = login.started_at + LOGIN_TIMEOUT_SECONDS
        while login.proc.poll() is None and time.time() < deadline:
            time.sleep(1)
        if login.proc.poll() is None:
            login.proc.kill()

    def snapshot(self) -> LoginSnapshot | None:
        login = self._current
        if login is None:
            return None
        with login.lock:
            running = login.exit_code is None
            if running:
                message = (
                    tr("请打开授权网址完成登录；如果页面显示验证码，把它贴到下方。")
                    if login.url
                    else tr("正在启动登录程序…")
                )
            elif login.exit_code == 0:
                message = tr("登录成功。")
            else:
                message = tr("登录程序已结束（代码 {exit_code}），没有完成登录。", exit_code=login.exit_code)
            return LoginSnapshot(
                cli=login.cli,
                running=running,
                url=login.url,
                output=login.output,
                exit_code=login.exit_code,
                started_at=login.started_at,
                message=message,
            )

    def submit_code(self, code: str) -> Literal["submitted", "invalid", "inactive"]:
        code = code.strip()
        if not code or "\n" in code or "\r" in code or len(code) > 512:
            return "invalid"
        login = self._current
        if login is None or login.proc.poll() is not None or login.proc.stdin is None:
            return "inactive"
        try:
            login.proc.stdin.write((code + "\n").encode("utf-8"))
            login.proc.stdin.flush()
        except (OSError, ValueError):
            return "inactive"
        return "submitted"

    def cancel(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._current is not None and self._current.proc.poll() is None:
            self._current.proc.kill()


login_manager = LoginManager()
