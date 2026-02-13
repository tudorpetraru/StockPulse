# StockPulse Implementation Plan (3 Parallel Agents)

Last updated: 2026-02-13
Sources analyzed:
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_PRD_v1.docx
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_Architecture_v1.docx
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_IA_and_Flows.html
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_Design_System.html
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_Wireframes.html
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_Prediction_Tracking_Addendum.docx
- /Users/tudor/Documents/AI/fintech/StockPulse/Specs/StockPulse_Predictions_Wireframe.html

## 1) Scope Lock (v1)

Build P0 features first, then P1 where time allows:
- P0 pages: Dashboard, Screener, Ticker, Portfolio, Watchlist, News.
- P0 infra: SQLite (WAL), disk cache, provider abstraction, graceful partial failures, background refresh jobs.
- P0 prediction pipeline (addendum): snapshot + evaluate + recompute jobs and DB tables.
- P0 prediction UI: Predictions tab on ticker with summary, consensus chart, analyst scorecard.

Defer to later unless ahead of schedule:
- P2 features (dividend tracker, read markers, backfill seed, manual snapshot trigger UI).
- Mobile polish beyond minimum 1024+ usability.

## 2) Architecture Decisions (to unblock execution)

- Python: 3.11.
- Web: FastAPI + Jinja2 templates + HTMX + Alpine.js + Plotly.js.
- ORM/migrations: SQLAlchemy 2 + Alembic.
- Caching: diskcache with TTLs from architecture spec.
- Scheduler: APScheduler in-process with ET market-hour checks.
- App shape: monolith, one process, router/service/provider layering.

## 3) Delivery Phases (compressed with 3 agents)

### Phase 0 (Day 1)
- Project scaffold, dependencies, config, logging, app startup, base template.
- DB models + Alembic baseline migration.
- Provider interfaces and stubs.
- CI basics (lint, format, tests).

### Phase 1 (Days 2-4)
- Core P0 pages + APIs: ticker overview/financials/news/insiders, portfolio CRUD + table, watchlist CRUD + table, news feed.
- Data service orchestration + cache + fallback + error flags.
- HTMX partials for ticker tabs and tables.

### Phase 2 (Days 5-6)
- Screener P0: filters, sort, paginate, click-through, CSV export.
- Scheduler jobs for portfolio/watchlist refresh.
- Prediction backend pipeline: schema + jobs + score computation + prediction APIs.

### Phase 3 (Days 7-8)
- Predictions tab (ticker), consensus chart API, analyst scorecard table.
- Global analyst leaderboard page and dashboard widget.
- Hardening: retries, stale-data indicators, integration tests, bug fixes.

## 4) Shared Contracts (all agents must follow)

