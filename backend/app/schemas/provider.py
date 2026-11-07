from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import Capabilities

ProviderKind = Literal["openai", "anthropic", "openai_compatible", "ollama", "claude_cli", "codex_cli"]
Task = Literal[
    "resume_parse",
    "resume_review",
    "job_extract",
    "match_score",
    "sponsor_entity",
    "cover_letter",
    "qa",
    "search",
    "embedding",
]


class ProviderIn(BaseModel):
    kind: ProviderKind
    name: str = Field(min_length=1, max_length=80)
    base_url: str | None = None
    api_key: str | None = None  # 只写，不回传
    default_model: str = Field(min_length=1)
    capabilities: Capabilities | None = None  # 不填则用该类型的预设
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    base_url: str | None = None
    api_key: str | None = None  # 空字串 = 清除
    default_model: str | None = Field(None, min_length=1)
    capabilities: Capabilities | None = None
    enabled: bool | None = None


class ProviderOut(BaseModel):
    """不包含完整 key，只有末四码。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ProviderKind
    name: str
    base_url: str | None
    api_key_last4: str | None
    has_api_key: bool
    default_model: str
    capabilities: Capabilities
    enabled: bool
    last_checked_at: datetime | None
    last_check_error: str | None
    created_at: datetime


class TestResult(BaseModel):
    ok: bool
    message: str
    sample: str | None = None


class CliStatusOut(BaseModel):
    name: str
    available: bool
    version: str | None
    error: str | None
    # not_installed / signed_in / signed_out / invalid（CLI 说已登录但实际调用回报失效）/ unknown
    state: str
    email: str | None = None
    auth_method: str | None = None


class CliLoginOut(BaseModel):
    cli: str
    running: bool
    url: str | None
    output: str
    exit_code: int | None
    started_at: float
    message: str


class LoginCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class CliInfo(BaseModel):
    clis: list[CliStatusOut]
    notice: str
    login: CliLoginOut | None = None


class TaskRouteIn(BaseModel):
    provider_id: uuid.UUID
    model: str = Field(min_length=1)
    params: dict | None = None


class TaskRouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task: Task
    label: str
    provider_id: uuid.UUID | None
    model: str | None
    params: dict | None = None
