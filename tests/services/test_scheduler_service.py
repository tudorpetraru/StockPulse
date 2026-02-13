from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.db_models import Portfolio, Position, Watchlist, WatchlistItem
from app.services.scheduler_service import SchedulerService


class StubPredictionService:
    async def run_daily_snapshot(self, db: Session):  # noqa: D401
        return {"ok": 1}

    async def evaluate_expired_predictions(self, db: Session):
        return {"resolved": 0}

    async def recompute_scores(self, db: Session):
        return {"scores_written": 0}


class StubYFinanceProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_current_price(self, ticker: str) -> float:
        self.calls.append(ticker)
        return 100.0


def _seed_tracked_tickers(db_session: Session) -> None:
    portfolio = Portfolio(name="Scheduler Main")
    db_session.add(portfolio)
    db_session.commit()
    db_session.refresh(portfolio)
    db_session.add_all(
        [
            Position(portfolio_id=portfolio.id, ticker="AAPL", shares=10, avg_cost=100.0),
            Position(portfolio_id=portfolio.id, ticker="MSFT", shares=5, avg_cost=200.0),
        ]
    )

    watchlist = Watchlist(name="Scheduler WL")
    db_session.add(watchlist)
    db_session.commit()
    db_session.refresh(watchlist)
    db_session.add_all(
        [
            WatchlistItem(watchlist_id=watchlist.id, ticker="AAPL"),
            WatchlistItem(watchlist_id=watchlist.id, ticker="TSLA"),
        ]
    )
    db_session.commit()


def test_within_market_hours_window() -> None:
    yfinance = StubYFinanceProvider()
    scheduler = SchedulerService(prediction_service=StubPredictionService(), yfinance_provider=yfinance)
    tz = ZoneInfo(get_settings().market_tz)

    assert scheduler._within_market_hours(datetime(2026, 2, 9, 9, 29, tzinfo=tz)) is False
    assert scheduler._within_market_hours(datetime(2026, 2, 9, 9, 30, tzinfo=tz)) is True
    assert scheduler._within_market_hours(datetime(2026, 2, 9, 16, 0, tzinfo=tz)) is True
    assert scheduler._within_market_hours(datetime(2026, 2, 9, 16, 1, tzinfo=tz)) is False
    assert scheduler._within_market_hours(datetime(2026, 2, 8, 12, 0, tzinfo=tz)) is False


@pytest.mark.asyncio
async def test_portfolio_watchlist_refresh_job_skips_outside_market_hours(db_session: Session) -> None:
    yfinance = StubYFinanceProvider()
    scheduler = SchedulerService(prediction_service=StubPredictionService(), yfinance_provider=yfinance)
    scheduler._within_market_hours = lambda now=None: False  # type: ignore[assignment]

    result = await scheduler._portfolio_watchlist_refresh_job(db_session)
    assert result == {"skipped": 1, "reason": "outside_market_hours"}
    assert yfinance.calls == []


@pytest.mark.asyncio
async def test_portfolio_watchlist_refresh_job_refreshes_tracked_prices(db_session: Session) -> None:
    _seed_tracked_tickers(db_session)

    yfinance = StubYFinanceProvider()
    scheduler = SchedulerService(prediction_service=StubPredictionService(), yfinance_provider=yfinance)
    scheduler._within_market_hours = lambda now=None: True  # type: ignore[assignment]

    result = await scheduler._portfolio_watchlist_refresh_job(db_session)

    assert result == {"tickers": 3, "refreshed": 3, "failed": 0}
    assert sorted(yfinance.calls) == ["AAPL", "MSFT", "TSLA"]

