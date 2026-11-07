"""用 LLM 把履历纯文字结构化为 ParsedResume，并检查有没有原文里找不到的内容。"""

from __future__ import annotations

import re

from app.llm.base import LLMProvider, Message
from app.schemas.resume import ParsedResume

SYSTEM = """You convert resume plain text into structured JSON.
Rules:
- Copy text verbatim from the resume. Do not rewrite, summarize, translate, or fix wording.
- Never invent anything. If a field is not present in the text, leave it as an empty string or empty list.
- Keep dates exactly as written (e.g. "Jan 2021", "2019 - Present").
- Each bullet point becomes one string in `bullets`, without the leading bullet symbol.
- `skills` is a flat list of individual skills as written."""

MAX_CHARS = 30_000


def structure_resume(provider: LLMProvider, raw_text: str) -> ParsedResume:
    text = raw_text[:MAX_CHARS]
    result = provider.generate(
        [Message("system", SYSTEM), Message("user", f"Resume text:\n<<<\n{text}\n>>>")],
        schema=ParsedResume,
    )
    assert isinstance(result.parsed, ParsedResume)
    return result.parsed


_WS = re.compile(r"[\W_]+", re.UNICODE)


def _norm(s: str) -> str:
    return _WS.sub(" ", s.lower()).strip()


def unverified_items(parsed: ParsedResume, raw_text: str) -> list[str]:
    """回传在原文里找不到的 bullet / 技能（可能是模型改写或编造），给用户确认。"""
    source = _norm(raw_text)
    items: list[str] = list(parsed.skills)
    for exp in parsed.experience:
        items += exp.bullets
    for proj in parsed.projects:
        items += proj.bullets
    missing = []
    for item in items:
        n = _norm(item)
        if n and n not in source:
            missing.append(item)
    return missing
