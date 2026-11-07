# job-hunter-agent

Open-source, local-first job hunting assistant. Connect your own model (API key / Ollama / your local Claude Code or Codex CLI), upload your resume and preferences, get transparent resume reviews — and, in later milestones, job search with match scores, H-1B / green card history, and cover letter drafts.

[中文说明](README.zh-CN.md) · Spec: [docs/SPEC.md](docs/SPEC.md)

> Status: **M1** (skeleton, model connections, resume & preferences, resume review). The app never applies to jobs, fills forms, or contacts employers for you.

## Quick start (Docker — API key / Ollama)

```bash
cp .env.example .env
# put a Fernet key in APP_SECRET_KEY (used to encrypt API keys at rest):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build
```

Open http://localhost:8000.

## Native mode (needed for local Claude Code / Codex CLI)

The CLI providers call *your* `claude` / `codex` as a subprocess, using your own login. Docker containers don't have them, so run the backend on the host:

```bash
cp .env.example .env            # fill APP_SECRET_KEY
docker compose up -d db         # Postgres + pgvector on localhost:5433
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
pnpm install
pnpm dev                        # http://localhost:5173
```

The app never reads or stores your CLI credentials; log in to the CLI in your own terminal.

## Tests

```bash
docker compose up -d db
cd backend
uv run pytest
uv run ruff check .
```

LLM tests use a fake provider and never call real APIs. API tests use a separate `jobhunter_test` database and are skipped if Postgres isn't reachable.

## License

MIT
