"""Shared test conftest — supports both Agent B and Agent C routers.

Agent B routers (ticker, screener, predictions) don't use DB.
Agent C routers (dashboard, portfolio, watchlist, news) require DB.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.middleware.rate_limit import limiter
from app.models.db_models import Portfolio, Position, Watchlist, WatchlistItem

# ── Shared in-memory DB for Agent C tests ──
# StaticPool ensures every session uses the same underlying connection,
# so all sessions see the same tables and data.

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _setup_db():
    """Create tables before each test and drop after."""
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    limiter.reset()


@pytest.fixture()
def db_session():
    session = _TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _override_get_db():
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


class _TestDataService:
    async def get_profile(self, symbol: str):
        return {
            "name": symbol,
            "symbol": symbol,
            "sector": "Technology",
            "industry": "Software",
            "exchange": "NASDAQ",
            "description": "",
        }

    async def get_price(self, symbol: str):
        return {"price": 100.0, "change": 1.0, "change_pct": 1.0, "updated": "now"}

    async def get_metrics(self, symbol: str):
        return {
            "pe": "20",
            "fwd_pe": "18",
            "peg": "1.5",
            "mkt_cap": "100B",
            "ev_ebitda": "12",
            "beta": "1.1",
            "ps": "4.5",
            "pb": "6.0",
            "roe": "12%",
            "profit_margin": "20%",
            "debt_equity": "0.3",
            "insider_own": "2%",
        }

    async def get_analyst_ratings(self, symbol: str):
        return {"consensus": "Buy", "count": 0, "low": "N/A", "avg": "N/A", "high": "N/A", "ratings": []}

    async def get_financials(self, symbol: str, period: str = "annual"):
        return {"columns": [], "income": [], "balance": [], "cashflow": []}

    async def get_news(self, symbol: str, limit: int = 20):
        return [
            {
                "title": f"{symbol} headline",
                "source": "Test Source",
                "date": "2026-02-13",
                "time_ago": "1h ago",
                "link": "https://example.com/news",
                "ticker": symbol,
            }
        ][:limit]

    async def get_insider_trades(self, symbol: str):
        return []

    async def get_holders(self, symbol: str):
        return {"institutional": [], "mutual_fund": []}

    async def get_earnings(self, symbol: str):
        return {"history": [], "next_date": "N/A"}

    async def get_price_history(self, symbol: str, period: str = "1y"):
        return [
            {"date": "2026-02-12", "close": 99.0, "open": 98.0, "high": 100.0, "low": 97.0, "volume": 1000},
            {"date": "2026-02-13", "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 1200},
        ]

    async def get_peers(self, symbol: str):
        return []

    async def screen_stocks(self, filters):  # noqa: D401
        return []


class _TestPredictionService:
    async def get_analyst_scorecard(self, symbol: str):
        return []

    async def get_consensus_history(self, symbol: str):
        return []

    async def get_top_analysts(self, *, sector: str | None = None, symbol: str | None = None):
        return []

    async def get_firm_history(self, symbol: str, firm: str):
        return []

    async def run_snapshot(self):
        return {"status": "ok", "snapshots_created": 0}

    async def get_prediction_summary(self, symbol: str):
        return {"active": 0, "resolved": 0, "accuracy": None, "consensus_target": "N/A"}

    async def get_prediction_history(self, symbol: str):
        return []


def _mount_static(app: FastAPI) -> None:
    static_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Agent C test client (with DB) ──


@pytest.fixture()
def client():
    """Test client with Agent B + Agent C routers + DB override."""
    from app.routers.dashboard import router as dashboard_router
    from app.routers.news import router as news_router
    from app.routers.portfolio import router as portfolio_router
    from app.routers.predictions import router as predictions_router
    from app.routers.screener import router as screener_router
    from app.routers.ticker import router as ticker_router
    from app.routers.watchlist import router as watchlist_router

    test_app = FastAPI()
    _mount_static(test_app)
    # Agent B routers
    test_app.include_router(ticker_router)
    test_app.include_router(screener_router)
    test_app.include_router(predictions_router)
    # Agent C routers
    test_app.include_router(dashboard_router)
    test_app.include_router(portfolio_router)
    test_app.include_router(watchlist_router)
    test_app.include_router(news_router)
    test_app.add_middleware(SlowAPIMiddleware)
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.state.data_service = _TestDataService()
    test_app.state.prediction_service = _TestPredictionService()

    with TestClient(test_app) as c:
        yield c



# ── Sample data fixtures ──


@pytest.fixture()
def sample_portfolio(db_session: Session) -> Portfolio:
    portfolio = Portfolio(name="Test Portfolio")
    db_session.add(portfolio)
    db_session.commit()
    db_session.refresh(portfolio)
    positions = [
        Position(portfolio_id=portfolio.id, ticker="AAPL", shares=100, avg_cost=150.0),
        Position(portfolio_id=portfolio.id, ticker="NVDA", shares=50, avg_cost=120.0),
        Position(portfolio_id=portfolio.id, ticker="MSFT", shares=30, avg_cost=400.0),
    ]
    db_session.add_all(positions)
    db_session.commit()
    return portfolio


@pytest.fixture()
def sample_watchlist(db_session: Session) -> Watchlist:
    wl = Watchlist(name="Tech Growth")
    db_session.add(wl)
    db_session.commit()
    db_session.refresh(wl)
    items = [
        WatchlistItem(watchlist_id=wl.id, ticker="TSLA", notes="Buy below $250"),
        WatchlistItem(watchlist_id=wl.id, ticker="PLTR"),
        WatchlistItem(watchlist_id=wl.id, ticker="SNOW", notes="Cloud data play"),
    ]
    db_session.add_all(items)
    db_session.commit()
    return wl