- File layout (target):
`/Users/tudor/Documents/AI/fintech/StockPulse/app/main.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/config.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/database.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/routers/*.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/services/*.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/services/providers/*.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/models/db_models.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/models/schemas.py`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/templates/*.html`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/templates/partials/*.html`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/static/css/custom.css`
`/Users/tudor/Documents/AI/fintech/StockPulse/app/static/js/app.js`

- TTLs (must match spec):
price=5m, metrics=15m, financials=1h, analyst=1h, news=10m, screener=15m, insiders=1h, profile=6h, holders=6h.

- Error model:
Service returns per-panel status flags (`ok|error|stale`) and optional message.
Templates render panel-level fallback, never whole-page failure.

- Route contracts (must exist):
`/`, `/screener`, `/ticker/{symbol}`, `/portfolio`, `/watchlist`, `/news`
`/hx/ticker/{symbol}/{financials|analysts|news|insiders|holders|earnings|predictions}`
`/hx/screener/results`, `/hx/portfolio/table`, `/hx/watchlist/table/{id}`, `/hx/news/feed`
JSON APIs from architecture/addendum for charts, CRUD, search, export, predictions.

- Prediction scoring constants:
success threshold = `abs(error) < 0.10`, minimum resolved predictions = 5, composite = `0.4*success + 0.3*directional + 0.3*(1-abs_error)` clamped 0..1.

## 5) Parallel Work Split (Agent A / B / C)

## Agent A (Platform + Data + Scheduler)

Branch: `codex/agent-a-platform-data`

### TODO
1. Bootstrap project and runtime foundation.
2. Implement config, logging, app lifespan, dependency injection.
3. Implement database layer, WAL mode, SQLAlchemy models, Alembic migrations.
4. Implement cache service (diskcache wrapper with typed keys and TTL map).
5. Implement provider interfaces and first-pass adapters (`yfinance`, `finvizfinance`, `pygooglenews`, optional `tvscreener`).
6. Implement `DataService` orchestration with fallback and panel status flags.
7. Implement scheduler service for:
8. portfolio refresh (15 min, market hours)
9. watchlist refresh (15 min, market hours)
10. prediction snapshot (18:00 ET weekdays)
11. outcome evaluation (18:30 ET weekdays)
12. score recomputation (19:00 ET weekdays)
13. Implement prediction tables and queries:
14. `analyst_snapshots`
15. `consensus_snapshots`
16. `analyst_scores`
17. Implement prediction computation routines and repository methods.
18. Add unit tests for services and scoring formulas.

### Deliverables
- `app/config.py`, `app/database.py`, `app/services/cache_service.py`, `app/services/data_service.py`, `app/services/scheduler_service.py`, `app/services/prediction_service.py`.
- `app/models/db_models.py` and Alembic migrations.
- Provider modules under `app/services/providers/`.
- Test files under `tests/services/` and `tests/models/`.

### Definition of Done
- App boots with `python run.py` and creates DB.
- Scheduler jobs register and run in dry-run mode.
- Prediction job can snapshot at least one ticker end-to-end.
- Tests for scoring and outcome evaluation pass.

## Agent B (Ticker + Screener + Predictions UI/API)

Branch: `codex/agent-b-research-screener`

### TODO
1. Implement routers for ticker and screener pages.
2. Implement ticker page with Overview tab eager-loaded.
3. Implement HTMX partials for financials, analysts, news, insiders, holders, earnings.
4. Implement chart JSON APIs for ticker price and prediction chart.
5. Implement screener form, result query integration, sort, pagination, CSV export.
6. Implement screener preset APIs and UI wiring.
7. Implement prediction APIs:
8. `/api/predictions/{symbol}/analysts`
9. `/api/predictions/{symbol}/consensus-history`
10. `/api/predictions/top-analysts`
11. `/api/predictions/{symbol}/analyst/{firm}`
12. `/api/predictions/snapshot/run`
13. Implement ticker Predictions tab partial (summary, period selector, chart container, analyst scorecard, prediction history feed).
14. Implement analyst leaderboard page (`/analysts`) and sortable table.

### Deliverables
- `app/routers/ticker.py`, `app/routers/screener.py`, `app/routers/predictions.py`.
- `app/templates/ticker.html`, `app/templates/screener.html`, `app/templates/analysts.html`.
- `app/templates/partials/ticker_*.html` including predictions partials.
- `app/services/chart_service.py` updates for price + prediction charts.
- Tests under `tests/routers/ticker_*.py`, `tests/routers/screener_*.py`, `tests/routers/predictions_*.py`.

### Definition of Done
- Ticker page supports lazy tab loading via HTMX.
- Screener returns <10s query times on cached/warm paths.
- Predictions tab shows cold-start state when no resolved outcomes exist.
- Leaderboard page loads and sorts by composite score.

## Agent C (Dashboard + Portfolio + Watchlist + News + Design System Integration)

Branch: `codex/agent-c-portfolio-watchlist-news`

### TODO
1. Implement routers/pages for dashboard, portfolio, watchlist, news.
2. Implement portfolio CRUD APIs and HTMX table refresh workflow.
3. Implement watchlist CRUD APIs, multiple lists, notes, refresh status timestamp.
4. Implement news feed aggregation page with filters (all/portfolio/watchlist/custom).
5. Implement dashboard cards:
6. portfolio summary
7. watchlist movers
8. recent news
9. market snapshot
10. prediction widget (tracking/resolved/top analysts)
11. Implement base layout (`base.html`) with global nav and Ctrl+K search box.
12. Implement CSS tokens and components from design system in `custom.css`.
13. Implement `app.js` shortcuts (Ctrl/Cmd+K, Esc, 1-5 ticker tabs, R, W).
14. Ensure table/accessibility conventions (thead/th, labels, sign prefixes, N/A policy).

### Deliverables
- `app/routers/dashboard.py`, `app/routers/portfolio.py`, `app/routers/watchlist.py`, `app/routers/news.py`.
- `app/templates/dashboard.html`, `app/templates/portfolio.html`, `app/templates/watchlist.html`, `app/templates/news.html`, `app/templates/base.html`.
- `app/templates/partials/portfolio_table.html`, `app/templates/partials/watchlist_table.html`, `app/templates/partials/news_feed.html`.
- `app/static/css/custom.css`, `app/static/js/app.js`.
- Tests under `tests/routers/portfolio_*.py`, `tests/routers/watchlist_*.py`, `tests/routers/news_*.py`, `tests/ui/`.

### Definition of Done
- Portfolio and watchlist CRUD works via HTMX without full reload.
- Dashboard renders all P0 cards and prediction widget.
- News feed supports custom search and basic source/ticker filtering.
- UI matches design-system rules for color coding and formatting.

## 6) Integration Plan

- Day 1 end: merge Agent A foundation first.
- Day 2 morning: Agents B/C rebase onto Agent A.
- Day 4 end: merge B + C into `codex/integration-v1` and run full test suite.
- Day 6 end: merge prediction backend from A + UI from B + widget hooks from C.
- Day 8: stabilization and release-candidate tag.

Conflict-avoidance ownership:
- Agent A owns `app/services/*`, `app/models/*`, migrations.
- Agent B owns ticker/screener/predictions routers and templates.
- Agent C owns dashboard/portfolio/watchlist/news routers, base template, static assets.
- Shared file edits (`app/main.py`, `requirements.txt`, `README.md`) only through small, reviewed PRs.

## 7) Testing Matrix (minimum)

- Unit:
cache TTL behavior, fallback selection, scoring formula, unresolved prediction evaluation.
- Router/API:
status codes, schema shape, pagination/sorting, CSV export content type.
- Integration:
portfolio add/edit/delete -> table refresh -> summary recompute.
screener submit -> results partial -> click ticker.
prediction snapshot -> evaluate -> leaderboard metrics.
- UI smoke:
all main routes return 200 and render key headings.

## 8) Open Questions to Resolve Early

1. `tvscreener` support on Python 3.11 in your local environment.
2. International ticker support in v1 (recommend: US-only first).
3. Final choice for preserving price history locally vs on-demand fetch only.
4. Whether to include `/analysts` in top nav for v1 or keep under ticker only.

## 9) Immediate Kickoff Commands

- Shared environment (run once, then every agent uses it):
`cd /Users/tudor/Documents/AI/fintech/StockPulse`
`PYTHON_BIN=/opt/homebrew/bin/python3.11 ./scripts/bootstrap_env.sh`

- Per agent shell before any work:
`cd /Users/tudor/Documents/AI/fintech/StockPulse`
`source .venv/bin/activate`
`./scripts/check_env.sh`

- Agent A:
`git checkout -b codex/agent-a-platform-data`
- Agent B:
`git checkout -b codex/agent-b-research-screener`
- Agent C:
`git checkout -b codex/agent-c-portfolio-watchlist-news`

Then each agent starts from Section 5 TODO list above and opens PRs against a shared integration branch.
