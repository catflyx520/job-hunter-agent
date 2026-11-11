# job-hunter-agent

Open-source, local-first job hunting assistant. Connect your own model (API key / Ollama / your local Claude Code or Codex CLI), upload your resume and preferences, then paste jobs to get evidence-backed match scores, H-1B / green card employer history, and cover letter / application answer drafts. Automatic job search and application tracking come in later milestones.

[Chinese](README.zh-CN.md) · Spec: [docs/SPEC.md](docs/SPEC.md)

> Status: **M4 (local)** — model connections (incl. one-click CLI login), resume review, automatic job search across the sites you pick (public job pages on LinkedIn, Built In, YC and more, plus the public Greenhouse / Lever / Ashby APIs) → de-duplication, hard exclusions, match scores with resume evidence, H-1B / PERM employer history; paste a job URL / JD; cover letters and application answers (with screenshots); application tracking and a stats page. The app never applies to jobs, fills forms, or contacts employers for you.

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

The CLI providers call *your* `claude` / `codex` as a subprocess and use your own subscription. In **Settings → Connection** you can see the login status and sign in with one click: the app runs the CLI's own login command, shows you the official authorization link, and passes the verification code back to the CLI. Credentials are stored by the CLI; the app never reads or stores tokens. You can still log in from your own terminal instead.

## Job search

On the **Jobs** page, pick sites and a per-site limit, then start a search. Each search is a batch (ID like `2026-11-07-A`) that reports how many jobs each site found and kept, and why any pages could not be read.

- LinkedIn, Indeed, Built In, YC and similar: a web search finds public job pages, then the app reads them. By default this uses the web search built into the model assigned to the "job search" task (the Claude CLI gets the WebSearch tool for this task only). You can switch to [Tavily](https://tavily.com) or a self-hosted [SearXNG](https://docs.searxng.org) under Settings.
- Greenhouse / Lever / Ashby: reads the companies' public job board JSON; no search source needed. Company boards are remembered from job pages you've read, or you can add them by hand.
- Public pages only. The app stops at sign-in, CAPTCHA or verification pages and records why; it never tries to get around them. Without signing in, LinkedIn and Indeed pages are often unreadable — that is expected.
- Each job takes about 20–40 seconds to read, extract and score; jobs hit by a hard exclusion are not scored.

## Application tracking and stats

Mark a job as saved → applied → interviewing → offer / rejected / ghosted (or dismiss it and restore it later). Every change is kept in a history; the "applied" time is the time you marked it — the app never invents submission times or applies for you.

The stats page shows totals, a funnel, reply rate, source sites, sponsorship policy and visa history breakdowns, exclusion reasons, salary and score distributions, daily / weekly trends and a backlog. Filter by company, site, batch, location, status or date, and click any bar to see the jobs behind it.

## H-1B / green card history data

Employer history comes from official public data: DOL LCA and PERM disclosure files, and the USCIS H-1B Employer Data Hub.

```bash
cd backend
uv run python ../scripts/sponsor_data/download.py     # last 3 fiscal years by default
uv run python ../scripts/sponsor_data/build.py        # aggregate and import into the database
```

The official sites usually block scripted downloads (HTTP 403). The tool does not try to get around that: it prints the official URLs so you can download them in your browser. Keep the original file names and put the files in `data/sponsor/raw/`, then run `build.py`. History records never mean a job will sponsor you; each job page shows the JD's own policy separately.

## Tests

```bash
docker compose up -d
cd backend
uv run pytest
uv run ruff check .
```

LLM tests use a fake provider and never call real APIs. API tests use a separate `jobhunter_test` database and are skipped if Postgres isn't reachable.

### Evals

`evals/datasets/cases.py` holds 5 fictional job seekers, 40 labeled job descriptions and 50 company-name pairs (all synthetic).

```bash
cd backend
uv run python ../evals/run_evals.py                                                   # no model calls (also runs in CI)
uv run python ../evals/run_evals.py --suite llm --provider claude_cli --model sonnet  # uses your own model
```

The `llm` suite measures extraction accuracy, hard-exclusion precision / recall, recommendation accuracy, cover letter citation rate, and whether application answers flag what needs your confirmation. Thresholds live in `evals/thresholds.json`; the run exits non-zero when a metric drops below them.

## License

MIT
