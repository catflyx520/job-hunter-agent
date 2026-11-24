"""Reach out：联系人与往来消息。消息由用户自己发送，app 只记录；草稿不存。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import _created, _in, _updated, _uuid_pk

CONTACT_ROLE_KINDS = ("engineer", "eng_manager", "recruiter", "other")
CONTACT_SOURCES = ("web_search", "hunter", "user")
EMAIL_SOURCES = ("hunter", "user")
MESSAGE_DIRECTIONS = ("out", "in")
MESSAGE_CHANNELS = ("connect_note", "inmail", "linkedin_message", "email")
MESSAGE_STYLES = ("technical", "general")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(_in("role_kind", CONTACT_ROLE_KINDS), name="ck_contacts_role_kind"),
        CheckConstraint(_in("found_via", CONTACT_SOURCES), name="ck_contacts_found_via"),
        CheckConstraint(
            f"email_source IS NULL OR {_in('email_source', EMAIL_SOURCES)}", name="ck_contacts_email_source"
        ),
        Index(
            "uq_contacts_linkedin_url", "linkedin_url", unique=True, postgresql_where=text("linkedin_url IS NOT NULL")
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    email_source: Mapped[str | None] = mapped_column(Text)
    email_confidence: Mapped[int | None] = mapped_column(SmallInteger)
    found_via: Mapped[str] = mapped_column(Text, nullable=False)
    role_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="other")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    messages: Mapped[list["OutreachMessage"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", passive_deletes=True, order_by="OutreachMessage.sent_at"
    )


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    __table_args__ = (
        CheckConstraint(_in("direction", MESSAGE_DIRECTIONS), name="ck_outreach_messages_direction"),
        CheckConstraint(_in("channel", MESSAGE_CHANNELS), name="ck_outreach_messages_channel"),
        CheckConstraint(f"style IS NULL OR {_in('style', MESSAGE_STYLES)}", name="ck_outreach_messages_style"),
        Index("ix_outreach_messages_contact_sent", "contact_id", "sent_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    material_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = _created()

    contact: Mapped[Contact] = relationship(back_populates="messages")


__all__ = [
    "CONTACT_ROLE_KINDS",
    "MESSAGE_CHANNELS",
    "MESSAGE_DIRECTIONS",
    "MESSAGE_STYLES",
    "Contact",
    "OutreachMessage",
]
