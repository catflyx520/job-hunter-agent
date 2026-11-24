"""Reach out 的请求 / 回应格式。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.job import JobSummary

RoleKind = Literal["engineer", "eng_manager", "recruiter", "other"]
Channel = Literal["connect_note", "inmail", "linkedin_message", "email"]
Direction = Literal["out", "in"]
Style = Literal["technical", "general"]


def _email(v: str | None) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    if "@" not in v or "." not in v.split("@")[-1] or " " in v:
        raise ValueError("invalid email")
    return v


class ContactIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(None, max_length=300)
    linkedin_url: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=300)
    company_id: uuid.UUID | None = None
    company_name: str | None = Field(None, max_length=200)
    role_kind: RoleKind = "other"
    found_via: Literal["web_search", "hunter", "user"] = "user"
    email_confidence: int | None = Field(None, ge=0, le=100)
    why: str | None = Field(None, max_length=1000)

    _check_email = field_validator("email")(lambda cls, v: _email(v))


class ContactPatch(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    title: str | None = Field(None, max_length=300)
    linkedin_url: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=300)
    role_kind: RoleKind | None = None
    notes: str | None = Field(None, max_length=5000)

    _check_email = field_validator("email")(lambda cls, v: _email(v))


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID | None
    company_name: str | None = None
    full_name: str
    title: str | None
    linkedin_url: str | None
    email: str | None
    email_source: str | None
    email_confidence: int | None
    found_via: str
    role_kind: str
    notes: str | None
    created_at: datetime


class ContactSummary(BaseModel):
    id: uuid.UUID
    full_name: str
    title: str | None
    company_id: uuid.UUID | None
    company_name: str | None
    last_message_at: datetime | None
    last_direction: Direction | None
    message_count: int


class MessageIn(BaseModel):
    direction: Direction
    channel: Channel
    body: str = Field(max_length=20_000)
    subject: str | None = Field(None, max_length=500)
    style: Style | None = None
    job_id: uuid.UUID | None = None
    sent_at: datetime | None = None
    material_meta: dict[str, Any] | None = None

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body is empty")
        return v.strip()


class MessagePatch(BaseModel):
    body: str | None = Field(None, max_length=20_000)
    subject: str | None = Field(None, max_length=500)
    channel: Channel | None = None
    sent_at: datetime | None = None

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("body is empty")
        return v.strip() if v else v


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    job_id: uuid.UUID | None
    direction: Direction
    channel: Channel
    style: str | None
    subject: str | None
    body: str
    material_meta: dict[str, Any] | None
    sent_at: datetime


class MessageCreated(MessageOut):
    application_status: str | None = None  # 这条消息挂的职位目前的投递状态


class ContactDetail(ContactOut):
    messages: list[MessageOut] = Field(default_factory=list)
    jobs: list[JobSummary] = Field(default_factory=list)


class EmailLookupIn(BaseModel):
    domain: str | None = Field(None, max_length=300)


class EmailLookupOut(BaseModel):
    found: bool
    contact: ContactOut


class MessageDeleted(BaseModel):
    warning: str | None = None
