from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from diskcache import Cache

from app.config import get_settings


@dataclass(frozen=True)
class CachePolicy:
    ttl_seconds: int


CACHE_POLICIES: dict[str, CachePolicy] = {
    "price": CachePolicy(ttl_seconds=5 * 60),
    "metrics": CachePolicy(ttl_seconds=15 * 60),
    "financials": CachePolicy(ttl_seconds=60 * 60),
    "analyst": CachePolicy(ttl_seconds=60 * 60),
    "news": CachePolicy(ttl_seconds=10 * 60),
    "screener": CachePolicy(ttl_seconds=15 * 60),
    "insiders": CachePolicy(ttl_seconds=60 * 60),
    "profile": CachePolicy(ttl_seconds=6 * 60 * 60),
    "holders": CachePolicy(ttl_seconds=6 * 60 * 60),
}


class CacheService:
    def __init__(self) -> None:
        settings = get_settings()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(directory=str(settings.cache_dir), size_limit=settings.cache_size_limit_bytes)

    @staticmethod
    def build_key(category: str, symbol: str, **kwargs: Any) -> str:
        suffix = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        if suffix:
            return f"{category}:{symbol.upper()}:{suffix}"
        return f"{category}:{symbol.upper()}"

    def get(self, key: str) -> Any | None:
        return self._cache.get(key, default=None)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._cache.set(key, value, expire=ttl_seconds)

    def delete(self, key: str) -> bool:
        return bool(self._cache.delete(key))

    def clear_prefix(self, prefix: str) -> int:
        removed = 0
        for k in list(self._cache.iterkeys()):
            if str(k).startswith(prefix):
                self._cache.delete(k)
                removed += 1
        return removed

    def close(self) -> None:
        self._cache.close()


def ttl_for(category: str) -> int:
    policy = CACHE_POLICIES.get(category)
    if policy is None:
        raise KeyError(f"Unknown cache category: {category}")
    return policy.ttl_seconds
