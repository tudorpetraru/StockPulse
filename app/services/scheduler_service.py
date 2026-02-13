from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.errors import SERVICE_RECOVERABLE_ERRORS
from app.services.prediction_service import PredictionSnapshotService, refresh_tracked_prices
from app.services.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, prediction_service: PredictionSnapshotService, yfinance_provider: YFinanceProvider) -> None:
        settings = get_settings()
        self._tz = ZoneInfo(settings.market_tz)
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=self._tz)
        self._prediction_service = prediction_service
        self._yfinance_provider = yfinance_provider

    def start(self) -> None:
        if self._scheduler.running:
            return
        self._register_jobs()
        self._scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def _register_jobs(self) -> None:
        self._scheduler.add_job(
            self._wrap_db_job(self._portfolio_watchlist_refresh_job),
            CronTrigger(day_of_week="mon-fri", hour="9-16", minute="*/15", timezone=self._tz),
            id="portfolio_watchlist_refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._wrap_db_job(self._prediction_snapshot_job),
            CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.prediction_snapshot_hour_et,
                minute=0,
                timezone=self._tz,
            ),
            id="prediction_snapshot",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._wrap_db_job(self._prediction_evaluation_job),
            CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.prediction_evaluation_hour_et,
                minute=self._settings.prediction_evaluation_minute_et,
                timezone=self._tz,
            ),
            id="outcome_evaluation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._wrap_db_job(self._prediction_recompute_job),
            CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.prediction_recompute_hour_et,
                minute=self._settings.prediction_recompute_minute_et,
                timezone=self._tz,
            ),
            id="score_recomputation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _wrap_db_job(self, job: Callable[[Session], Awaitable[dict]]) -> Callable[[], Awaitable[None]]:
        async def wrapped() -> None:
            db = SessionLocal()
            try:
                result = await job(db)
                logger.info("Scheduler job %s result=%s", job.__name__, result)
            except SERVICE_RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.exception("Scheduler job %s failed: %s", job.__name__, exc)
            finally:
                db.close()

        return wrapped

    async def _portfolio_watchlist_refresh_job(self, db: Session) -> dict:
        if not self._within_market_hours():
            return {"skipped": 1, "reason": "outside_market_hours"}
        return await refresh_tracked_prices(db, self._yfinance_provider)

    async def _prediction_snapshot_job(self, db: Session) -> dict:
        return await self._prediction_service.run_daily_snapshot(db)

    async def _prediction_evaluation_job(self, db: Session) -> dict:
        return await self._prediction_service.evaluate_expired_predictions(db)

    async def _prediction_recompute_job(self, db: Session) -> dict:
        return await self._prediction_service.recompute_scores(db)

    def _within_market_hours(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(self._tz)
        if now.weekday() >= 5:
            return False
        if now.hour < 9 or now.hour > 16:
            return False
        if now.hour == 9 and now.minute < 30:
            return False
        if now.hour == 16 and now.minute > 0:
            return False
        return True
