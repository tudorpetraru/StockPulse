# Changelog

All notable changes to this project are documented in this file.

## 2026-02-14

### Added

- Added a "Captured Prediction Records" table in the ticker Predictions tab to show stored snapshot fields (snapshot date, firm, action, rating, target, implied return, resolve date, status, source).
- Added Screener classification filters for `Sector` and `Industry`, including dynamic `GET /api/screener/industries` loading with sector-scoped in-memory caching.
- Added CSV export controls in the ticker Predictions tab for both:
  - Analyst Scorecard table.
  - Captured Prediction Records table.
- Added symbol-scoped manual snapshot endpoint `POST /api/predictions/{symbol}/snapshot/run`.

### Changed

- Updated prediction history payloads to include normalized `snapshot_date` and `source` fields for UI/table rendering.
- Updated Screener toolbar control styling/alignment for preset select/actions and switched screener execution to explicit `Screen` submit only (no implicit auto-submit on input change).
- Updated ticker Predictions cold-start UX to:
  - Show scheduled snapshot cadence (`Mon-Fri at 6:00 PM ET` from config).
  - Auto-trigger a one-time per-session on-load snapshot when no prediction records are present for the active symbol.

### Fixed

- Fixed `/api/chart/{symbol}/consensus` period handling so `1Y`, `2Y`, and `All` return distinct data windows rather than the same range.
- Fixed prediction snapshot ingestion for duplicate firm rows in the same run by de-duplicating per firm before DB upsert, preventing unique-key insert failures.
- Fixed Screener filter mapping to propagate `sector` and `industry` values to Finviz query options.
- Fixed a sticky-empty Screener cache failure mode by bypassing cached empty result sets and retrying upstream screener fetches before surfacing an error.

### Tests

- Added ticker-router regression coverage for:
  - Predictions partial rendering of the "Captured Prediction Records" table.
  - Consensus chart period filtering behavior (`1Y` vs `All`) and upstream yfinance period selection.
- Added prediction-pipeline regression coverage for duplicate-firm snapshot ingestion to ensure one upserted row per firm/date/ticker.
- Added Screener router regressions for sector/industry filter forwarding and industry endpoint behavior.
- Added data-service regressions for sector/industry option mapping, empty-cache refetch behavior, and provider-error propagation in screener queries.
- Targeted suites passing:
  - `pytest -q tests/routers/test_ticker.py tests/services/test_prediction_pipeline.py`
  - `pytest -q tests/routers/test_screener.py tests/services/test_data_service.py`

## 2026-02-13

### Added

- Portfolio chart APIs:
  - `GET /api/chart/portfolio/{portfolio_id}/sector`
  - `GET /api/chart/portfolio/{portfolio_id}/positions`
- Render-time quote hydration for portfolio and watchlist table rows.
- Manual refresh wiring for portfolio/watchlist tables with `refresh=1` support.
- Sorting query support on HTMX table endpoints:
  - `GET /hx/portfolio/table`
  - `GET /hx/watchlist/table/{watchlist_id}`
- Regression test module `tests/services/test_data_service.py`.

### Changed

- Reworked ticker tab controls and keyboard interactions to use semantic tab elements and `data-action` hooks.
- Switched Alpine include to CSP-safe build (`@alpinejs/csp`).
- Updated portfolio/watchlist templates to use live quote fields, sortable headers, and last-refreshed metadata.
- Added portfolio chart rendering in the portfolio screen using Plotly JSON endpoints.
- Updated custom CSS with accessibility and UI-alignment class styles used by the revised templates.
- Updated holders tables to show clearer filing semantics (`% In` of AAPL shares, filing-to-filing change, and AAPL position value).
- Removed the derived "share of displayed holders" column to avoid misrepresenting fund-level portfolio weight.

### Fixed

- Fixed ticker financials partial crash (`/hx/ticker/{symbol}/financials`) caused by iterating `row.values` method instead of row payload values.
- Fixed CSP/Alpine eval-related console breakage on ticker/portfolio/watchlist pages.
- Fixed news normalization for provider key variants (`Title`, `Link`, `Source`) and dict-shaped source payloads.
- Fixed Python 3.11 Google News compatibility (`base64.decodestring` fallback).
- Fixed ticker shortcut handling (`1-7`, `R`, `W`) and tab selector mismatch.
- Fixed market cap formatting and near-zero sign rendering in screener/peer outputs.
- Fixed NaN handling in numeric parsing paths to avoid `nan`/`$nan` rendering in earnings/metrics.
- Fixed screener preset load mismatch (`id` string/number comparison).
- Fixed invalid non-symbol ticker link rendering in generic news feed results.
- Fixed Finviz analyst parsing for current columns (`Outer`, `Status`, `Price`) including price-target extraction from range strings.
- Fixed prediction-tab consensus target mismatch by aligning displayed consensus with ticker overview analyst average.
- Fixed holders percent scaling by treating provider `pctHeld` as ratio input and converting to percentage display.
- Fixed financials tab value rendering for both annual and quarterly views by mapping timestamp-based raw columns correctly (eliminating false all-`N/A` rows).
- Stopped tracking SQLite runtime sidecar files (`data/*.db-wal`, `data/*.db-shm`) and added ignore rules to keep local portfolio data artifacts private.

### Tests

- Added ticker financials regression test for populated rows rendering.
- Added news normalization regressions for title/source mapping and invalid ticker link suppression.
- Added portfolio/watchlist refresh regressions validating refresh-path quote updates.
- Added data-service regressions for title/link/source normalization, near-zero clipping, market-cap formatting, and NaN handling.
- Added regressions for Finviz analyst-price parsing, prediction-summary consensus fallback, and holders percent normalization.
- Added regression coverage for timestamp-based financial column mapping (annual + quarterly) and holders filing change normalization.
- Full suite passing: `103 passed` (`pytest -q`).
