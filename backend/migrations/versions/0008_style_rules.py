"""writing style rules

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19 18:00:00

- 新增 style_rules（从保存的修改整理出的写法规则，两类材料分开学）
- materials 加 style_rules（写这份草稿时用的规则文字）、style_learned_at（修改上次被整理的时间）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "style_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "source_material_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("kind", ("cover_letter", "qa")), name="ck_style_rules_kind"),
        sa.CheckConstraint(_in("origin", ("learned", "manual")), name="ck_style_rules_origin"),
        sa.CheckConstraint(_in("status", ("active", "removed")), name="ck_style_rules_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("materials", sa.Column("style_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("materials", sa.Column("style_learned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("materials", "style_learned_at")
    op.drop_column("materials", "style_rules")
    op.drop_table("style_rules")
