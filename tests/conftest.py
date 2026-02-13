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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.models.db_models import Portfolio, Position, Watchlist, WatchlistItem

# ── Shared in-memory DB for Agent C tests ──

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
_TestSession = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _setup_db():
    """Create tables before each test and drop after."""
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)


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
    test_app.dependency_overrides[get_db] = _override_get_db

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
