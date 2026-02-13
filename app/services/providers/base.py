from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any


class DataProviderError(Exception):
    """Base provider exception."""


class DataUnavailable(DataProviderError):
    """Provider returned no usable data."""


class InvalidSymbol(DataProviderError):
    """Invalid or unsupported ticker symbol."""


class RateLimited(DataProviderError):
    """Provider request rejected due to rate limiting."""


@dataclass(slots=True)
class ProviderResult:
    data: Any
    stale: bool = False


class BaseProvider(ABC):
    @abstractmethod
    async def get_company_profile(self, symbol: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_key_metrics(self, symbol: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_financials(self, symbol: str, period: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_price_history(self, symbol: str, period: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float: ...

    @abstractmethod
    async def get_price_on_date(self, symbol: str, target_date: date) -> float | None: ...

    @abstractmethod
    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]: ...
