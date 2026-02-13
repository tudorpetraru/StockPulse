from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable
from typing import Any

from finvizfinance.screener.overview import Overview

from app.errors import SERVICE_RECOVERABLE_ERRORS
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
        except SERVICE_RECOVERABLE_ERRORS as primary_exc:
            logger.warning("Primary provider failed for %s: %s", cache_key, primary_exc)
            if fallback is not None:
                try:
                    data = await self._run_with_retry(fallback)
                    self.cache.set(cache_key, data, ttl_for(cache_category))
                    return DataPanelResult(status="stale", data=data, message="Using fallback provider")
                except SERVICE_RECOVERABLE_ERRORS as fallback_exc:
                    logger.warning("Fallback provider failed for %s: %s", cache_key, fallback_exc)
            stale = self.cache.get(cache_key)
            if stale is not None:
                return DataPanelResult(status="stale", data=stale, message="Using stale cache due to provider errors")
            return DataPanelResult(status="error", message=str(primary_exc))

    async def get_ticker_snapshot(self, symbol: str, bypass_cache: bool = False) -> PartialDataResult:
        upper_symbol = symbol.upper()

        profile_key = self.cache.build_key("profile", upper_symbol)
        metrics_key = self.cache.build_key("metrics", upper_symbol)
        analyst_key = self.cache.build_key("analyst", upper_symbol, schema="v2")
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

    async def get_profile(self, symbol: str) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("profile", upper_symbol),
            cache_category="profile",
            primary=lambda: self.yfinance.get_company_profile(upper_symbol),
            fallback=lambda: self.finviz.get_company_profile(upper_symbol),
        )
        data = panel.data if isinstance(panel.data, dict) else {}
        return {
            "name": _as_str(_first(data, "name", "longName", "shortName")) or upper_symbol,
            "symbol": upper_symbol,
            "sector": _as_str(_first(data, "sector")) or "N/A",
            "industry": _as_str(_first(data, "industry")) or "N/A",
            "exchange": _as_str(_first(data, "exchange")) or "N/A",
            "description": _as_str(_first(data, "description", "longBusinessSummary")),
        }

    async def get_price(self, symbol: str, bypass_cache: bool = False) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("price", upper_symbol),
            cache_category="price",
            primary=lambda: self.yfinance.get_current_price(upper_symbol),
            fallback=lambda: self.finviz.get_current_price(upper_symbol),
            bypass_cache=bypass_cache,
        )
        price = _to_float(panel.data) or 0.0

        profile_cached = self.cache.get(self.cache.build_key("profile", upper_symbol))
        day_change = _to_float(_first(profile_cached, "day_change")) if isinstance(profile_cached, dict) else None
        if day_change is not None and abs(day_change) <= 1:
            change_pct = day_change * 100.0
        else:
            change_pct = day_change or 0.0
        change_pct = _clip_near_zero(change_pct)
        change = price * (change_pct / 100.0)

        return {
            "price": float(price),
            "change": float(change),
            "change_pct": float(change_pct),
            "updated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        }

    async def get_metrics(self, symbol: str, bypass_cache: bool = False) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("metrics", upper_symbol),
            cache_category="metrics",
            primary=lambda: self.finviz.get_key_metrics(upper_symbol),
            fallback=lambda: self.yfinance.get_key_metrics(upper_symbol),
            bypass_cache=bypass_cache,
        )
        data = panel.data if isinstance(panel.data, dict) else {}

        market_cap = _first(data, "Market Cap", "market_cap")
        return {
            "pe": _fmt_metric(_first(data, "P/E", "pe")),
            "fwd_pe": _fmt_metric(_first(data, "Forward P/E", "forward_pe")),
            "peg": _fmt_metric(_first(data, "PEG", "peg")),
            "mkt_cap": _fmt_market_cap(market_cap),
            "ev_ebitda": _fmt_metric(_first(data, "EV/EBITDA", "ev_ebitda")),
            "beta": _fmt_metric(_first(data, "Beta", "beta")),
            "ps": _fmt_metric(_first(data, "P/S", "ps")),
            "pb": _fmt_metric(_first(data, "P/B", "pb")),
            "roe": _fmt_metric(_first(data, "ROE", "roe"), percent=True),
            "profit_margin": _fmt_metric(_first(data, "Profit Margin", "profit_margin"), percent=True),
            "debt_equity": _fmt_metric(_first(data, "Debt/Eq", "debt_equity")),
            "insider_own": _fmt_metric(_first(data, "Insider Own"), percent=True),
        }

    async def get_analyst_ratings(self, symbol: str) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("analyst", upper_symbol, schema="v2"),
            cache_category="analyst",
            primary=lambda: self.finviz.get_analyst_ratings(upper_symbol),
            fallback=lambda: self.yfinance.get_analyst_ratings(upper_symbol),
        )
        rows = panel.data if isinstance(panel.data, list) else []
        normalized: list[dict[str, Any]] = []
        targets: list[float] = []
        rating_counts: dict[str, int] = {}

        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            target = _to_float(_first(row, "price_target", "Price Target", "target"))
            if target is not None:
                targets.append(target)

            rating = _as_str(_first(row, "rating", "Rating")).strip() or "N/A"
            if rating != "N/A":
                rating_counts[rating] = rating_counts.get(rating, 0) + 1

            normalized.append(
                {
                    "date": _display_column_label(_first(row, "date", "Date")),
                    "firm": _as_str(_first(row, "firm", "Firm", "Analyst")) or "Unknown",
                    "action": _as_str(_first(row, "action", "Action")) or "N/A",
                    "rating": rating,
                    "target": f"{target:.2f}" if target is not None else "N/A",
                }
            )

        consensus = max(rating_counts, key=rating_counts.get) if rating_counts else "N/A"
        low_target = min(targets) if targets else None
        avg_target = (sum(targets) / len(targets)) if targets else None
        high_target = max(targets) if targets else None

        if not targets:
            try:
                live_consensus = await self.yfinance.get_consensus_targets(upper_symbol)
                low_target = _to_float(live_consensus.get("low"))
                avg_target = _to_float(live_consensus.get("avg"))
                high_target = _to_float(live_consensus.get("high"))
            except SERVICE_RECOVERABLE_ERRORS as exc:
                logger.debug("Live consensus fallback unavailable for %s: %s", upper_symbol, exc)

        return {
            "consensus": consensus,
            "count": len(normalized),
            "low": f"{low_target:.2f}" if low_target is not None else "N/A",
            "avg": f"{avg_target:.2f}" if avg_target is not None else "N/A",
            "high": f"{high_target:.2f}" if high_target is not None else "N/A",
            "ratings": normalized,
        }

    async def get_financials(self, symbol: str, period: str = "annual") -> dict[str, Any]:
        upper_symbol = symbol.upper()
        period_value = "quarterly" if period == "quarterly" else "annual"
        panel = await self._panel(
            cache_key=self.cache.build_key("financials", upper_symbol, period=period_value),
            cache_category="financials",
            primary=lambda: self.yfinance.get_financials(upper_symbol, period_value),
        )
        data = panel.data if isinstance(panel.data, dict) else {}
        income_rows = data.get("income_statement", []) if isinstance(data.get("income_statement"), list) else []
        balance_rows = data.get("balance_sheet", []) if isinstance(data.get("balance_sheet"), list) else []
        cashflow_rows = data.get("cash_flow", []) if isinstance(data.get("cash_flow"), list) else []
        raw_columns = _extract_columns([income_rows, balance_rows, cashflow_rows])
        columns = [_display_column_label(col) for col in raw_columns]
        return {
            "columns": columns,
            "income": _normalize_financial_rows(income_rows, raw_columns),
            "balance": _normalize_financial_rows(balance_rows, raw_columns),
            "cashflow": _normalize_financial_rows(cashflow_rows, raw_columns),
        }

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("news", upper_symbol, limit=limit),
            cache_category="news",
            primary=lambda: self.finviz.get_news(upper_symbol, limit=limit),
            fallback=lambda: self.yfinance.get_news(upper_symbol, limit=limit),
        )
        rows = panel.data if isinstance(panel.data, list) else []
        news: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            published = _as_str(_first(row, "published", "Date", "date", "datetime"))
            parsed = _parse_datetime(published)
            news.append(
                {
                    "title": _as_str(_first(row, "title", "Title", "News", "headline")) or "Untitled",
                    "link": _as_str(_first(row, "url", "Link", "link")) or "#",
                    "source": _source_name(_first(row, "source", "Source", "provider")) or "Unknown",
                    "date": parsed.strftime("%Y-%m-%d") if parsed else (published or "N/A"),
                    "time_ago": _time_ago(parsed) if parsed else "recent",
                    "ticker": upper_symbol,
                }
            )
        return news

    async def get_insider_trades(self, symbol: str) -> list[dict[str, Any]]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("insiders", upper_symbol),
            cache_category="insiders",
            primary=lambda: self.finviz.get_insider_transactions(upper_symbol),
            fallback=lambda: self.yfinance.get_insider_transactions(upper_symbol),
        )
        rows = panel.data if isinstance(panel.data, list) else []
        result: list[dict[str, Any]] = []
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            shares = _to_float(_first(row, "Shares", "Shares Traded", "#Shares", "shares", "Qty"))
            value = _to_float(_first(row, "Value", "Value ($)", "value", "Transaction Value"))
            result.append(
                {
                    "date": _as_str(_first(row, "Date", "date")) or "N/A",
                    "name": _as_str(_first(row, "Insider", "Insider Trading", "Name", "name")) or "N/A",
                    "title": _as_str(_first(row, "Title", "Relationship", "title")) or "N/A",
                    "type": _as_str(_first(row, "Transaction", "Type", "action", "type")) or "N/A",
                    "shares": shares,
                    "value": value,
                }
            )
        return result

    async def get_holders(self, symbol: str) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("holders", upper_symbol, schema="v3"),
            cache_category="holders",
            primary=lambda: self.yfinance.get_holders(upper_symbol),
        )
        data = panel.data if isinstance(panel.data, dict) else {}
        institutional_rows = data.get("institutional", []) if isinstance(data.get("institutional"), list) else []
        mutual_fund_rows = data.get("mutual_fund", []) if isinstance(data.get("mutual_fund"), list) else []
        institutional = _normalize_holder_rows(institutional_rows)
        mutual_fund = _normalize_holder_rows(mutual_fund_rows)
        return {"institutional": institutional, "mutual_fund": mutual_fund}

    async def get_earnings(self, symbol: str) -> dict[str, Any]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("financials", upper_symbol, panel="earnings"),
            cache_category="financials",
            primary=lambda: self.yfinance.get_earnings(upper_symbol),
        )
        data = panel.data if isinstance(panel.data, dict) else {}
        history = data.get("history", []) if isinstance(data.get("history"), list) else []
        next_date = _as_str(data.get("next_date")).strip() or "N/A"
        return {"history": history[:8], "next_date": next_date}

    async def get_price_history(self, symbol: str, period: str = "1y", bypass_cache: bool = False) -> list[dict[str, Any]]:
        upper_symbol = symbol.upper()
        panel = await self._panel(
            cache_key=self.cache.build_key("price", upper_symbol, period=period),
            cache_category="price",
            primary=lambda: self.yfinance.get_price_history(upper_symbol, period=period),
            bypass_cache=bypass_cache,
        )
        rows = panel.data if isinstance(panel.data, list) else []
        history: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            close = _to_float(_first(row, "close", "Close"))
            if close is None:
                continue
            history.append(
                {
                    "date": _normalize_date(_first(row, "date", "Date", "Datetime")),
                    "open": _to_float(_first(row, "open", "Open")) or close,
                    "high": _to_float(_first(row, "high", "High")) or close,
                    "low": _to_float(_first(row, "low", "Low")) or close,
                    "close": close,
                    "volume": _to_float(_first(row, "volume", "Volume")) or 0.0,
                }
            )
        return history

    async def get_peers(self, symbol: str) -> list[dict[str, Any]]:
        upper_symbol = symbol.upper()
        cache_key = self.cache.build_key("profile", upper_symbol, panel="peers")
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            normalized_cached = _normalize_peer_rows(cached, upper_symbol)
            if normalized_cached != cached:
                self.cache.set(cache_key, normalized_cached, ttl_for("profile"))
            return normalized_cached

        profile = await self.get_profile(upper_symbol)
        sector = _as_str(profile.get("sector")).strip()

        def _run() -> list[dict[str, Any]]:
            overview = Overview()
            if sector and sector != "N/A":
                try:
                    overview.set_filter(filters_dict={"Sector": sector})
                except (ValueError, TypeError, KeyError):
                    logger.debug("Unable to filter peers by sector=%s", sector)

            df = overview.screener_view(order="Market Cap.", limit=40, verbose=0, ascend=False, sleep_sec=0)
            if df is None or getattr(df, "empty", True):
                return []

            peers: list[dict[str, Any]] = []
            for row in df.to_dict(orient="records"):
                peer_symbol = _as_str(row.get("Ticker")).upper()
                if not peer_symbol or peer_symbol == upper_symbol:
                    continue
                ytd = _clip_near_zero(_to_percent_float(_first(row, "Perf YTD", "Perf YTD%")))
                peers.append(
                    {
                        "symbol": peer_symbol,
                        "name": _as_str(row.get("Company")) or peer_symbol,
                        "price": _to_float(row.get("Price")) or 0.0,
                        "pe": _fmt_metric(_first(row, "P/E")),
                        "mkt_cap": _fmt_market_cap(row.get("Market Cap")),
                        "ytd": ytd or 0.0,
                    }
                )
                if len(peers) >= 8:
                    break
            return peers

        try:
            peers = await asyncio.to_thread(_run)
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Peers lookup failed for %s: %s", upper_symbol, exc)
            peers = []

        normalized_peers = _normalize_peer_rows(peers, upper_symbol)
        self.cache.set(cache_key, normalized_peers, ttl_for("profile"))
        return normalized_peers

    async def screen_stocks(self, filters: dict[str, Any], limit: int = 300) -> list[dict[str, Any]]:
        """Run a screener query via finviz overview with best-effort filter mapping."""
        cache_key = self.cache.build_key("screener", "US", **filters)
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            normalized_cached = _normalize_screener_rows(cached)
            if normalized_cached != cached:
                self.cache.set(cache_key, normalized_cached, ttl_for("screener"))
            return normalized_cached

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
                        "change_pct": _clip_near_zero(_to_percent_float(row.get("Change"))),
                        "mkt_cap": _fmt_market_cap(row.get("Market Cap")),
                        "mkt_cap_num": _to_mkt_cap_num(row.get("Market Cap")),
                        "pe": _to_float(row.get("P/E")),
                        "eps": _to_float(row.get("EPS (ttm)")),
                        "volume": _to_float(row.get("Volume")),
                    }
                )
            return rows

        try:
            rows = await asyncio.to_thread(_run)
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Screener query failed: %s", exc)
            rows = []

        normalized_rows = _normalize_screener_rows(rows)
        self.cache.set(cache_key, normalized_rows, ttl_for("screener"))
        return normalized_rows


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
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    text = str(value).strip()
    if text in {"", "-", "N/A"}:
        return None
    try:
        num = float(text.replace(",", ""))
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    except ValueError:
        return None


