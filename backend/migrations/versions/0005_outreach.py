"""outreach contacts and messages, referred status

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11 12:00:00

- 新增 contacts、outreach_messages（Reach out：用户自己发送，app 只记录）
- 投递状态加 referred（已请求内推）；统计 view 把它算进已投递
- 模型任务加 outreach；integration 加 hunter（邮箱查找）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUS = ("saved", "applied", "interviewing", "offer", "rejected", "ghosted", "dismissed")
NEW_STATUS = ("saved", "referred", "applied", "interviewing", "offer", "rejected", "ghosted", "dismissed")
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
)
NEW_TASKS = (*OLD_TASKS, "outreach")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _status_checks(values: tuple[str, ...]) -> list[tuple[str, str, str]]:
    return [
        ("ck_applications_status", "applications", _in("status", values)),
        (
            "ck_applications_previous_status",
            "applications",
            f"previous_status IS NULL OR {_in('previous_status', values)}",
        ),
        ("ck_application_events_to_status", "application_events", _in("to_status", values)),
    ]


def _source_stats(submitted: tuple[str, ...]) -> str:
    return f"""
CREATE OR REPLACE VIEW v_source_stats AS
SELECT
    src.site_id,
    count(DISTINCT src.job_id) AS found,
    count(DISTINCT src.job_id) FILTER (WHERE rj.outcome = 'kept') AS kept,
    count(DISTINCT src.job_id) FILTER (WHERE {_in("a.status", submitted)})
        AS applied,
    count(DISTINCT src.job_id) FILTER (WHERE a.status IN ('interviewing', 'offer')) AS interviews
FROM job_sources src
LEFT JOIN search_run_jobs rj ON rj.job_id = src.job_id
LEFT JOIN applications a ON a.job_id = src.job_id
GROUP BY src.site_id
"""


def _replace_check(name: str, table: str, sql: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, sql)


def upgrade() -> None:
    for name, table, sql in _status_checks(NEW_STATUS):
        _replace_check(name, table, sql)
    _replace_check("ck_task_routes_task", "task_routes", _in("task", NEW_TASKS))
    _replace_check("ck_integrations_kind", "integrations", _in("kind", ("tavily", "searxng", "hunter")))
    op.execute(_source_stats(("referred", "applied", "interviewing", "offer", "rejected", "ghosted")))

    op.create_table(
        "contacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("email_source", sa.Text(), nullable=True),
        sa.Column("email_confidence", sa.SmallInteger(), nullable=True),
        sa.Column("found_via", sa.Text(), nullable=False),
        sa.Column("role_kind", sa.Text(), server_default="other", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            _in("role_kind", ("engineer", "eng_manager", "recruiter", "other")), name="ck_contacts_role_kind"
        ),
        sa.CheckConstraint(_in("found_via", ("web_search", "hunter", "user")), name="ck_contacts_found_via"),
        sa.CheckConstraint(
            f"email_source IS NULL OR {_in('email_source', ('hunter', 'user'))}", name="ck_contacts_email_source"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])
    op.create_index(
        "uq_contacts_linkedin_url",
        "contacts",
        ["linkedin_url"],
        unique=True,
        postgresql_where=sa.text("linkedin_url IS NOT NULL"),
    )
    op.create_table(
        "outreach_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("style", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("material_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("direction", ("out", "in")), name="ck_outreach_messages_direction"),
        sa.CheckConstraint(
            _in("channel", ("connect_note", "inmail", "linkedin_message", "email")), name="ck_outreach_messages_channel"
        ),
        sa.CheckConstraint(
            f"style IS NULL OR {_in('style', ('technical', 'general'))}", name="ck_outreach_messages_style"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_messages_contact_sent", "outreach_messages", ["contact_id", "sent_at"])
    op.create_index("ix_outreach_messages_job_id", "outreach_messages", ["job_id"])


def downgrade() -> None:
    op.drop_table("outreach_messages")
    op.drop_table("contacts")
    op.execute("DELETE FROM integrations WHERE kind = 'hunter'")
    op.execute("DELETE FROM task_routes WHERE task = 'outreach'")
    op.execute("UPDATE applications SET status = 'saved' WHERE status = 'referred'")
    op.execute("UPDATE applications SET previous_status = 'saved' WHERE previous_status = 'referred'")
    op.execute("UPDATE application_events SET to_status = 'saved' WHERE to_status = 'referred'")
    op.execute(_source_stats(OLD_STATUS[1:6]))
    _replace_check("ck_integrations_kind", "integrations", _in("kind", ("tavily", "searxng")))
    _replace_check("ck_task_routes_task", "task_routes", _in("task", OLD_TASKS))
    for name, table, sql in _status_checks(OLD_STATUS):
        _replace_check(name, table, sql)
