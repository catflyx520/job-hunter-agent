"""邮件同步（Gmail 只读）：每次同步与处理过的信。信只存寄件人、日期、主旨与一小段证据原文。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import _created, _in, _uuid_pk

SYNC_STATUS = ("running", "completed", "failed")
MAIL_KINDS = ("application_received", "rejection", "interview", "offer", "not_evidence")
MAIL_OUTCOMES = ("created", "updated", "evidence_only", "needs_review", "ignored", "resolved")


class EmailSync(Base):
    __tablename__ = "email_syncs"
    __table_args__ = (CheckConstraint(_in("status", SYNC_STATUS), name="ck_email_syncs_status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[str] = mapped_column(Text, nullable=False)
    window_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        CheckConstraint(_in("kind", MAIL_KINDS), name="ck_email_messages_kind"),
        CheckConstraint(_in("outcome", MAIL_OUTCOMES), name="ck_email_messages_outcome"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # Gmail message id
    account: Mapped[str] = mapped_column(Text, nullable=False, server_default="")  # 哪个 Gmail 帐号
    rfc822_id: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(Text)
    view_url: Mapped[str | None] = mapped_column(Text)  # 经 Claude CLI 读信时连接器给的链接
    sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_syncs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    from_addr: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    requisition_id: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def gmail_url(self) -> str:
        from app.mail.gmail import gmail_url

        if self.view_url:
            return self.view_url
        return gmail_url(self.account, self.rfc822_id, self.thread_id or "")


__all__ = ["MAIL_KINDS", "MAIL_OUTCOMES", "SYNC_STATUS", "EmailMessage", "EmailSync"]
