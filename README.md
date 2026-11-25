# Job Hunter Agent

[![CI](https://github.com/catflyx520/job-hunter-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/catflyx520/job-hunter-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A local-first job search assistant. It finds job postings, scores each one against your resume, and drafts cover letters that use only facts from that resume. You bring your own model: an API key, Ollama, or your local Claude Code or Codex CLI.

**[Live demo](https://catfly.dev/job-hunter/)** · [Case study](https://catfly.dev/projects/job-hunter-agent/) · [Full guide](docs/GUIDE.md) · [Chinese](README.zh-CN.md)

**Stack:** Python · FastAPI · LangGraph · PostgreSQL + pgvector · React · TypeScript

## What it does

- **Job search.** Searches the sites you pick (LinkedIn, Indeed, Built In, YC, and Greenhouse / Lever / Ashby boards), removes duplicates and applies your hard exclusions.
- **Match scores.** Scores each job against your resume and shows the resume evidence behind each score.
- **Sponsorship history.** Shows each employer's H-1B / green card history from public DOL and USCIS data.
- **Drafts.** Writes cover letters, application answers and referral requests. A sentence with no resume evidence is flagged for you to confirm.
- **Tracking.** Follows each application from saved to offer, with a stats page.

The app never applies to jobs, fills forms, or contacts employers for you.

## How it works

Three LangGraph workflows run the model steps: job search (one discovery step per site, in parallel), drafting (retrieve evidence → generate → verify citations) and resume review. Resume evidence is retrieved with pgvector similarity and PostgreSQL full-text search, merged with reciprocal rank fusion.

## Eval results

40 labeled synthetic job posts, run with Claude Sonnet:

| Metric | Result |
| --- | --- |
| Job field extraction (7 fields per job) | 100% (280 of 280 checks) |
| Apply / maybe / skip decision matches the label | 87.5% (35 of 40) |

## Run

You need [uv](https://docs.astral.sh/uv/), Node.js 20+ with [pnpm](https://pnpm.io/), and Docker (for the database only).

```bash
cp .env.example .env
docker compose up -d                                 # database only, on localhost:5433
cd backend
uv run python -m app.core.security                   # prints a key; put it in .env as APP_SECRET_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
pnpm install
pnpm dev                                             # http://localhost:5173
```

## Tests

```bash
cd backend
uv run pytest
uv run python ../evals/run_evals.py                  # evals with no model calls (also runs in CI)
```

## License

MIT
