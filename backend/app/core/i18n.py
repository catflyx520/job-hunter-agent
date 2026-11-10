"""后端产生的文字跟着介面语言走（英文预设，另有中文）。

- 前端每个请求带 `X-UI-Lang: en|zh`，中介层把它放进 contextvar；背景执行（搜索批次）用 copy_context 带过去。
- 程式里给用户看的句子写成 tr("中文原文", 变数=...)，英文放在 app/core/i18n_en.py。
- 给模型的指令用 output_language()，让模型用同一种语言写说明。
- 已经存进资料库的文字（例如旧的评分说明）维持产生当时的语言。
"""

from __future__ import annotations

import contextvars
from typing import Literal

from app.core.i18n_en import EN

Lang = Literal["en", "zh"]
DEFAULT: Lang = "en"
_lang: contextvars.ContextVar[Lang] = contextvars.ContextVar("ui_lang", default=DEFAULT)


def parse_lang(value: str | None) -> Lang:
    v = (value or "").strip().lower()
    return "zh" if v.startswith("zh") else "en" if v.startswith("en") else DEFAULT


def set_lang(lang: Lang) -> contextvars.Token:
    return _lang.set(lang)


def get_lang() -> Lang:
    return _lang.get()


def tr(zh: str, **kw: object) -> str:
    """把中文原文换成目前语言；{name} 用 kw 填入。字典里没有的句子维持中文。"""
    s = EN.get(zh, zh) if get_lang() == "en" else zh
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            s = zh.format(**kw)
    return s


def output_language() -> str:
    """给模型的指令：说明、理由、缺口要用哪种语言写。"""
    return "Simplified Chinese" if get_lang() == "zh" else "English"
