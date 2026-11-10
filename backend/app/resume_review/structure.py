"""用 LLM 把履历纯文字结构化为 ParsedResume，并检查有没有原文里找不到的内容。"""

from __future__ import annotations

import re

from app.core.i18n import tr
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


EXPERIENCE_HEADING = re.compile(
    r"^\s*(work |professional |relevant )?(experience|employment( history)?|work history)\s*:?\s*$", re.I | re.M
)


def empty_structure_warning(parsed: ParsedResume, raw_text: str) -> str | None:
    """原文明明有经历标题，结构化结果却没有任何经历：多半是模型漏抓，提醒用户重新结构化。"""
    if parsed.experience or not EXPERIENCE_HEADING.search(raw_text):
        return None
    return tr(
        "结构化结果里没有任何工作经历，但原文有 Experience 段落，可能是模型漏抓。请在「管理」里点「重新结构化」（可在设置页为「履历解析」换一个模型），或手动补上。"
    )


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
