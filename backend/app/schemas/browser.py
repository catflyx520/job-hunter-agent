from __future__ import annotations

from pydantic import BaseModel


class BrowserStatus(BaseModel):
    enabled: bool
    available: bool  # Playwright 装了没有
    reason: str | None  # 不可用的原因
    window_open: bool
    logged_in: dict[str, bool | None]  # 网站 → 最近一次看到的登录状态；None 是还没检查


class BrowserToggle(BaseModel):
    enabled: bool


class BrowserOpen(BaseModel):
    site: str
