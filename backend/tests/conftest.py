"""测试设定。

- 纯逻辑测试不需要数据库。
- API 测试需要 Postgres（`docker compose up db`），使用独立的 `jobhunter_test` 数据库；连不上时跳过并说明原因。
- 所有 LLM 呼叫都用 FakeProvider，不打真实 API。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://jobhunter:jobhunter@localhost:5433/jobhunter_test"
)
# 必须在 import app 之前设定（settings 有快取）
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["APP_SECRET_KEY"] = Fernet.generate_key().decode()
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="jha-test-data-")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.llm.fake import FakeProvider  # noqa: E402
from tests.samples import fake_responder  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _ensure_database() -> str | None:
    """建立测试数据库并跑 migration。回传 None 表示成功，否则回传跳过原因。"""
    url = make_url(TEST_DB_URL)
    try:
        admin = create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        )
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database})
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001
        return f"连不上测试数据库（{type(exc).__name__}）。请先执行 `docker compose up -d db`。"

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = TEST_DB_URL
    command.upgrade(cfg, "head")
    return None


_db_skip_reason: str | None | bool = False


@pytest.fixture(scope="session")
def database():
    global _db_skip_reason
    if _db_skip_reason is False:
        _db_skip_reason = _ensure_database()
    if _db_skip_reason:
        pytest.skip(_db_skip_reason)
    from app.core.db import get_engine

    return get_engine()


KEEP_TABLES = {"job_sites"}  # migration 预载的种子资料


def truncate_all(engine) -> None:
    import app.models  # noqa: F401
    from app.core.db import Base

    tables = ", ".join(t for t in Base.metadata.tables if t not in KEEP_TABLES)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        conn.execute(text("UPDATE job_sites SET enabled = false, max_results = 20"))


@pytest.fixture(autouse=True)
def zh_messages():
    """不经过 HTTP 的逻辑测试也用中文（预设是英文）。"""
    from app.core.i18n import _lang, set_lang

    token = set_lang("zh")
    yield
    _lang.reset(token)


# 所有取得 provider 的地方都换成假 provider
PROVIDER_LOOKUPS = (
    "app.api.resumes",
    "app.api.jobs",
    "app.jobs.service",
    "app.materials.service",
    "app.rag.retrieve",
    "app.search.process",
    "app.search.web",
)


@pytest.fixture
def db_session(database):
    from app.core.db import get_sessionmaker

    truncate_all(database)
    with get_sessionmaker()() as s:
        yield s
        s.rollback()


@pytest.fixture
def client(database, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from app.main import create_app

    truncate_all(database)
    fake = FakeProvider(fake_responder, embed_dim=get_settings().embedding_dim)
    fake.kind = "fake"
    for module in PROVIDER_LOOKUPS:
        monkeypatch.setattr(importlib.import_module(module), "provider_for_task", lambda db, task: fake)
    # 既有测试检查中文讯息；英文另有测试（test_i18n.py）
    with TestClient(create_app(), base_url="http://localhost", headers={"X-UI-Lang": "zh"}) as c:
        c.fake = fake  # type: ignore[attr-defined]
        yield c
