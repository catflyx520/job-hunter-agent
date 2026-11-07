"""SQLAlchemy 模型。M1 只建 SPEC 4.4.3 的 A（设定与模型连接）与 B（履历、需求、个人事实）两组。"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.db import Base

EMBEDDING_DIM = get_settings().embedding_dim

PROVIDER_KINDS = ("openai", "anthropic", "openai_compatible", "ollama", "claude_cli", "codex_cli")
TASKS = (
    "resume_parse",
    "resume_review",
    "job_extract",
    "match_score",
    "sponsor_entity",
    "cover_letter",
    "qa",
    "search",
    "embedding",
)
CHUNK_SECTIONS = ("summary", "experience", "project", "skills", "education")
FACT_VALUE_TYPES = ("text", "number", "date", "boolean", "choice")
FACT_SOURCES = ("user_confirmed", "resume_derived", "from_answer")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# ---------- A. 设定与模型连接 ----------


class LLMProvider(Base):
    __tablename__ = "llm_providers"
    __table_args__ = (CheckConstraint(_in("kind", PROVIDER_KINDS), name="ck_llm_providers_kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    api_key_last4: Mapped[str | None] = mapped_column(Text)
    default_model: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TaskRoute(Base):
    __tablename__ = "task_routes"
    __table_args__ = (CheckConstraint(_in("task", TASKS), name="ck_task_routes_task"),)

    task: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="RESTRICT"), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = _updated()

    provider: Mapped[LLMProvider] = relationship()


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (CheckConstraint(_in("kind", ("tavily", "searxng")), name="ck_integrations_kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# ---------- B. 履历、需求、个人事实 ----------


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (Index("uq_resumes_single_active", "is_active", unique=True, postgresql_where=text("is_active")),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    label: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parsed_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    chunks: Mapped[list["ExperienceChunk"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", passive_deletes=True
    )
    reviews: Mapped[list["ResumeReview"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", passive_deletes=True
    )


class ExperienceChunk(Base):
    __tablename__ = "experience_chunks"
    __table_args__ = (
        CheckConstraint(_in("section", CHUNK_SECTIONS), name="ck_experience_chunks_section"),
        Index(
            "ix_experience_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_experience_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True), nullable=False)
    created_at: Mapped[datetime] = _created()

    resume: Mapped[Resume] = relationship(back_populates="chunks")


class ResumeReview(Base):
    __tablename__ = "resume_reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_role: Mapped[str | None] = mapped_column(Text)
    parse_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    keyword_score: Mapped[int | None] = mapped_column(SmallInteger)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()

    resume: Mapped[Resume] = relationship(back_populates="reviews")


class Preferences(Base):
    __tablename__ = "preferences"
    __table_args__ = (CheckConstraint("id = 1", name="ck_preferences_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = _updated()


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint(_in("value_type", FACT_VALUE_TYPES), name="ck_facts_value_type"),
        CheckConstraint(_in("source", FACT_SOURCES), name="ck_facts_source"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
