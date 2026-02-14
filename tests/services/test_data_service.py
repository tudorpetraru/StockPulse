"""Regression tests for DataService normalization and formatting edge cases."""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from app.services.data_service import (
    DataService,
    _clip_near_zero,
    _display_column_label,
    _fmt_market_cap,
    _map_filters_to_finviz,
    _to_float,
)
from app.services.providers.base import DataProviderError


class _DummyCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def build_key(self, category: str, symbol: str, **kwargs: Any) -> str:
        parts = [category, symbol]
        for key in sorted(kwargs):
            parts.append(f"{key}={kwargs[key]}")
        return "|".join(parts)

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        _ = ttl
        self._store[key] = value


class _DummyProvider:
    def __init__(
        self,
        *,
        news_rows: list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
        consensus_targets: dict[str, Any] | None = None,
        holders: dict[str, Any] | None = None,
    ) -> None:
        self.news_rows = news_rows or []
        self.metrics = metrics or {}
        self.consensus_targets = consensus_targets or {}
        self.holders = holders or {"institutional": [], "mutual_fund": []}

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        _ = symbol
        return self.news_rows[:limit]

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return self.metrics

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        _ = symbol
        return []

    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return self.consensus_targets

    async def get_holders(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return self.holders

    async def get_financials(self, symbol: str, period: str = "annual") -> dict[str, Any]:
        _ = (symbol, period)
        return {"income_statement": [], "balance_sheet": [], "cash_flow": []}

    async def get_price_delta(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return {"change": 0.0, "change_pct": 0.0}


def test_get_news_maps_title_link_and_dict_source():
    cache = _DummyCache()
    finviz = _DummyProvider(
        news_rows=[
            {
                "Title": "Uppercase Title",
                "Link": "https://example.com/news",
                "Source": {"displayName": "Mapped Source"},
                "Date": "2026-02-13",
            }
        ]
    )
    yfinance = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    items = asyncio.run(service.get_news("AAPL", limit=5))
    assert items[0]["title"] == "Uppercase Title"
    assert items[0]["link"] == "https://example.com/news"
    assert items[0]["source"] == "Mapped Source"


def test_clip_near_zero_avoids_negative_zero_display():
    assert _clip_near_zero(-0.001) == 0.0
    assert _clip_near_zero(0.001) == 0.0
    assert _clip_near_zero(-0.2) == -0.2


def test_market_cap_formatting_from_large_numeric_values():
    assert _fmt_market_cap("4542640000000.0") == "4.54T"
    assert _fmt_market_cap(335770000000.0) == "335.77B"


def test_to_float_treats_nan_as_missing():
    assert _to_float(float("nan")) is None
    assert _to_float("nan") is None


def test_get_metrics_converts_nan_to_na():
    cache = _DummyCache()
    finviz = _DummyProvider(metrics={"P/E": float("nan"), "Market Cap": "4542640000000.0"})
    yfinance = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    metrics = asyncio.run(service.get_metrics("NVDA"))
    assert metrics["pe"] == "N/A"
    assert metrics["mkt_cap"] == "4.54T"


def test_display_column_label_strips_midnight_suffix():
    assert _display_column_label("2025-10-31 00:00:00") == "2025-10-31"


def test_get_insider_trades_maps_finviz_fields():
    cache = _DummyCache()

    class _InsiderProvider(_DummyProvider):
        async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
            _ = symbol
            return [
                {
                    "Date": "Feb 04 '26",
                    "Insider Trading": "Kress Colette",
                    "Relationship": "EVP & Chief Financial Officer",
                    "Transaction": "Sale",
                    "#Shares": 27640.0,
                    "Value ($)": 4856861.0,
                }
            ]

    finviz = _InsiderProvider()
    yfinance = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)
    rows = asyncio.run(service.get_insider_trades("NVDA"))
    assert rows[0]["name"] == "Kress Colette"
    assert rows[0]["title"] == "EVP & Chief Financial Officer"
    assert rows[0]["shares"] == 27640.0
    assert rows[0]["value"] == 4856861.0


def test_get_analyst_ratings_falls_back_to_live_consensus_targets():
    cache = _DummyCache()

    class _AnalystProvider(_DummyProvider):
        async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]:
            _ = symbol
            return [
                {
                    "date": "2026-02-10 00:00:00",
                    "firm": "Bernstein",
                    "action": "Reiterated",
                    "rating": "Outperform",
                    "price_target": None,
                }
            ]

    finviz = _AnalystProvider()
    yfinance = _DummyProvider(consensus_targets={"low": 205.0, "avg": 293.06952, "high": 350.0})
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    ratings = asyncio.run(service.get_analyst_ratings("AAPL"))
    assert ratings["low"] == "205.00"
    assert ratings["avg"] == "293.07"
    assert ratings["high"] == "350.00"
    assert ratings["ratings"][0]["date"] == "2026-02-10"


def test_get_holders_normalizes_pct_in_and_pct_change():
    cache = _DummyCache()
    yfinance = _DummyProvider(
        holders={
            "institutional": [
                {"name": "Fund A", "shares": 100.0, "pct_in": 0.25, "pct_change": 0.10, "value": 3000.0, "date": "2025-12-31"},
                {"name": "Fund B", "shares": 300.0, "pct_in": 0.75, "pct_change": -0.10, "value": 1000.0, "date": "2025-12-31"},
            ],
            "mutual_fund": [],
        }
    )
    finviz = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    holders = asyncio.run(service.get_holders("AAPL"))
    first = holders["institutional"][0]
    second = holders["institutional"][1]

    assert first["pct_in"] == 25.0
    assert second["pct_in"] == 75.0
    assert first["pct_change"] == 10.0
    assert second["pct_change"] == -10.0


