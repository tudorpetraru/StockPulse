"""Regression tests for DataService normalization and formatting edge cases."""
from __future__ import annotations

import asyncio
from typing import Any

from app.services.data_service import (
    DataService,
    _clip_near_zero,
    _display_column_label,
    _fmt_market_cap,
    _to_float,
)


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
    def __init__(self, *, news_rows: list[dict[str, Any]] | None = None, metrics: dict[str, Any] | None = None) -> None:
        self.news_rows = news_rows or []
        self.metrics = metrics or {}

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        _ = symbol
        return self.news_rows[:limit]

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return self.metrics

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        _ = symbol
        return []


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
