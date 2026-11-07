"""Provider 统一介面（SPEC 4.3）。LangGraph 节点与业务逻辑只依赖这个模块。"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError


class LLMError(RuntimeError):
    """可以直接显示给用户的错误（不含金钥、原始 log 或本机路径）。"""


class NotSupported(LLMError):
    pass


class Capabilities(BaseModel):
    structured_output: bool = True
    vision: bool = False
    web_search: bool = False
    tool_calling: bool = False


@dataclass
class ImageInput:
    mime: str
    data: bytes


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class GenerateResult:
    text: str
    model: str
    parsed: BaseModel | None = None
    usage: dict[str, Any] = field(default_factory=dict)


DEFAULT_CAPABILITIES: dict[str, Capabilities] = {
    "openai": Capabilities(structured_output=True, vision=True, web_search=True, tool_calling=True),
    "anthropic": Capabilities(structured_output=True, vision=True, web_search=True, tool_calling=True),
    "openai_compatible": Capabilities(structured_output=True),
    "ollama": Capabilities(structured_output=True, tool_calling=True),
    # CLI 模式：文字生成时停用所有工具；web_search 指 CLI 自带搜索，留给 F3 使用
    "claude_cli": Capabilities(structured_output=True, web_search=True),
    "codex_cli": Capabilities(structured_output=True, vision=True, web_search=True),
}

EMBEDDING_KINDS = {"openai", "openai_compatible", "ollama"}


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object only (no markdown fences, no commentary) "
        "that validates against this JSON Schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> str:
    """去掉 markdown fence，取第一个 `{` 到最后一个 `}`。"""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        return cleaned
    return cleaned[start : end + 1]


class LLMProvider(ABC):
    kind: str = "base"

    def __init__(self, model: str, capabilities: Capabilities | None = None):
        self.model = model
        self._capabilities = capabilities or DEFAULT_CAPABILITIES.get(self.kind, Capabilities())

    # ---- 子类实现 ----
    @abstractmethod
    def _complete(
        self, messages: list[Message], images: list[ImageInput] | None, json_mode: dict[str, Any] | None
    ) -> tuple[str, dict[str, Any]]:
        """回传 (文字, usage)。json_mode 不为 None 时是要求输出的 JSON Schema。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotSupported(f"{self.kind} 不支援 embedding，请在设置页为 embedding 任务指定其他模型。")

    def list_models(self) -> list[str]:
        return [self.model]

    # ---- 共用 ----
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def generate(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None = None,
        images: list[ImageInput] | None = None,
    ) -> GenerateResult:
        if images and not self._capabilities.vision:
            raise NotSupported("目前的模型不支援图片，请改贴文字。")
        if schema is None:
            text, usage = self._complete(messages, images, None)
            return GenerateResult(text=text, model=self.model, usage=usage)

        json_schema = schema.model_json_schema()
        msgs = _with_schema_instruction(messages, schema)
        text, usage = self._complete(msgs, images, json_schema)
        try:
            return GenerateResult(text, self.model, schema.model_validate_json(extract_json(text)), usage)
        except ValidationError as exc:
            # 失败重试一次，把错误告诉模型
            retry = msgs + [
                Message("assistant", text),
                Message(
                    "user",
                    "Your previous reply was not valid JSON for the schema. Errors:\n"
                    f"{_short_errors(exc)}\nReturn the corrected JSON object only.",
                ),
            ]
            text2, usage2 = self._complete(retry, images, json_schema)
            try:
                parsed = schema.model_validate_json(extract_json(text2))
            except ValidationError as exc2:
                raise LLMError("模型输出格式不符合要求（已重试一次），请重试或换一个模型。") from exc2
            return GenerateResult(text2, self.model, parsed, {"first": usage, "retry": usage2})


def _with_schema_instruction(messages: list[Message], schema: type[BaseModel]) -> list[Message]:
    instruction = schema_instruction(schema)
    if messages and messages[0].role == "system":
        return [Message("system", messages[0].content + "\n\n" + instruction), *messages[1:]]
    return [Message("system", instruction), *messages]


def _short_errors(exc: ValidationError) -> str:
    return "\n".join(f"- {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])


def flatten_prompt(messages: list[Message]) -> str:
    """给 CLI 用：把多轮讯息合成一段文字。"""
    parts = []
    for m in messages:
        tag = {"system": "SYSTEM", "user": "USER", "assistant": "ASSISTANT (your previous reply)"}[m.role]
        parts.append(f"### {tag}\n{m.content}")
    return "\n\n".join(parts)
