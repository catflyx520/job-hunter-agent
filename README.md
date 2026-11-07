# job-hunter-agent

Open-source, local-first job hunting assistant. Connect your own model (API key / Ollama / your local Claude Code or Codex CLI), upload your resume and preferences, get transparent resume reviews — and, in later milestones, job search with match scores, H-1B / green card history, and cover letter drafts.

[中文说明](README.zh-CN.md) · Spec: [docs/SPEC.md](docs/SPEC.md)

> Status: **M1** (skeleton, model connections incl. one-click CLI login, resume & preferences, resume review). The app never applies to jobs, fills forms, or contacts employers for you.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- Node.js 20+ and [pnpm](https://pnpm.io/)
- Docker — only for the database (Postgres 16 + pgvector)

## Run

```bash
cp .env.example .env
cd backend && uv run python -m app.core.security    # prints a key; put it in .env as APP_SECRET_KEY
```

```bash
docker compose up -d                                 # database only, on localhost:5433
```

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
pnpm install
pnpm dev                                             # http://localhost:5173
```

If the backend runs on another port, start the frontend with `API_PORT=<port> pnpm dev`.

## Local Claude Code / Codex CLI

The CLI providers call *your* `claude` / `codex` as a subprocess and use your own subscription. In **Settings → 本机 CLI 登录** you can see the login status and sign in with one click: the app runs the CLI's own login command, shows you the official authorization link, and passes the verification code back to the CLI. Credentials are stored by the CLI; the app never reads or stores tokens. You can still log in from your own terminal instead.

## Tests

```bash
docker compose up -d
cd backend
uv run pytest
uv run ruff check .
```

LLM tests use a fake provider and never call real APIs. API tests use a separate `jobhunter_test` database and are skipped if Postgres isn't reachable.

## License

MIT
