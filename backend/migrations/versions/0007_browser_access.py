"""logged-in browser search (LinkedIn)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 12:00:00

- job_sites.access_method 加 browser（用户自己登录的浏览器窗口，只读职位）
- integration 加 browser（功能开关，不存任何秘密）
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACCESS = ("web_search", "ats_api", "paste_only")
OLD_KINDS = ("tavily", "searxng", "hunter", "gmail")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _replace_check(name: str, table: str, sql: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, sql)


def upgrade() -> None:
    _replace_check("ck_job_sites_access", "job_sites", _in("access_method", (*OLD_ACCESS, "browser")))
    _replace_check("ck_integrations_kind", "integrations", _in("kind", (*OLD_KINDS, "browser")))


def downgrade() -> None:
    op.execute("UPDATE job_sites SET access_method = 'web_search' WHERE access_method = 'browser'")
    op.execute("DELETE FROM integrations WHERE kind = 'browser'")
    _replace_check("ck_integrations_kind", "integrations", _in("kind", OLD_KINDS))
    _replace_check("ck_job_sites_access", "job_sites", _in("access_method", OLD_ACCESS))
