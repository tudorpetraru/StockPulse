# StockPulse

Local-first stock research workstation built with FastAPI, server-rendered templates, HTMX interactions, and a SQLite backend.

## Scope

### Implemented in this repository

- Dashboard with:
  - portfolio summary card
  - watchlist movers
  - market snapshot
  - recent news rollup
  - prediction widget (tracking/resolved/accuracy/top analysts)
- Screener with:
  - filter form
  - sorting and pagination
  - preset save/list/delete
  - CSV export
- Ticker research page with:
  - overview
  - financials
  - analyst ratings
  - news
  - insider activity
  - holders
  - earnings
  - predictions tab and chart APIs
- Portfolio management:
  - create/delete portfolios
  - add/update/delete positions
  - HTMX table refresh
- Watchlist management:
  - create/delete watchlists
  - add/update/delete items
  - quick add from ticker
  - HTMX table refresh
- News feed:
  - all / portfolio / watchlist / custom filters
  - paginated HTMX feed endpoint
- Prediction tracking:
  - analyst and consensus snapshots
  - outcome evaluation
  - score recomputation
  - top-analyst leaderboard page
- Background scheduling:
  - market-hours refresh jobs
  - prediction jobs (snapshot/evaluate/recompute)
- Security baseline:
  - CSRF middleware
  - security headers middleware
  - global error sanitization
  - rate limits via SlowAPI

### In scope documents

- Product/design/architecture specs are in `Specs/`.
- Execution plan used by agents is in `IMPLEMENTATION_PLAN.md`.

## Tech Stack and Libraries

### Backend/runtime

- Python 3.11
- FastAPI
- Uvicorn
- Jinja2
- python-multipart

### Data/storage

- SQLAlchemy 2
- Alembic
- SQLite (WAL mode enabled)
- diskcache

### Scheduling and resilience

- APScheduler
- SlowAPI (rate limiting)

### Market/news providers

- yfinance
- finvizfinance
- pygooglenews
- tvscreener (installed; limited usage in current code paths)

### Frontend

- PicoCSS (classless base from CDN)
- HTMX
- Alpine.js
- Plotly.js
- custom CSS/JS in `app/static/`

### Dev tooling

- pytest
- pytest-asyncio
- httpx (tests)
- ruff

## Repository Layout

```text
app/
  main.py
  config.py
  routers/
  services/
  middleware/
  templates/
  static/
alembic/
data/
scripts/
Specs/
tests/
run.py
```

## Setup (Shared venv for all agents)

Use the same project-local virtual environment for all terminals/agents.

```bash
cd <project-root>/StockPulse
PYTHON_BIN=python3.11 ./scripts/bootstrap_env.sh
source .venv/bin/activate
./scripts/check_env.sh
```

If `python3.11` is not available in PATH:

```bash
PYTHON_BIN=python3 ./scripts/bootstrap_env.sh
```

The bootstrap script recreates `.venv` automatically if Python minor version changes.

## Database and Migrations

App startup also creates tables via SQLAlchemy metadata, but schema migrations should still be applied explicitly:

```bash
source .venv/bin/activate
alembic upgrade head
```

Default DB path is `data/stockpulse.db` (configurable via `DB_PATH`).

## Launch the App

```bash
cd <project-root>/StockPulse
source .venv/bin/activate
python run.py
```

Open <http://127.0.0.1:8000>.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Stop the App

If running in the foreground terminal:

- Press `Ctrl+C`

If it was started elsewhere and you need to stop by process match:

```bash
pkill -f "python run.py|uvicorn"
```

## Configuration

Environment variables are loaded from `.env` (if present) and process env:

- `ENVIRONMENT` (default: `development`)  
  - `production` disables auto-reload in `run.py`
- `HOST` (default: `127.0.0.1`)
- `PORT` (default: `8000`)
- `DB_PATH` (default: `data/stockpulse.db`)
- `CACHE_DIR` (default: `data/cache`)
- `CACHE_SIZE_LIMIT` (default: `524288000`)
- `REFRESH_INTERVAL_MIN` (default: `15`)
- `MARKET_TZ` (default: `US/Eastern`)
- `LOG_LEVEL` (default: `INFO`)
- `PREDICTION_SNAPSHOT_HOUR_ET` (default: `18`)
- `PREDICTION_EVALUATION_HOUR_ET` (default: `18`)
- `PREDICTION_EVALUATION_MINUTE_ET` (default: `30`)
- `PREDICTION_RECOMPUTE_HOUR_ET` (default: `19`)
- `PREDICTION_RECOMPUTE_MINUTE_ET` (default: `0`)

## Quality Checks

```bash
source .venv/bin/activate
ruff check app tests
pytest -q
```

## Caveats (Current)

- This is currently a local-first, single-instance app with no auth/login model.
- Background jobs run in-process via APScheduler. If the process is down, jobs do not run.
- Market/news providers are external and can throttle/fail; the app uses fallback and stale-cache behavior, but data completeness is not guaranteed.
- Portfolio and watchlist tables still render several market fields as placeholders (`N/A`) and do not yet show fully live per-row quote analytics.
- CSP currently allows `'unsafe-inline'` for scripts/styles to support existing template patterns; tighten further before internet-facing deployment.
- SQLite WAL sidecar files (`*.db-wal`, `*.db-shm`) are expected during runtime.

## Still To Do

1. Replace portfolio/watchlist placeholder quote columns with live per-row pricing and day-change metrics.
2. Add authentication/authorization and user isolation for multi-user deployments.
3. Move scheduler jobs to a dedicated worker process for production reliability.
4. Add stronger observability (structured request logs, job metrics, provider failure dashboards).
5. Add deployment artifacts (Dockerfile/compose, reverse-proxy guidance, HTTPS/cookie hardening defaults).
6. Expand end-to-end tests for critical UI flows and failure scenarios (provider outages, rate-limit responses, CSRF failures).

## Notes

- Not financial advice.
- `SECURITY_FIXES.md` tracks the hardening work completed in this iteration.
