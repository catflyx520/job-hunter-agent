"""email sync (Gmail read-only)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 12:00:00

- 新增 email_syncs、email_messages（邮件同步：只读 Gmail，用邮件更新投递状态）
- application_events 加 source（user / email）与 email_message_id（信件证据）
- integration 加 gmail；模型任务加 email_classify；职位验证来源加 email；job_sites 加 email
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TASKS = (
    "resume_parse",
    "resume_review",
    "job_extract",
    "match_score",
    "sponsor_entity",
    "cover_letter",
    "qa",
    "search",
    "embedding",
    "outreach",
)
OLD_KINDS = ("tavily", "searxng", "hunter")
OLD_VERIFICATION = ("employer_site", "ats_api", "job_board", "search_snippet", "pasted")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _replace_check(name: str, table: str, sql: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, sql)


def upgrade() -> None:
    _replace_check("ck_task_routes_task", "task_routes", _in("task", (*OLD_TASKS, "email_classify")))
    _replace_check("ck_integrations_kind", "integrations", _in("kind", (*OLD_KINDS, "gmail")))
    _replace_check("ck_jobs_verification", "jobs", _in("verification_source", (*OLD_VERIFICATION, "email")))
    op.execute(
        "INSERT INTO job_sites (id, name, access_method, sort_order, limitation_note) "
        "VALUES ('email', '邮件', 'paste_only', 200, '邮件同步建的职位') ON CONFLICT (id) DO NOTHING"
    )

    op.create_table(
        "email_syncs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("window_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("status", ("running", "completed", "failed")), name="ck_email_syncs_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("account", sa.Text(), server_default="", nullable=False),
        sa.Column("rfc822_id", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("view_url", sa.Text(), nullable=True),
        sa.Column("sync_id", sa.UUID(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_addr", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("requisition_id", sa.Text(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("kind", ("application_received", "rejection", "interview", "offer", "not_evidence")),
            name="ck_email_messages_kind",
        ),
        sa.CheckConstraint(
            _in("outcome", ("created", "updated", "evidence_only", "needs_review", "ignored", "resolved")),
            name="ck_email_messages_outcome",
        ),
        sa.ForeignKeyConstraint(["sync_id"], ["email_syncs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_messages_sync_id", "email_messages", ["sync_id"])
    op.create_index("ix_email_messages_job_id", "email_messages", ["job_id"])

    op.add_column("application_events", sa.Column("source", sa.Text(), server_default="user", nullable=False))
    op.add_column("application_events", sa.Column("email_message_id", sa.Text(), nullable=True))
    op.create_check_constraint("ck_application_events_source", "application_events", "source IN ('user', 'email')")
    op.create_foreign_key(
        "fk_application_events_email_message_id",
        "application_events",
        "email_messages",
        ["email_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_application_events_email_message_id", "application_events", type_="foreignkey")
    op.drop_constraint("ck_application_events_source", "application_events", type_="check")
    op.drop_column("application_events", "email_message_id")
    op.drop_column("application_events", "source")
    op.drop_table("email_messages")
    op.drop_table("email_syncs")
    op.execute("DELETE FROM job_sources WHERE site_id = 'email'")
    op.execute("DELETE FROM job_sites WHERE id = 'email'")
    op.execute("UPDATE jobs SET verification_source = 'pasted' WHERE verification_source = 'email'")
    op.execute("DELETE FROM integrations WHERE kind = 'gmail'")
    op.execute("DELETE FROM task_routes WHERE task = 'email_classify'")
    _replace_check("ck_jobs_verification", "jobs", _in("verification_source", OLD_VERIFICATION))
    _replace_check("ck_integrations_kind", "integrations", _in("kind", OLD_KINDS))
    _replace_check("ck_task_routes_task", "task_routes", _in("task", OLD_TASKS))
