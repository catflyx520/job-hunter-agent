"""M1：extensions + A 组（模型设定）+ B 组（履历、需求、个人事实）

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.core.config import get_settings
from app.models import CHUNK_SECTIONS, FACT_SOURCES, FACT_VALUE_TYPES, PROVIDER_KINDS, TASKS, _in

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    for ext in ("vector", "pg_trgm", "pgcrypto"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")

    op.create_table(
        "llm_providers",
        _id(),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text),
        sa.Column("api_key_encrypted", sa.LargeBinary),
        sa.Column("api_key_last4", sa.Text),
        sa.Column("default_model", sa.Text, nullable=False),
        sa.Column("capabilities", pg.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_check_error", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_in("kind", PROVIDER_KINDS), name="ck_llm_providers_kind"),
    )
    op.create_table(
        "task_routes",
        sa.Column("task", sa.Text, primary_key=True),
        sa.Column("provider_id", UUID, sa.ForeignKey("llm_providers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("params", pg.JSONB),
        _ts("updated_at"),
        sa.CheckConstraint(_in("task", TASKS), name="ck_task_routes_task"),
    )
    op.create_table(
        "integrations",
        _id(),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("config", pg.JSONB, nullable=False),
        sa.Column("secret_encrypted", sa.LargeBinary),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_in("kind", ("tavily", "searxng")), name="ck_integrations_kind"),
    )

    op.create_table(
        "resumes",
        _id(),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("mime", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False, unique=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("parsed", pg.JSONB, nullable=False),
        sa.Column("parsed_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false")),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "uq_resumes_single_active", "resumes", ["is_active"], unique=True, postgresql_where=sa.text("is_active")
    )

    op.create_table(
        "experience_chunks",
        _id(),
        sa.Column("resume_id", UUID, sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section", sa.Text, nullable=False),
        sa.Column("source_ref", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(get_settings().embedding_dim), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.Column(
            "tsv",
            pg.TSVECTOR,
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        _ts("created_at"),
        sa.CheckConstraint(_in("section", CHUNK_SECTIONS), name="ck_experience_chunks_section"),
    )
    op.create_index("ix_experience_chunks_resume_id", "experience_chunks", ["resume_id"])
    op.create_index(
        "ix_experience_chunks_embedding",
        "experience_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_experience_chunks_tsv", "experience_chunks", ["tsv"], postgresql_using="gin")

    op.create_table(
        "resume_reviews",
        _id(),
        sa.Column("resume_id", UUID, sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_role", sa.Text),
        sa.Column("parse_score", sa.SmallInteger, nullable=False),
        sa.Column("content_score", sa.SmallInteger, nullable=False),
        sa.Column("keyword_score", sa.SmallInteger),
        sa.Column("findings", pg.JSONB, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_resume_reviews_resume_id", "resume_reviews", ["resume_id"])

    op.create_table(
        "preferences",
        sa.Column("id", sa.SmallInteger, primary_key=True, server_default=sa.text("1")),
        sa.Column("data", pg.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        _ts("updated_at"),
        sa.CheckConstraint("id = 1", name="ck_preferences_singleton"),
    )

    op.create_table(
        "facts",
        _id(),
        sa.Column("key", sa.Text, nullable=False, unique=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("value_type", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_in("value_type", FACT_VALUE_TYPES), name="ck_facts_value_type"),
        sa.CheckConstraint(_in("source", FACT_SOURCES), name="ck_facts_source"),
    )


def downgrade() -> None:
    for table in (
        "facts",
        "preferences",
        "resume_reviews",
        "experience_chunks",
        "resumes",
        "integrations",
        "task_routes",
        "llm_providers",
    ):
        op.drop_table(table)
