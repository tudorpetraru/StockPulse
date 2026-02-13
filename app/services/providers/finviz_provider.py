from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from finvizfinance.quote import finvizfinance

from app.services.providers.base import BaseProvider, DataUnavailable, InvalidSymbol


class FinvizProvider(BaseProvider):
    async def _quote(self, symbol: str) -> finvizfinance:
        if not symbol or not symbol.strip():
            raise InvalidSymbol("Symbol cannot be empty")
        return finvizfinance(symbol.upper())

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        quote = await self._quote(symbol)

        def load() -> dict[str, Any]:
            profile = quote.ticker_description()
            if not profile:
                raise DataUnavailable(f"No profile for {symbol}")
            return {"symbol": symbol.upper(), "description": profile}

        return await asyncio.to_thread(load)

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        quote = await self._quote(symbol)
        data = await asyncio.to_thread(lambda: quote.ticker_fundament())
        if not data:
            raise DataUnavailable(f"No key metrics for {symbol}")
        return data

    async def get_financials(self, symbol: str, period: str) -> dict[str, Any]:
        raise DataUnavailable("Financials are not provided by finviz provider")

    async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]:
        quote = await self._quote(symbol)
        ratings = await asyncio.to_thread(lambda: quote.ticker_outer_ratings())
        if ratings is None:
            return []
        rows = ratings.to_dict(orient="records") if hasattr(ratings, "to_dict") else list(ratings)
        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized.append(
                {
                    "date": row.get("Date"),
                    "firm": row.get("Analyst") or row.get("Firm") or "Unknown",
                    "action": row.get("Action"),
                    "rating": row.get("Rating") or row.get("To Grade") or "N/A",
                    "price_target": row.get("Price Target") or row.get("Price_Target"),
                }
            )
        return normalized

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        quote = await self._quote(symbol)
        insiders = await asyncio.to_thread(lambda: quote.ticker_inside_trader())
        if insiders is None:
            return []
        return insiders.to_dict(orient="records") if hasattr(insiders, "to_dict") else list(insiders)

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        quote = await self._quote(symbol)
        news = await asyncio.to_thread(lambda: quote.ticker_news())
        if news is None:
            return []
        rows = news.to_dict(orient="records") if hasattr(news, "to_dict") else list(news)
        return rows[:limit]

    async def get_price_history(self, symbol: str, period: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Price history is not provided by finviz provider")

    async def get_current_price(self, symbol: str) -> float:
        metrics = await self.get_key_metrics(symbol)
        price = metrics.get("Price")
        if price in (None, ""):
            raise DataUnavailable(f"No current price for {symbol}")
        return float(str(price).replace("$", "").replace(",", ""))

    async def get_price_on_date(self, symbol: str, target_date: date) -> float | None:
        raise DataUnavailable("Historical price-on-date is not provided by finviz provider")

    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]:
        ratings = await self.get_analyst_ratings(symbol)
        targets = [row.get("price_target") for row in ratings if row.get("price_target") not in (None, "")]
        numeric_targets: list[float] = []
        for target in targets:
            try:
                numeric_targets.append(float(str(target).replace("$", "").replace(",", "")))
            except ValueError:
                continue
        current = await self.get_current_price(symbol)
        if not numeric_targets:
            return {
                "low": None,
                "avg": None,
                "median": None,
                "high": None,
                "count": len(ratings) or None,
                "consensus": None,
                "current": current,
            }
        sorted_targets = sorted(numeric_targets)
        middle = len(sorted_targets) // 2
        median = (
            sorted_targets[middle]
            if len(sorted_targets) % 2 == 1
            else (sorted_targets[middle - 1] + sorted_targets[middle]) / 2
        )
        return {
            "low": min(sorted_targets),
            "avg": sum(sorted_targets) / len(sorted_targets),
            "median": median,
            "high": max(sorted_targets),
            "count": len(sorted_targets),
            "consensus": None,
            "current": current,
        }
