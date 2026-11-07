"""以 API 连线的 provider：OpenAI、OpenAI 兼容端点、Anthropic、Ollama。"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.llm.base import Capabilities, ImageInput, LLMError, LLMProvider

REQUEST_TIMEOUT = 120.0


def _b64(img: ImageInput) -> str:
    return base64.b64encode(img.data).decode("ascii")


def _friendly(exc: Exception, who: str) -> LLMError:
    text = str(exc).lower()
    if any(s in text for s in ("401", "unauthorized", "invalid api key", "authentication", "incorrect api key")):
        return LLMError(f"{who} 验证失败：请检查 API key。")
    if any(s in text for s in ("429", "rate limit", "quota")):
        return LLMError(f"{who} 额度或速率限制，请稍后重试。")
    if any(s in text for s in ("404", "not found", "does not exist")):
        return LLMError(f"{who} 找不到指定的模型或端点。")
    if any(s in text for s in ("connect", "timed out", "timeout", "name resolution")):
        return LLMError(f"无法连线到 {who}，请检查网址与网络。")
    return LLMError(f"{who} 呼叫失败：{type(exc).__name__}")


class OpenAIProvider(LLMProvider):
    kind = "openai"
    label = "OpenAI"

    def __init__(self, model: str, api_key: str, base_url: str | None = None, capabilities: Capabilities | None = None):
        super().__init__(model, capabilities)
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key or "not-needed", base_url=base_url or None, timeout=REQUEST_TIMEOUT)

    def _complete(self, messages, images, json_mode):
        payload: list[dict[str, Any]] = []
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        for i, m in enumerate(messages):
            if i == last_user and images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                parts += [
                    {"type": "image_url", "image_url": {"url": f"data:{img.mime};base64,{_b64(img)}"}} for img in images
                ]
                payload.append({"role": m.role, "content": parts})
            else:
                payload.append({"role": m.role, "content": m.content})
        kwargs: dict[str, Any] = {"model": self.model, "messages": payload}
        if json_mode is not None:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc
        usage = resp.usage.model_dump() if resp.usage else {}
        return resp.choices[0].message.content or "", usage

    def _complete_search(self, messages, json_mode):
        """Responses API + 内建 web_search 工具。"""
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        try:
            resp = self._client.responses.create(
                model=self.model, instructions=system or None, input=convo, tools=[{"type": "web_search"}]
            )
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
        return resp.output_text or "", usage

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = self._client.embeddings.create(model=self.model, input=texts)
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc
        return [d.embedding for d in resp.data]

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._client.models.list())
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc


class OpenAICompatibleProvider(OpenAIProvider):
    kind = "openai_compatible"
    label = "OpenAI 兼容端点"

    def _complete_search(self, messages, json_mode):
        return LLMProvider._complete_search(self, messages, json_mode)

    def _complete(self, messages, images, json_mode):
        # 很多兼容端点不支援 response_format，统一靠提示词 + Pydantic 验证
        return super()._complete(messages, images, None)


class AnthropicProvider(LLMProvider):
    kind = "anthropic"
    label = "Anthropic"
    max_tokens = 4096

    def __init__(self, model: str, api_key: str, capabilities: Capabilities | None = None):
        super().__init__(model, capabilities)
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT)

    def _complete(self, messages, images, json_mode, tools: list[dict[str, Any]] | None = None):
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [m for m in messages if m.role != "system"]
        last_user = max((i for i, m in enumerate(convo) if m.role == "user"), default=-1)
        payload: list[dict[str, Any]] = []
        for i, m in enumerate(convo):
            if i == last_user and images:
                blocks: list[dict[str, Any]] = [
                    {"type": "image", "source": {"type": "base64", "media_type": img.mime, "data": _b64(img)}}
                    for img in images
                ]
                blocks.append({"type": "text", "text": m.content})
                payload.append({"role": m.role, "content": blocks})
            else:
                payload.append({"role": m.role, "content": m.content})
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "messages": payload}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
            kwargs["max_tokens"] = 8192
        try:
            resp = self._client.messages.create(**kwargs)
            # 服务端工具（web search）跑太久时会回 pause_turn，接着让它继续，最多 3 次
            for _ in range(3):
                if getattr(resp, "stop_reason", "") != "pause_turn":
                    break
                kwargs["messages"] = payload + [{"role": "assistant", "content": resp.content}]
                resp = self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, resp.usage.model_dump() if resp.usage else {}

    def _complete_search(self, messages, json_mode):
        return self._complete(
            messages, None, json_mode, tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]
        )

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._client.models.list())
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc


class OllamaProvider(LLMProvider):
    kind = "ollama"
    label = "Ollama"

    def __init__(self, model: str, base_url: str | None, capabilities: Capabilities | None = None):
        super().__init__(model, capabilities)
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = httpx.post(f"{self.base_url}{path}", json=body, timeout=REQUEST_TIMEOUT * 2)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc

    def _complete(self, messages, images, json_mode):
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        payload = []
        for i, m in enumerate(messages):
            item: dict[str, Any] = {"role": m.role, "content": m.content}
            if i == last_user and images:
                item["images"] = [_b64(img) for img in images]
            payload.append(item)
        body: dict[str, Any] = {"model": self.model, "messages": payload, "stream": False}
        if json_mode is not None:
            body["format"] = json_mode
        data = self._post("/api/chat", body)
        usage = {k: data[k] for k in ("prompt_eval_count", "eval_count") if k in data}
        return data.get("message", {}).get("content", ""), usage

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._post("/api/embed", {"model": self.model, "input": texts})["embeddings"]

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise _friendly(exc, self.label) from exc
        return sorted(m["name"] for m in r.json().get("models", []))
