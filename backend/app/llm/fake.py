"""测试用的假 provider，不打任何网络。"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

from app.llm.base import Capabilities, ImageInput, LLMProvider, Message

Responder = Callable[[list[Message], dict | None], str]


class FakeProvider(LLMProvider):
    kind = "fake"

    def __init__(
        self,
        responses: list[str] | Responder | None = None,
        model: str = "fake-model",
        embed_dim: int = 8,
        capabilities: Capabilities | None = None,
    ):
        super().__init__(model, capabilities or Capabilities(structured_output=True, vision=True))
        self._responses = responses if responses is not None else []
        self.embed_dim = embed_dim
        self.calls: list[tuple[list[Message], list[ImageInput] | None, dict | None]] = []

    def _complete(self, messages, images, json_mode):
        self.calls.append((messages, images, json_mode))
        if callable(self._responses):
            return self._responses(messages, json_mode), {}
        if not self._responses:
            raise AssertionError("FakeProvider 没有剩余的回应")
        return self._responses.pop(0), {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        """以内容杂凑产生稳定的单位向量。"""
        vectors = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            raw = [(digest[i % len(digest)] - 128) / 128 for i in range(self.embed_dim)]
            norm = math.sqrt(sum(x * x for x in raw)) or 1.0
            vectors.append([x / norm for x in raw])
        return vectors
