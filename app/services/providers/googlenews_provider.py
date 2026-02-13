from __future__ import annotations

import asyncio
import base64
from datetime import date
from typing import Any

from app.services.providers.base import BaseProvider, DataUnavailable


class GoogleNewsProvider(BaseProvider):
    def __init__(self, lang: str = "en", country: str = "US") -> None:
        self._client: Any | None = None
        self._init_error: Exception | None = None
        if not hasattr(base64, "decodestring"):
            base64.decodestring = base64.decodebytes  # type: ignore[attr-defined]
        if not hasattr(base64, "encodestring"):
            base64.encodestring = base64.encodebytes  # type: ignore[attr-defined]
        try:
            from pygooglenews import GoogleNews  # type: ignore[import-not-found]

            self._client = GoogleNews(lang=lang, country=country)
        except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
            self._init_error = exc

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Company profile is not available from Google News")

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Key metrics are not available from Google News")

    async def get_financials(self, symbol: str, period: str) -> dict[str, Any]:
        raise DataUnavailable("Financials are not available from Google News")

    async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Analyst ratings are not available from Google News")

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Insider transactions are not available from Google News")

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        if self._client is None:
            raise DataUnavailable(f"Google News provider unavailable: {self._init_error}")

        def load() -> list[dict[str, Any]]:
            response = self._client.search(symbol)
            entries = response.get("entries", []) if isinstance(response, dict) else []
            items: list[dict[str, Any]] = []
            for entry in entries[:limit]:
                items.append(
                    {
                        "title": entry.get("title"),
                        "source": entry.get("source", {}).get("title"),
                        "published": entry.get("published"),
                        "url": entry.get("link"),
                        "symbol": symbol.upper(),
                    }
                )
            return items

        return await asyncio.to_thread(load)

    async def get_price_history(self, symbol: str, period: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Price history is not available from Google News")

    async def get_current_price(self, symbol: str) -> float:
        raise DataUnavailable("Current price is not available from Google News")

    async def get_price_on_date(self, symbol: str, target_date: date) -> float | None:
        raise DataUnavailable("Price on date is not available from Google News")

    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Consensus targets are not available from Google News")
