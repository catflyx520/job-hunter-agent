# Job Hunter Agent

[![CI](https://github.com/catflyx520/job-hunter-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/catflyx520/job-hunter-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

本地运行的求职助手：帮你找职位，按你的履历给每个职位评分，并且只用履历里的事实起草 cover letter。模型用你自己的：API key、Ollama，或本机的 Claude Code / Codex CLI。

**[在线 Demo](https://catfly.dev/job-hunter/)** · [案例说明](https://catfly.dev/projects/job-hunter-agent/) · [完整说明](docs/GUIDE.zh-CN.md) · [英文版](README.md)

**技术栈：** Python · FastAPI · LangGraph · PostgreSQL + pgvector · React · TypeScript

## 功能

- **职位搜索**：在你选的网站上搜索（LinkedIn、Indeed、Built In、YC，以及 Greenhouse / Lever / Ashby 的职位板），去重并套用你的硬性排除条件。
- **匹配评分**：按履历给每个职位评分，并列出评分依据的履历证据。
- **担保历史**：用 DOL 和 USCIS 的公开资料显示雇主的 H-1B / 绿卡历史。
- **草稿**：起草 cover letter、申请问答和内推请求。没有履历证据的句子会标出来请你确认。
- **投递追踪**：从收藏到 offer 记录每个申请的进度，并有统计页。

这个应用不会替你投递、填表或联系雇主。

## 运作方式

模型相关的步骤由三个 LangGraph 工作流执行：职位搜索（每个网站一个发现步骤，并行执行）、草稿（检索证据 → 生成 → 核对引用）和履历检查。履历证据用 pgvector 相似度加 PostgreSQL 全文检索取回，再用 RRF（Reciprocal Rank Fusion）合并。

## 评测结果

40 份标注好的合成 JD，用 Claude Sonnet 跑：

| 指标 | 结果 |
| --- | --- |
| 职位字段抽取（每份 JD 7 个字段） | 100%（280 项检查全部正确） |
| 投递 / 再考虑 / 跳过的建议与标注一致 | 87.5%（40 份中 35 份） |

## 启动

需要 [uv](https://docs.astral.sh/uv/)、Node.js 20+ 和 [pnpm](https://pnpm.io/)，以及 Docker（只用来跑数据库）。

```bash
cp .env.example .env
docker compose up -d                                 # 只启动数据库，在 localhost:5433
cd backend
uv run python -m app.core.security                   # 会印出一个密钥，填进 .env 的 APP_SECRET_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```bash
cd frontend
pnpm install
pnpm dev                                             # http://localhost:5173
```

## 测试

```bash
cd backend
uv run pytest
uv run python ../evals/run_evals.py                  # 不呼叫模型的 evals（CI 也跑）
```

## 授权

MIT
