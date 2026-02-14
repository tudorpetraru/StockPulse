"""News feed router — aggregated news with filters.

Owned by Agent C.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_data_service
from app.errors import SERVICE_RECOVERABLE_ERRORS
from app.models.db_models import Position, WatchlistItem
from app.services.data_service import DataService

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
_DEFAULT_TIMEFRAME = "24h"
_TIMEFRAME_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _get_portfolio_tickers(db: Session) -> list[str]:
    """Get unique tickers from all portfolio positions."""
    rows = db.query(Position.ticker).distinct().all()
    return [r[0] for r in rows]


def _get_watchlist_tickers(db: Session) -> list[str]:
    """Get unique tickers from all watchlists."""
    rows = db.query(WatchlistItem.ticker).distinct().all()
    return [r[0] for r in rows]


def _parse_custom_input(raw: str) -> tuple[list[str] | None, str | None]:
    value = raw.strip()
    if not value:
        return None, None
    parts = [p.strip().upper() for p in value.split(",") if p.strip()]
    if parts and all(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", part) for part in parts):
        return parts, None
    return None, value


def _normalize_timeframe(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _TIMEFRAME_WINDOWS:
        return value
    return _DEFAULT_TIMEFRAME


def _parse_published_datetime(raw: str) -> datetime | None:
    value = raw.strip()
    if not value or value.upper() == "N/A":
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
    except (TypeError, ValueError):
        pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(hour=23, minute=59, second=59, tzinfo=UTC)
        except ValueError:
            continue

    return None


def _normalize_news_item(row: dict, default_ticker: str | None = None) -> dict:
    source_raw = row.get("source") or row.get("Source")
    if isinstance(source_raw, dict):
        source = source_raw.get("displayName") or source_raw.get("title") or source_raw.get("name") or "Unknown"
    else:
        source = source_raw or "Unknown"
    published = str(row.get("published") or row.get("date") or row.get("Date") or row.get("time_ago") or "N/A")
    ticker_raw = row.get("ticker") or row.get("symbol") or default_ticker
    ticker = str(ticker_raw).strip().upper() if ticker_raw else None
    if ticker and not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
        ticker = None

    return {
        "title": row.get("title") or row.get("Title") or row.get("headline") or "Untitled",
        "url": row.get("url") or row.get("link") or row.get("Link") or "#",
        "source": source,
        "published": published,
        "ticker": ticker,
        "summary": row.get("summary") or "",
    }


def _published_sort_key(item: dict) -> datetime:
    raw = str(item.get("published") or "")
    parsed = _parse_published_datetime(raw)
    if parsed is None:
        return datetime.min.replace(tzinfo=UTC)
    return parsed


async def _fetch_news(
    request: Request,
    ds: DataService,
    tickers: list[str] | None = None,
    search_query: str | None = None,
    timeframe: str = _DEFAULT_TIMEFRAME,
    limit: int = 20,
    page: int = 1,
) -> tuple[list[dict], bool]:
    current_page = max(page, 1)
    start = (current_page - 1) * limit
    end = start + limit
    target = end + 1
    items: list[dict] = []

    normalized_tickers = []
    for ticker in tickers or []:
        clean = ticker.strip().upper()
        if clean and clean not in normalized_tickers:
            normalized_tickers.append(clean)

    if normalized_tickers:
        selected = normalized_tickers[:8]
        symbol_count = max(len(selected), 1)
        per_symbol = max(8, ((target + symbol_count - 1) // symbol_count) + 2)
        per_symbol = min(per_symbol, max(25, target + 5))
        batches = await asyncio.gather(
            *(ds.get_news(symbol, limit=per_symbol) for symbol in selected),
            return_exceptions=True,
        )
        for symbol, batch in zip(selected, batches, strict=False):
            if isinstance(batch, Exception):
                logger.warning("News lookup failed for %s: %s", symbol, batch)
                continue
            for row in batch:
                if isinstance(row, dict):
                    items.append(_normalize_news_item(row, default_ticker=symbol))
    else:
        query = (search_query or "US stock market").strip()
        providers = getattr(request.app.state, "providers", {})
        google = providers.get("googlenews") if isinstance(providers, dict) else None
        if google is not None and hasattr(google, "get_news"):
            try:
                batch = await google.get_news(query, limit=target)
                for row in batch:
                    if isinstance(row, dict):
                        items.append(_normalize_news_item(row))
            except SERVICE_RECOVERABLE_ERRORS as exc:
                logger.warning("Google News lookup failed for query=%s: %s", query, exc)

        if not items:
            fallback = await asyncio.gather(
                ds.get_news("SPY", limit=max(2, target // 2)),
                ds.get_news("QQQ", limit=max(2, target // 2)),
                return_exceptions=True,
            )
            for symbol, batch in zip(("SPY", "QQQ"), fallback, strict=False):
                if isinstance(batch, Exception):
                    continue
                for row in batch:
                    if isinstance(row, dict):
                        items.append(_normalize_news_item(row, default_ticker=symbol))

    dedup: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (str(item.get("url", "")).strip(), str(item.get("title", "")).strip())
        if key not in dedup:
            dedup[key] = item

    cutoff = datetime.now(UTC) - _TIMEFRAME_WINDOWS.get(timeframe, _TIMEFRAME_WINDOWS[_DEFAULT_TIMEFRAME])
    filtered = []
    for item in dedup.values():
        published_dt = _parse_published_datetime(str(item.get("published") or ""))
        if published_dt is None:
            continue
        if published_dt >= cutoff:
            filtered.append(item)

    ordered = sorted(filtered, key=_published_sort_key, reverse=True)
    page_items = ordered[start:end]
    has_more = len(ordered) > end
    return page_items, has_more


@router.get("/news", response_class=HTMLResponse)
async def news_page(
    request: Request,
    filter: str = Query("all"),
    q: str = Query("", max_length=500),
    timeframe: str = Query(_DEFAULT_TIMEFRAME),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    timeframe_key = _normalize_timeframe(timeframe)
    tickers = None
    search_query = None
    if filter == "portfolio":
        tickers = _get_portfolio_tickers(db)
    elif filter == "watchlist":
        tickers = _get_watchlist_tickers(db)
    elif filter == "custom" and q:
        tickers, search_query = _parse_custom_input(q)

    news_items, has_more = await _fetch_news(
        request,
        ds,
        tickers=tickers,
        search_query=search_query,
        timeframe=timeframe_key,
        limit=20,
        page=1,
    )

    return templates.TemplateResponse("news.html", {
        "request": request,
        "active_page": "news",
        "news_items": news_items,
        "active_filter": filter,
        "active_timeframe": timeframe_key,
        "search_query": q,
        "page": 1,
        "has_more": has_more,
    })


@router.get("/hx/news/feed", response_class=HTMLResponse)
async def news_feed_partial(
    request: Request,
    filter: str = Query("all"),
    q: str = Query("", max_length=500),
    timeframe: str = Query(_DEFAULT_TIMEFRAME),
    page: int = Query(1),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    timeframe_key = _normalize_timeframe(timeframe)
    tickers = None
    search_query = None
    if filter == "portfolio":
        tickers = _get_portfolio_tickers(db)
    elif filter == "watchlist":
        tickers = _get_watchlist_tickers(db)
    elif filter == "custom" and q:
        tickers, search_query = _parse_custom_input(q)

    news_items, has_more = await _fetch_news(
        request,
        ds,
        tickers=tickers,
        search_query=search_query,
        timeframe=timeframe_key,
        limit=20,
        page=max(page, 1),
    )

    return templates.TemplateResponse("partials/news_feed.html", {
        "request": request,
        "news_items": news_items,
        "active_filter": filter,
        "active_timeframe": timeframe_key,
        "search_query": q,
        "page": page,
        "has_more": has_more,
    })
