"""应用设定，全部来自环境变量或 `.env`。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://jobhunter:jobhunter@localhost:5433/jobhunter"
    # Fernet key；用 `uv run python -m app.core.security` 产生
    app_secret_key: str = ""
    data_dir: Path = REPO_DIR / "data"
    embedding_dim: int = 1536

    # 本机 CLI provider
    cli_timeout_seconds: int = 180
    cli_max_concurrency: int = 2

    # 上传限制
    max_resume_bytes: int = 10 * 1024 * 1024

    # 前端打包后的静态档（docker 模式由后端直接提供）
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
