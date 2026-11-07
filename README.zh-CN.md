# job-hunter-agent

开源、本地运行的求职助手：连接你自己的模型（API key / Ollama / 本机 Claude Code 或 Codex CLI），上传履历与求职需求，得到透明的履历评分；后续里程碑会加入职位搜索与匹配评分、H-1B / 绿卡历史、cover letter 草稿。

[English](README.md) · 规格：[docs/SPEC.md](docs/SPEC.md)

> 目前进度：**M1**（骨架、模型连接、履历与需求、履历评分）。本 app 不会自动投递、不会自动填表、不会代你联系雇主。

## 快速启动（Docker，适用 API key / Ollama）

```bash
cp .env.example .env
# 在 APP_SECRET_KEY 填入 Fernet 金钥（用来加密保存 API key）：
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build
```

打开 http://localhost:8000。

## 原生模式（使用本机 Claude Code / Codex CLI 时需要）

CLI provider 以子进程调用**你自己**的 `claude` / `codex`，使用你的登录与订阅额度。docker 容器里没有这些 CLI，所以后端要直接跑在本机：

```bash
cp .env.example .env            # 填 APP_SECRET_KEY
docker compose up -d db         # Postgres + pgvector，localhost:5433
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```bash
cd frontend
pnpm install
pnpm dev                        # http://localhost:5173
```

app 不读取、不保存任何 CLI 凭证；请在自己的终端登录 CLI。此模式使用你自己的订阅额度，仅供个人本地使用，额度和使用规则以 Anthropic / OpenAI 的条款为准。

## 测试

```bash
docker compose up -d db
cd backend
uv run pytest
uv run ruff check .
```

LLM 相关测试一律用假 provider，不打真实 API。API 测试使用独立的 `jobhunter_test` 数据库，连不上 Postgres 时会跳过。

## 授权

MIT