def test_get_price_ignores_outlier_profile_day_change_pct():
    cache = _DummyCache()
    yfinance = _DummyProvider()
    finviz = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    cache.set(cache.build_key("price", "ISLN.L"), 73.19, ttl=60)
    cache.set(cache.build_key("profile", "ISLN.L", schema="v2"), {"day_change": -96.69795}, ttl=60)

    quote = asyncio.run(service.get_price("ISLN.L"))
    assert quote["price"] == 73.19
    assert quote["change_pct"] == 0.0
    assert quote["change"] == 0.0


def test_get_price_prefers_yfinance_delta_panel():
    cache = _DummyCache()

    class _DeltaProvider(_DummyProvider):
        async def get_current_price(self, symbol: str) -> float:
            _ = symbol
            return 100.0

        async def get_price_delta(self, symbol: str) -> dict[str, Any]:
            _ = symbol
            return {"change": -1.5, "change_pct": -1.5}

    yfinance = _DeltaProvider()
    finviz = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    quote = asyncio.run(service.get_price("AAPL", bypass_cache=True))
    assert quote["price"] == 100.0
    assert quote["change"] == -1.5
    assert quote["change_pct"] == -1.5


def test_get_financials_maps_timestamp_columns_for_annual_and_quarterly():
    cache = _DummyCache()

    class _FinancialProvider(_DummyProvider):
        async def get_financials(self, symbol: str, period: str = "annual") -> dict[str, Any]:
            _ = symbol
            if period == "quarterly":
                c1 = pd.Timestamp("2025-12-31 00:00:00")
                c2 = pd.Timestamp("2025-09-30 00:00:00")
                return {
                    "income_statement": [{"index": "Revenue", c1: 10_000_000_000, c2: 9_000_000_000}],
                    "balance_sheet": [],
                    "cash_flow": [],
                }
            c1 = pd.Timestamp("2025-09-30 00:00:00")
            c2 = pd.Timestamp("2024-09-30 00:00:00")
            return {
                "income_statement": [{"index": "Revenue", c1: 100_000_000_000, c2: 95_000_000_000}],
                "balance_sheet": [],
                "cash_flow": [],
            }

    yfinance = _FinancialProvider()
    finviz = _DummyProvider()
    service = DataService(cache=cache, yfinance_provider=yfinance, finviz_provider=finviz)

    annual = asyncio.run(service.get_financials("AAPL", period="annual"))
    quarterly = asyncio.run(service.get_financials("AAPL", period="quarterly"))

    assert annual["columns"] == ["2025-09-30", "2024-09-30"]
    assert annual["income"][0]["label"] == "Revenue"
    assert annual["income"][0]["values"] == ["100.00B", "95.00B"]

    assert quarterly["columns"] == ["2025-12-31", "2025-09-30"]
    assert quarterly["income"][0]["values"] == ["10.00B", "9.00B"]


def test_map_filters_to_finviz_includes_sector_and_industry():
    mapped = _map_filters_to_finviz({"sector": "technology", "industry": "semiconductors"})
    assert mapped["Sector"] == "Technology"
    assert mapped["Industry"] == "Semiconductors"


def test_screen_stocks_ignores_cached_empty_and_refetches(monkeypatch):
    cache = _DummyCache()
    key = cache.build_key("screener", "US")
    cache.set(key, [], ttl=60)

    class _OverviewWithRows:
        def set_filter(self, filters_dict: dict[str, str]):
            _ = filters_dict

        def screener_view(self, **kwargs):
            _ = kwargs
            return pd.DataFrame(
                [{"Ticker": "AAPL", "Company": "Apple Inc", "Sector": "Technology", "Industry": "Consumer Electronics", "Price": 200.0, "Change": "+1.2%", "Market Cap": "3.0T", "P/E": 30.0, "Volume": 12345}]
            )

    monkeypatch.setattr("app.services.data_service.Overview", _OverviewWithRows)

    service = DataService(cache=cache, yfinance_provider=_DummyProvider(), finviz_provider=_DummyProvider())
    rows = asyncio.run(service.screen_stocks({}))

    assert rows
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["sector"] == "Technology"
    assert rows[0]["industry"] == "Consumer Electronics"


def test_screen_stocks_raises_provider_error_on_recoverable_failure(monkeypatch):
    cache = _DummyCache()
    key = cache.build_key("screener", "US")

    class _OverviewRaises:
        def set_filter(self, filters_dict: dict[str, str]):
            _ = filters_dict

        def screener_view(self, **kwargs):
            _ = kwargs
            raise OSError("finviz rate limited")

    monkeypatch.setattr("app.services.data_service.Overview", _OverviewRaises)

    service = DataService(cache=cache, yfinance_provider=_DummyProvider(), finviz_provider=_DummyProvider())

    try:
        asyncio.run(service.screen_stocks({}))
        assert False, "Expected DataProviderError"
    except DataProviderError:
        pass

    assert cache.get(key) is None
