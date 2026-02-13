from __future__ import annotations

from datetime import date
from typing import Any

from app.services.providers.base import BaseProvider, DataUnavailable


class TVScreenerProvider(BaseProvider):
    """Placeholder adapter for tvscreener integrations used by screener queries."""

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Company profile is not available from tvscreener")

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Key metrics are not available from tvscreener")

    async def get_financials(self, symbol: str, period: str) -> dict[str, Any]:
        raise DataUnavailable("Financials are not available from tvscreener")

    async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Analyst ratings are not available from tvscreener")

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Insider transactions are not available from tvscreener")

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        raise DataUnavailable("News is not available from tvscreener")

    async def get_price_history(self, symbol: str, period: str) -> list[dict[str, Any]]:
        raise DataUnavailable("Price history is not available from tvscreener")

    async def get_current_price(self, symbol: str) -> float:
        raise DataUnavailable("Current price is not available from tvscreener")

    async def get_price_on_date(self, symbol: str, target_date: date) -> float | None:
        raise DataUnavailable("Price on date is not available from tvscreener")

    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]:
        raise DataUnavailable("Consensus targets are not available from tvscreener")
