from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from finvizfinance.screener.overview import Overview

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

    async def screen_stocks(self, filters: dict[str, Any], limit: int = 300) -> list[dict[str, Any]]:
        """Run a screener query via finviz overview with best-effort filter mapping."""
        cache_key = self.cache.build_key("screener", "US", **filters)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        finviz_filters = _map_filters_to_finviz(filters)

        def _run() -> list[dict[str, Any]]:
            overview = Overview()
            if finviz_filters:
                overview.set_filter(filters_dict=finviz_filters)
            df = overview.screener_view(order="Market Cap.", limit=limit, verbose=0, ascend=False, sleep_sec=0)
            if df is None or getattr(df, "empty", True):
                return []

            rows: list[dict[str, Any]] = []
            for row in df.to_dict(orient="records"):
                rows.append(
                    {
                        "ticker": _as_str(row.get("Ticker")),
                        "company": _as_str(row.get("Company")),
                        "price": _to_float(row.get("Price")),
                        "change_pct": _to_percent_float(row.get("Change")),
                        "mkt_cap": _as_str(row.get("Market Cap")),
                        "mkt_cap_num": _to_mkt_cap_num(row.get("Market Cap")),
                        "pe": _to_float(row.get("P/E")),
                        "eps": _to_float(row.get("EPS (ttm)")),
                        "volume": _to_float(row.get("Volume")),
                    }
                )
            return rows

        try:
            rows = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Screener query failed: %s", exc)
            rows = []

        self.cache.set(cache_key, rows, ttl_for("screener"))
        return rows


def _map_filters_to_finviz(filters: dict[str, Any]) -> dict[str, str]:
    mapped: dict[str, str] = {}

    _map_under_over(filters, mapped, "pe_min", "pe_max", "P/E")
    _map_under_over(filters, mapped, "fwd_pe_min", "fwd_pe_max", "Forward P/E")
    _map_under_over(filters, mapped, "pb_min", "pb_max", "P/B")
    _map_under_over(filters, mapped, "eps_min", "eps_max", "EPS growththis year", suffix="%")
    _map_under_over(filters, mapped, "roe_min", "roe_max", "Return on Equity", suffix="%")
    _map_under_over(filters, mapped, "rsi_min", "rsi_max", "RSI (14)")
    _map_under_over(filters, mapped, "insider_min", "insider_max", "InsiderOwnership", suffix="%")

    mkt_cap_map = {
        "mega": "Mega ($200bln and more)",
        "large": "Large ($10bln to $200bln)",
        "mid": "Mid ($2bln to $10bln)",
        "small": "Small ($300mln to $2bln)",
        "micro": "Micro ($50mln to $300mln)",
    }
    mkt_cap = filters.get("mkt_cap")
    if mkt_cap in mkt_cap_map:
        mapped["Market Cap."] = mkt_cap_map[str(mkt_cap)]

    sma50_pos = filters.get("sma50_pos")
    if sma50_pos == "above":
        mapped["50-Day Simple Moving Average"] = "Price above SMA50"
    elif sma50_pos == "below":
        mapped["50-Day Simple Moving Average"] = "Price below SMA50"

    return mapped


def _map_under_over(
    filters: dict[str, Any],
    out: dict[str, str],
    min_key: str,
    max_key: str,
    finviz_key: str,
    suffix: str = "",
) -> None:
    max_value = _to_float(filters.get(max_key))
    min_value = _to_float(filters.get(min_key))

    if max_value is not None:
        option = _pick_option(finviz_key, "Under", max_value, suffix=suffix)
        if option:
            out[finviz_key] = option
            return

    if min_value is not None:
        option = _pick_option(finviz_key, "Over", min_value, suffix=suffix)
        if option:
            out[finviz_key] = option


def _pick_option(finviz_key: str, direction: str, value: float, suffix: str = "") -> str | None:
    from finvizfinance.constants import filter_dict

    options = list(filter_dict.get(finviz_key, {}).get("option", {}).keys())
    candidates: list[tuple[float, str]] = []
    pattern = rf"^{direction}\\s+(-?\\d+(?:\\.\\d+)?)\\{suffix}$"
    for option in options:
        match = re.match(pattern, option)
        if not match:
            continue
        candidates.append((float(match.group(1)), option))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    if direction == "Under":
        for threshold, option in candidates:
            if threshold >= value:
                return option
        return candidates[-1][1]

    for threshold, option in reversed(candidates):
        if threshold <= value:
            return option
    return candidates[0][1]


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in {"", "-", "N/A"}:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _to_percent_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("%", "").replace("+", "").strip()
    if text in {"", "-", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_mkt_cap_num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace("$", "")
    if text in {"", "-", "N/A"}:
        return None

    multipliers = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
    suffix = text[-1]
    if suffix in multipliers:
        base = _to_float(text[:-1])
        if base is None:
            return None
        return base * multipliers[suffix]
    return _to_float(text)
