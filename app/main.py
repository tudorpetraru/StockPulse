from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, engine
from app.routers import (
    dashboard_router,
    news_router,
    portfolio_router,
    predictions_router,
    screener_router,
    ticker_router,
    watchlist_router,
)
from app.services.cache_service import CacheService
from app.services.data_service import DataService
from app.services.prediction_service import PredictionService, PredictionSnapshotService
from app.services.providers.googlenews_provider import GoogleNewsProvider
from app.services.providers.finviz_provider import FinvizProvider
from app.services.providers.yfinance_provider import YFinanceProvider
from app.services.scheduler_service import SchedulerService


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    Base.metadata.create_all(bind=engine)

    cache = CacheService()
    yfinance_provider = YFinanceProvider()
    finviz_provider = FinvizProvider()
    googlenews_provider = GoogleNewsProvider()
    data_service = DataService(cache=cache, yfinance_provider=yfinance_provider, finviz_provider=finviz_provider)
    prediction_snapshot_service = PredictionSnapshotService(
        yfinance_provider=yfinance_provider,
        finviz_provider=finviz_provider,
    )
    prediction_service = PredictionService(snapshot_service=prediction_snapshot_service)
    scheduler = SchedulerService(prediction_service=prediction_snapshot_service, yfinance_provider=yfinance_provider)

    app.state.cache = cache
    app.state.providers = {
        "yfinance": yfinance_provider,
        "finviz": finviz_provider,
        "googlenews": googlenews_provider,
    }
    app.state.data_service = data_service
    app.state.prediction_service = prediction_service
    app.state.prediction_snapshot_service = prediction_snapshot_service
    app.state.scheduler = scheduler

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        cache.close()


app = FastAPI(title="StockPulse", version="1.0.0", lifespan=lifespan)

# Static files (CSS, JS) — Agent C
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard_router)
app.include_router(screener_router)
app.include_router(ticker_router)
app.include_router(predictions_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(news_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
