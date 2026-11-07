"""SPEC 4.4.3 D 组：签证历史。"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import _created, _in, _updated, _uuid_pk

PROGRAMS = ("lca", "perm", "uscis_h1b")
ALIAS_METHODS = ("exact", "fuzzy", "llm_suggested", "user")
ALIAS_STATUS = ("suggested", "confirmed", "rejected")
SPONSOR_STATUS = ("records_found", "no_match_in_scope", "not_checked", "employer_unknown")


class SponsorDataset(Base):
    __tablename__ = "sponsor_datasets"
    __table_args__ = (
        CheckConstraint(_in("program", PROGRAMS), name="ck_sponsor_datasets_program"),
        CheckConstraint("row_count > 0", name="ck_sponsor_datasets_rows"),
        UniqueConstraint("sha256", name="uq_sponsor_datasets_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quarter: Mapped[int | None] = mapped_column(SmallInteger)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SponsorEmployer(Base):
    __tablename__ = "sponsor_employers"
    __table_args__ = (
        Index(
            "ix_sponsor_employers_trgm",
            "employer_norm",
            postgresql_using="gin",
            postgresql_ops={"employer_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employer_norm: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_variants: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)


class SponsorStat(Base):
    __tablename__ = "sponsor_stats"
    __table_args__ = (CheckConstraint(_in("program", PROGRAMS), name="ck_sponsor_stats_program"),)

    employer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sponsor_employers.id", ondelete="CASCADE"), primary_key=True
    )
    program: Mapped[str] = mapped_column(Text, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    filed: Mapped[int] = mapped_column(Integer, nullable=False)
    certified_or_approved: Mapped[int] = mapped_column(Integer, nullable=False)
    denied: Mapped[int] = mapped_column(Integer, nullable=False)
    top_titles: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    dataset_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)


class EmployerAlias(Base):
    __tablename__ = "employer_aliases"
    __table_args__ = (
        CheckConstraint(_in("method", ALIAS_METHODS), name="ck_employer_aliases_method"),
        CheckConstraint(_in("status", ALIAS_STATUS), name="ck_employer_aliases_status"),
        UniqueConstraint("company_id", "sponsor_employer_id", name="uq_employer_aliases_pair"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sponsor_employer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sponsor_employers.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    sponsor_employer: Mapped[SponsorEmployer] = relationship()


class CompanySponsorStatus(Base):
    __tablename__ = "company_sponsor_status"
    __table_args__ = (CheckConstraint(_in("status", SPONSOR_STATUS), name="ck_company_sponsor_status"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    h1b_years: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    perm_years: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
