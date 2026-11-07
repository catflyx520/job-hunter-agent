# job-hunter-agent

开源、本地运行的求职助手：连接你自己的模型（API key / Ollama / 本机 Claude Code 或 Codex CLI），上传履历与求职需求，得到透明的履历评分；后续里程碑会加入职位搜索与匹配评分、H-1B / 绿卡历史、cover letter 草稿。

[English](README.md) · 规格：[docs/SPEC.md](docs/SPEC.md)

> 目前进度：**M1**（骨架、模型连接与 CLI 一键登录、履历与需求、履历评分）。本 app 不会自动投递、不会自动填表、不会代你联系雇主。

## 需要安装

- [uv](https://docs.astral.sh/uv/)（会自动装 Python 3.12）
- Node.js 20+ 与 [pnpm](https://pnpm.io/)
- Docker：只用来跑数据库（Postgres 16 + pgvector）

## 启动

```bash
cp .env.example .env
cd backend && uv run python -m app.core.security    # 印出金钥，填进 .env 的 APP_SECRET_KEY
```

```bash
docker compose up -d                                 # 只有数据库，localhost:5433
```

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```bash
cd frontend
pnpm install
pnpm dev                                             # http://localhost:5173
```

后端不在 8000 时，用 `API_PORT=<端口> pnpm dev` 启动前端。

## 本机 Claude Code / Codex CLI

CLI provider 以子进程调用**你自己**的 `claude` / `codex`，使用你的订阅额度。在「模型设置 → 本机 CLI 登录」可以看到登录状态并一键登录：app 执行 CLI 自己的登录指令，把官方授权网址显示给你，授权后的验证码由页面转交给 CLI。凭证由 CLI 自己保存，app 不读取、不保存任何 token。你也可以照旧在终端自己登录。此模式仅供个人本地使用，额度和使用规则以 Anthropic / OpenAI 的条款为准。

## 测试

```bash
docker compose up -d
cd backend
uv run pytest
uv run ruff check .
```

LLM 相关测试一律用假 provider，不打真实 API。API 测试使用独立的 `jobhunter_test` 数据库，连不上 Postgres 时会跳过。

## 授权

MIT
