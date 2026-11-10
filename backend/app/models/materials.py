"""SPEC 4.4.3 E 组：Cover letter 与申请问答。"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import EMBEDDING_DIM, _created, _in, _updated, _uuid_pk

MATERIAL_KINDS = ("cover_letter", "qa")
JD_SOURCES = ("stored", "url", "pasted", "none")
MATERIAL_STATUS = ("pending", "running", "done", "failed", "cancelled", "interrupted")
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(_in("kind", MATERIAL_KINDS), name="ck_materials_kind"),
        CheckConstraint(_in("jd_source", JD_SOURCES), name="ck_materials_jd_source"),
        CheckConstraint(_in("status", MATERIAL_STATUS), name="ck_materials_status"),
        Index(
            "ix_materials_question_embedding",
            "question_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"question_embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    question_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    requirements: Mapped[str | None] = mapped_column(Text)
    jd_source: Mapped[str] = mapped_column(Text, nullable=False)
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_sha256: Mapped[str | None] = mapped_column(Text)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL")
    )
    facts_used: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text)
    needs_confirmation: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    images: Mapped[list["MaterialImage"]] = relationship(
        back_populates="material", cascade="all, delete-orphan", order_by="MaterialImage.position"
    )


class MaterialImage(Base):
    __tablename__ = "material_images"
    __table_args__ = (
        CheckConstraint(_in("mime", IMAGE_MIMES), name="ck_material_images_mime"),
        CheckConstraint("size_bytes <= 5242880", name="ck_material_images_size"),
        UniqueConstraint("material_id", "position", name="uq_material_images_position"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)

    material: Mapped[Material] = relationship(back_populates="images")
