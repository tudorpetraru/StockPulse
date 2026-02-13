from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.models.schemas import DataPanelResult, PartialDataResult
from app.services.cache_service import CacheService, ttl_for
from app.services.providers.base import DataProviderError
from app.services.providers.finviz_provider import FinvizProvider
from app.services.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


class DataService:
    def __init__(
        self,
        cache: CacheService,
        yfinance_provider: YFinanceProvider,
        finviz_provider: FinvizProvider,
    ) -> None:
        self.cache = cache
        self.yfinance = yfinance_provider
        self.finviz = finviz_provider

    async def _run_with_retry(self, call: Callable[[], Awaitable[Any]], retries: int = 4) -> Any:
        delay = 1
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                return await call()
            except DataProviderError as exc:
                last_error = exc
                await asyncio.sleep(delay)
                delay *= 2
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected retry failure")

    async def _panel(
        self,
        *,
        cache_key: str,
        cache_category: str,
        primary: Callable[[], Awaitable[Any]],
        fallback: Callable[[], Awaitable[Any]] | None = None,
        bypass_cache: bool = False,
    ) -> DataPanelResult:
        if not bypass_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return DataPanelResult(status="ok", data=cached)

        try:
            data = await self._run_with_retry(primary)
            self.cache.set(cache_key, data, ttl_for(cache_category))
            return DataPanelResult(status="ok", data=data)
        except Exception as primary_exc:  # noqa: BLE001
            logger.warning("Primary provider failed for %s: %s", cache_key, primary_exc)
            if fallback is not None:
                try:
                    data = await self._run_with_retry(fallback)
                    self.cache.set(cache_key, data, ttl_for(cache_category))
                    return DataPanelResult(status="stale", data=data, message="Using fallback provider")
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning("Fallback provider failed for %s: %s", cache_key, fallback_exc)
            stale = self.cache.get(cache_key)
            if stale is not None:
                return DataPanelResult(status="stale", data=stale, message="Using stale cache due to provider errors")
            return DataPanelResult(status="error", message=str(primary_exc))

    async def get_ticker_snapshot(self, symbol: str, bypass_cache: bool = False) -> PartialDataResult:
        upper_symbol = symbol.upper()

        profile_key = self.cache.build_key("profile", upper_symbol)
        metrics_key = self.cache.build_key("metrics", upper_symbol)
        analyst_key = self.cache.build_key("analyst", upper_symbol)
        insiders_key = self.cache.build_key("insiders", upper_symbol)
        news_key = self.cache.build_key("news", upper_symbol)

        profile, metrics, analysts, insiders, news = await asyncio.gather(
            self._panel(
                cache_key=profile_key,
                cache_category="profile",
                primary=lambda: self.yfinance.get_company_profile(upper_symbol),
                fallback=lambda: self.finviz.get_company_profile(upper_symbol),
                bypass_cache=bypass_cache,
            ),
            self._panel(
                cache_key=metrics_key,
                cache_category="metrics",
                primary=lambda: self.finviz.get_key_metrics(upper_symbol),
                fallback=lambda: self.yfinance.get_key_metrics(upper_symbol),
                bypass_cache=bypass_cache,
            ),
            self._panel(
                cache_key=analyst_key,
                cache_category="analyst",
                primary=lambda: self.finviz.get_analyst_ratings(upper_symbol),
                fallback=lambda: self.yfinance.get_analyst_ratings(upper_symbol),
                bypass_cache=bypass_cache,
            ),
            self._panel(
                cache_key=insiders_key,
                cache_category="insiders",
                primary=lambda: self.finviz.get_insider_transactions(upper_symbol),
                fallback=lambda: self.yfinance.get_insider_transactions(upper_symbol),
                bypass_cache=bypass_cache,
            ),
            self._panel(
                cache_key=news_key,
                cache_category="news",
                primary=lambda: self.finviz.get_news(upper_symbol, limit=20),
                fallback=lambda: self.yfinance.get_news(upper_symbol, limit=20),
                bypass_cache=bypass_cache,
            ),
        )

        return PartialDataResult(
            symbol=upper_symbol,
            panels={
                "profile": profile,
                "metrics": metrics,
                "analysts": analysts,
                "insiders": insiders,
                "news": news,
            },
        )

    async def get_current_price(self, symbol: str, bypass_cache: bool = False) -> DataPanelResult:
        upper_symbol = symbol.upper()
        price_key = self.cache.build_key("price", upper_symbol)
        return await self._panel(
            cache_key=price_key,
            cache_category="price",
            primary=lambda: self.yfinance.get_current_price(upper_symbol),
            bypass_cache=bypass_cache,
        )
