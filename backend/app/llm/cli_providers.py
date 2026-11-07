"""本机 CLI provider：以子进程调用用户自己安装并登录的 `claude` / `codex`。

规则（SPEC F1）：
- 不读取、不保存、不转发任何登录凭证；登录由用户在终端自己完成。
- 非交互、只做文字生成：停用所有工具、MCP、session 保存。
- 逾时（预设 180 秒）与并行上限（预设 2）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.llm import auth_state
from app.llm.base import Capabilities, LLMError, LLMProvider, flatten_prompt

_semaphore: threading.BoundedSemaphore | None = None
_sem_lock = threading.Lock()

# 不传给 CLI 的环境变量：让 CLI 用用户自己的登录状态，而不是 app 里设定的 key
_STRIP_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "APP_SECRET_KEY", "DATABASE_URL")

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _sem() -> threading.BoundedSemaphore:
    global _semaphore
    with _sem_lock:
        if _semaphore is None:
            _semaphore = threading.BoundedSemaphore(get_settings().cli_max_concurrency)
        return _semaphore


@dataclass
class CliStatus:
    name: str
    available: bool
    version: str | None = None
    error: str | None = None


def find_executable(name: str) -> str | None:
    exe = shutil.which(name)
    if exe or name != "codex":
        return exe
    # Windows 上 Codex 桌面版会把 CLI 放在 LOCALAPPDATA
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    found = sorted(base.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True) if base.exists() else []
    return str(found[0]) if found else None


def detect_cli(name: str) -> CliStatus:
    exe = find_executable(name)
    if not exe:
        return CliStatus(name, False, error=f"找不到 `{name}`，请先安装并在终端登录。")
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        version = (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
        return CliStatus(name, True, version=version)
    except (OSError, subprocess.SubprocessError):
        return CliStatus(name, False, error=f"`{name} --version` 执行失败。")


def run_cli(args: list[str], stdin_text: str, who: str, cwd: str | None = None, cli: str = "") -> str:
    """执行 CLI，回传 stdout。错误讯息不含原始 log、凭证或路径。"""
    settings = get_settings()
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    with _sem():
        try:
            proc = subprocess.run(
                args,
                input=stdin_text.encode("utf-8"),
                capture_output=True,
                timeout=settings.cli_timeout_seconds,
                env=env,
                cwd=cwd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{who} 生成逾时（{settings.cli_timeout_seconds} 秒），可重试。") from exc
        except OSError as exc:
            raise LLMError(f"无法启动 {who}，请确认已安装。") from exc
    out = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode:
        combined = proc.stderr.decode("utf-8", errors="replace") + out
        lower = combined.lower()
        if auth_state.is_auth_error(combined) or any(x in lower for x in ("unauthorized", "login", "authentication")):
            if cli:
                auth_state.mark_invalid(cli)
            raise LLMError(f"{who} 未登录或登录已失效，请到「模型设置 → 本机 CLI 登录」重新登录后重试。")
        if any(x in lower for x in ("usage limit", "rate limit", "429", "quota")):
            raise LLMError(f"{who} 额度或速率限制，请稍后重试。")
        raise LLMError(f"{who} 未能完成生成，请确认本机登录、网络与模型权限后重试。")
    return out


class ClaudeCliProvider(LLMProvider):
    kind = "claude_cli"
    label = "Claude Code CLI"

    def __init__(self, model: str, capabilities: Capabilities | None = None):
        super().__init__(model, capabilities)

    def build_args(self, exe: str) -> list[str]:
        args = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",  # 停用所有内建工具（shell、文件读写、web 等）
            "--strict-mcp-config",  # 不载入任何 MCP server
            "--setting-sources",
            "",  # 不载入 user/project 设定（hooks、权限等）
            "--no-session-persistence",
        ]
        if self.model and self.model != "default":
            args += ["--model", self.model]
        return args

    def _complete(self, messages, images, json_mode):
        if images:
            raise LLMError("Claude Code CLI 模式不支援图片。")
        exe = find_executable("claude")
        if not exe:
            raise LLMError("找不到本机 `claude`，请先安装 Claude Code 并在终端登录。")
        with tempfile.TemporaryDirectory(prefix="jha-claude-") as workdir:
            out = run_cli(self.build_args(exe), flatten_prompt(messages), self.label, cwd=workdir, cli="claude")
        try:
            result = parse_claude_output(out)
        except LLMError as exc:
            if auth_state.is_auth_error(out):
                auth_state.mark_invalid("claude")
            raise exc
        auth_state.clear("claude")
        return result


def parse_claude_output(out: str) -> tuple[str, dict[str, Any]]:
    try:
        data = json.loads(out.strip().splitlines()[-1] if out.strip() else "")
    except (ValueError, IndexError) as exc:
        raise LLMError("Claude Code CLI 输出格式无法解析，请重试。") from exc
    if data.get("is_error"):
        status = data.get("api_error_status")
        if status == 401:
            raise LLMError("Claude Code CLI 登录已失效，请到「模型设置 → 本机 CLI 登录」重新登录后重试。")
        if status == 429:
            raise LLMError("Claude Code CLI 额度或速率限制，请稍后重试。")
        raise LLMError("Claude Code CLI 回报错误，请确认登录状态与额度。")
    result = data.get("result")
    if not isinstance(result, str) or not result.strip():
        raise LLMError("Claude Code CLI 没有返回内容，请重试。")
    return result, data.get("usage") or {}


class CodexCliProvider(LLMProvider):
    kind = "codex_cli"
    label = "Codex CLI"

    # 与旧项目相同：只留文字生成，停用 shell、外挂、浏览器等功能
    DISABLED_FEATURES = (
        "shell_tool",
        "multi_agent",
        "apps",
        "plugins",
        "hooks",
        "memories",
        "image_generation",
        "unified_exec",
    )

    def __init__(self, model: str, capabilities: Capabilities | None = None):
        super().__init__(model, capabilities)

    def build_args(self, exe: str, workdir: str, image_paths: list[str]) -> list[str]:
        args = [
            exe,
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--color",
            "never",
            "--cd",
            workdir,
            "-c",
            'web_search="disabled"',
        ]
        if self.model and self.model != "default":
            args += ["--model", self.model]
        for feature in self.DISABLED_FEATURES:
            args += ["--disable", feature]
        for path in image_paths:
            args += ["--image", path]
        args.append("-")
        return args

    def _complete(self, messages, images, json_mode):
        exe = find_executable("codex")
        if not exe:
            raise LLMError("找不到本机 `codex`，请先安装 Codex CLI 并在终端登录。")
        with tempfile.TemporaryDirectory(prefix="jha-codex-") as workdir:
            paths = []
            for i, img in enumerate(images or []):
                p = Path(workdir) / f"image-{i}{_EXT.get(img.mime, '.png')}"
                p.write_bytes(img.data)
                paths.append(str(p))
            out = run_cli(
                self.build_args(exe, workdir, paths), flatten_prompt(messages), self.label, cwd=workdir, cli="codex"
            )
        result = parse_codex_output(out)
        auth_state.clear("codex")
        return result


def parse_codex_output(out: str) -> tuple[str, dict[str, Any]]:
    answers: list[str] = []
    usage: dict[str, Any] = {}
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {}) or {}
        if item.get("type") in ("command_execution", "mcp_tool_call", "file_change", "web_search"):
            raise LLMError("Codex 尝试使用文字生成以外的工具，结果未采用。")
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            answers.append(item.get("text", ""))
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
    if not answers or not answers[-1].strip():
        raise LLMError("Codex 没有返回内容，请重试。")
    return answers[-1], usage
