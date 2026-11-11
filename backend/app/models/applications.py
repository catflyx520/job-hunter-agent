"""F 组：投递追踪。状态由用户标记，app 不自动投递。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import _created, _in, _updated, _uuid_pk

APPLICATION_STATUS = ("saved", "applied", "interviewing", "offer", "rejected", "ghosted", "dismissed")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("status", APPLICATION_STATUS), name="ck_applications_status"),
        CheckConstraint(
            f"previous_status IS NULL OR {_in('previous_status', APPLICATION_STATUS)}",
            name="ck_applications_previous_status",
        ),
        Index("ix_applications_status", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    previous_status: Mapped[str | None] = mapped_column(Text)  # dismissed 还原时用
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 用户标记「已投递」的时间
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL")
    )
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationEvent.id"
    )


class ApplicationEvent(Base):
    """状态变更历史：只新增，不修改。"""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint(_in("to_status", APPLICATION_STATUS), name="ck_application_events_to_status"),
        Index("ix_application_events_at", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = _created()

    application: Mapped[Application] = relationship(back_populates="events")


__all__ = ["APPLICATION_STATUS", "Application", "ApplicationEvent"]
