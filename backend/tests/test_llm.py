import json
import subprocess

import pytest
from pydantic import BaseModel

from app.llm import cli_providers
from app.llm.base import Capabilities, ImageInput, LLMError, Message, NotSupported, extract_json
from app.llm.cli_providers import (
    ClaudeCliProvider,
    CodexCliProvider,
    parse_claude_output,
    parse_codex_output,
    run_cli,
)
from app.llm.fake import FakeProvider


class Answer(BaseModel):
    answer: str
    needs_confirmation: list[str]


def test_extract_json_strips_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Sure! {"a": {"b": 2}} hope this helps') == '{"a": {"b": 2}}'


def test_generate_structured_ok_and_schema_in_system_prompt():
    fake = FakeProvider(['{"answer": "hi", "needs_confirmation": []}'])
    result = fake.generate([Message("user", "q")], schema=Answer)
    assert result.parsed == Answer(answer="hi", needs_confirmation=[])
    sent, _, schema = fake.calls[0]
    assert sent[0].role == "system" and "JSON Schema" in sent[0].content
    assert schema["title"] == "Answer"


def test_generate_retries_once_then_succeeds():
    fake = FakeProvider(["not json", '{"answer": "x", "needs_confirmation": ["salary"]}'])
    result = fake.generate([Message("user", "q")], schema=Answer)
    assert result.parsed.needs_confirmation == ["salary"]
    retry_msgs = fake.calls[1][0]
    assert retry_msgs[-2].role == "assistant" and retry_msgs[-2].content == "not json"
    assert "not valid JSON" in retry_msgs[-1].content


def test_generate_fails_after_one_retry():
    fake = FakeProvider(["bad", "still bad"])
    with pytest.raises(LLMError):
        fake.generate([Message("user", "q")], schema=Answer)
    assert len(fake.calls) == 2


def test_images_rejected_without_vision():
    fake = FakeProvider(["x"], capabilities=Capabilities(vision=False))
    with pytest.raises(NotSupported):
        fake.generate([Message("user", "q")], images=[ImageInput("image/png", b"x")])


def test_embedding_not_supported_by_default():
    with pytest.raises(NotSupported):
        ClaudeCliProvider("default").embed(["a"])


# ---------- CLI ----------


def test_claude_args_disable_tools_mcp_and_settings():
    args = ClaudeCliProvider("haiku").build_args("claude")
    assert args[:2] == ["claude", "-p"]
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args
    assert args[args.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in args
    assert args[args.index("--model") + 1] == "haiku"


def test_codex_args_read_only_and_images():
    args = CodexCliProvider("default").build_args("codex", "/tmp/w", ["/tmp/w/a.png"])
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--model" not in args
    assert args[args.index("--image") + 1] == "/tmp/w/a.png"
    assert args[-1] == "-"
    assert ["--disable", "shell_tool"] == args[args.index("shell_tool") - 1 : args.index("shell_tool") + 1]


def test_parse_claude_output():
    ok = json.dumps({"type": "result", "is_error": False, "result": "pong", "usage": {"output_tokens": 1}})
    assert parse_claude_output(ok) == ("pong", {"output_tokens": 1})
    expired = json.dumps({"is_error": True, "api_error_status": 401, "result": "Failed to authenticate"})
    with pytest.raises(LLMError, match="重新登录"):
        parse_claude_output(expired)
    with pytest.raises(LLMError):
        parse_claude_output("garbage")


def test_parse_codex_output_rejects_tool_use():
    lines = [
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "draft"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3}}),
    ]
    assert parse_codex_output("\n".join(lines)) == ("draft", {"input_tokens": 3})
    bad = json.dumps({"type": "item.started", "item": {"type": "command_execution"}})
    with pytest.raises(LLMError, match="工具"):
        parse_codex_output(bad)


def test_run_cli_strips_keys_and_maps_errors(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 1, b"", b"Error: not logged in")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    monkeypatch.setattr(cli_providers.subprocess, "run", fake_run)
    with pytest.raises(LLMError, match="未登录"):
        run_cli(["claude"], "hi", "Claude Code CLI")
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_run_cli_timeout(monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(cli_providers.subprocess, "run", fake_run)
    with pytest.raises(LLMError, match="逾时"):
        run_cli(["codex"], "hi", "Codex CLI")
