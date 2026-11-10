"""resume delete keeps history

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 20:00:00

- 删除履历版本时，搜索批次、职位评分、生成材料、投递记录保留，只把 resume_id 设为空
  （原本没有 ON DELETE，删除会被外键挡住）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (表, 约束名, 原本是否 NOT NULL)
REFS = [
    ("search_runs", "search_runs_resume_id_fkey", True),
    ("job_matches", "job_matches_resume_id_fkey", True),
    ("materials", "materials_resume_id_fkey", True),
    ("applications", "applications_resume_id_fkey", False),
]


def upgrade() -> None:
    for table, fk, not_null in REFS:
        if not_null:
            op.alter_column(table, "resume_id", nullable=True)
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(fk, table, "resumes", ["resume_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for table, fk, not_null in REFS:
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(fk, table, "resumes", ["resume_id"], ["id"])
        if not_null:
            op.alter_column(table, "resume_id", nullable=False)