def _to_percent_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("%", "").replace("+", "").strip()
    if text in {"", "-", "N/A"}:
        return None
    try:
        num = float(text)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
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


def _first(data: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data.get(key) not in (None, ""):
            return data.get(key)
    return None


def _fmt_metric(value: Any, percent: bool = False) -> str:
    number = _to_float(value)
    if number is None:
        text = _as_str(value).strip()
        if text.lower() in {"nan", "inf", "+inf", "-inf"}:
            return "N/A"
        return text if text else "N/A"
    if percent:
        pct = number * 100.0 if abs(number) <= 1 else number
        return f"{pct:.1f}%"
    if abs(number) >= 100:
        return f"{number:,.0f}"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_market_cap(value: Any) -> str:
    text = _as_str(value).strip()
    if text and any(ch in text.upper() for ch in ("B", "M", "T")):
        return text
    number = _to_float(value)
    if number is None:
        return "N/A"
    if number >= 1e12:
        return f"{number / 1e12:.2f}T"
    if number >= 1e9:
        return f"{number / 1e9:.2f}B"
    if number >= 1e6:
        return f"{number / 1e6:.2f}M"
    return f"{number:,.0f}"


def _clip_near_zero(value: float | None, threshold: float = 0.05) -> float | None:
    if value is None:
        return None
    return 0.0 if abs(value) < threshold else value


def _extract_columns(groups: list[list[dict[str, Any]]]) -> list[Any]:
    for rows in groups:
        if not rows:
            continue
        first_row = rows[0]
        keys = [k for k in first_row.keys() if k not in {"index", "Breakdown", ""}]
        if keys:
            return keys[:4]
    return []


def _display_column_label(value: Any) -> str:
    text = _as_str(value).strip()
    if not text:
        return "N/A"
    date_prefix = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if date_prefix:
        return date_prefix.group(1)
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.date().isoformat()
    return text.split(" ")[0] if " " in text and ":" in text else text


def _normalize_financial_rows(rows: list[dict[str, Any]], columns: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows[:40]:
        label = _as_str(_first(row, "index", "Breakdown")) or "N/A"
        values = []
        for col in columns:
            val = _lookup_financial_value(row, col)
            num = _to_float(val)
            if num is not None:
                if abs(num) >= 1e9:
                    values.append(f"{num / 1e9:.2f}B")
                elif abs(num) >= 1e6:
                    values.append(f"{num / 1e6:.2f}M")
                else:
                    values.append(f"{num:,.0f}")
            else:
                values.append(_as_str(val) or "N/A")
        normalized.append({"label": label, "values": values})
    return normalized


def _lookup_financial_value(row: dict[str, Any], col: Any) -> Any:
    if col in row:
        return row.get(col)

    col_text = _as_str(col).strip()
    if col_text and col_text in row:
        return row.get(col_text)

    col_label = _display_column_label(col)
    if col_label in row:
        return row.get(col_label)

    for key, value in row.items():
        if _display_column_label(key) == col_label:
            return value
    return None


def _normalize_peer_rows(rows: list[dict[str, Any]], target_symbol: str | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    upper_target = (target_symbol or "").upper().strip()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _as_str(_first(row, "symbol", "ticker", "Ticker")).upper().strip()
        if not symbol:
            continue
        if upper_target and symbol == upper_target:
            continue

        ytd = _clip_near_zero(_to_percent_float(_first(row, "ytd", "Perf YTD", "Perf YTD%")))
        normalized.append(
            {
                "symbol": symbol,
                "name": _as_str(_first(row, "name", "company", "Company")) or symbol,
                "price": _to_float(_first(row, "price", "Price")) or 0.0,
                "pe": _fmt_metric(_first(row, "pe", "P/E")),
                "mkt_cap": _fmt_market_cap(_first(row, "mkt_cap", "market_cap", "Market Cap")),
                "ytd": ytd or 0.0,
            }
        )
    return normalized


def _to_percent_value(value: Any) -> float | None:
    num = _to_float(value)
    if num is None:
        return None
    return num * 100.0 if abs(num) <= 1 else num


def _normalize_holder_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        shares = _to_float(_first(row, "shares", "Shares"))
        value = _to_float(_first(row, "value", "Value"))
        normalized.append(
            {
                "name": _as_str(_first(row, "name", "Holder", "holder", "Name")) or "N/A",
                "shares": shares,
                "pct_in": _to_percent_value(_first(row, "pct_in", "% In", "% Held", "pctHeld")),
                "pct_out": _to_percent_value(_first(row, "pct_out", "% Out", "Pct Out")),
                "pct_change": _to_percent_value(_first(row, "pct_change", "% Change", "Pct Change", "pctChange")),
                "value": value,
                "date": _display_column_label(_first(row, "date", "Date", "Date Reported")),
            }
        )

    return normalized


def _normalize_screener_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "ticker": _as_str(_first(row, "ticker", "Ticker")).upper(),
                "company": _as_str(_first(row, "company", "Company")),
                "price": _to_float(_first(row, "price", "Price")),
                "change_pct": _clip_near_zero(_to_percent_float(_first(row, "change_pct", "change", "Change"))),
                "mkt_cap": _fmt_market_cap(_first(row, "mkt_cap", "market_cap", "Market Cap")),
                "mkt_cap_num": _to_mkt_cap_num(_first(row, "mkt_cap_num", "mkt_cap", "market_cap", "Market Cap")),
                "pe": _to_float(_first(row, "pe", "P/E")),
                "eps": _to_float(_first(row, "eps", "EPS (ttm)")),
                "volume": _to_float(_first(row, "volume", "Volume")),
            }
        )
    return normalized


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%b-%d-%y %I:%M%p"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _time_ago(ts: datetime | None) -> str:
    if ts is None:
        return "recent"
    delta = datetime.now(UTC) - ts
    if delta.total_seconds() < 3600:
        minutes = max(1, int(delta.total_seconds() // 60))
        return f"{minutes}m ago"
    if delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() // 3600)
        return f"{hours}h ago"
    days = int(delta.total_seconds() // 86400)
    return f"{days}d ago"


def _source_name(value: Any) -> str:
    if isinstance(value, dict):
        text = _as_str(value.get("displayName") or value.get("title") or value.get("name"))
        return text.strip()
    return _as_str(value).strip()


def _normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = _as_str(value).strip()
    if not text:
        return ""
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.date().isoformat()
    if " " in text:
        return text.split(" ")[0]
    return text
