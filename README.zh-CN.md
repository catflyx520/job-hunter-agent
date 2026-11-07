# job-hunter-agent

开源、本地运行的求职助手：连接你自己的模型（API key / Ollama / 本机 Claude Code 或 Codex CLI），上传履历与求职需求，贴上职位就能得到引用履历证据的匹配评分、雇主 H-1B / 绿卡历史，以及 cover letter 与申请问答草稿。自动搜索与投递统计在后续里程碑加入。

[English](README.md) · 规格：[docs/SPEC.md](docs/SPEC.md)

> 目前进度：**M3**：模型连接（含 CLI 一键登录）、履历评分、勾选网站自动搜索职位（LinkedIn、Built In、YC 等公开职位页 + Greenhouse / Lever / Ashby 公开 API）→ 去重、硬性排除、引用履历证据的匹配评分、H-1B / PERM 雇主历史；也可贴网址或 JD；cover letter 与申请问答（可附截图）。本 app 不会自动投递、不会自动填表、不会代你联系雇主。

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

## 职位搜索

在「职位搜索」页勾选网站、设定每个网站的上限，按「开始搜索」会产生一个批次（编号如 `2026-11-07-A`），并列出每个网站找到几个、保留几个、读不到的原因。

- LinkedIn、Indeed、Built In、YC 等：先用网页搜索找到公开职位页，再由 app 读取。预设用「职位搜索」任务的模型自带搜索（Claude CLI 只在这个任务开放 WebSearch 工具）；也可以在「模型设置 → 职位搜索来源」改用 [Tavily](https://tavily.com)（搜索 API，有免费额度）或自己架设的 [SearXNG](https://docs.searxng.org)。
- Greenhouse / Lever / Ashby：读取公司职位板的官方公开 JSON，不需要搜索来源。公司 board 会从读过的职位页自动记下，也可以手动加入。
- 只读公开页面，遇到登录、CAPTCHA 或验证页就停下并记录原因，不绕过。不登录则 LinkedIn / Indeed 常常读不到，这是预期的限制。
- 每个职位要读取、抽取并评分，约 20–40 秒；被硬性排除的职位不评分。

## H-1B / 绿卡历史资料

雇主历史来自官方公开资料：美国劳工部 DOL 的 LCA、PERM 公开档，以及 USCIS H-1B Employer Data Hub。

```bash
cd backend
uv run python ../scripts/sponsor_data/download.py     # 预设最近 3 个财年
uv run python ../scripts/sponsor_data/build.py        # 汇总并导入数据库
```

官方网站通常拒绝程序下载（HTTP 403），本工具不会绕过：它会列出官方网址，请用浏览器下载，档名不要改，放进 `data/sponsor/raw/` 后再执行 `build.py`。历史记录不代表职位会提供 sponsorship；职位页会另外显示 JD 自己写的政策。

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
