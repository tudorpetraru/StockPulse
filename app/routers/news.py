"""News feed router — aggregated news with filters.

Owned by Agent C.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Position, WatchlistItem

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_portfolio_tickers(db: Session) -> list[str]:
    """Get unique tickers from all portfolio positions."""
    rows = db.query(Position.ticker).distinct().all()
    return [r[0] for r in rows]


def _get_watchlist_tickers(db: Session) -> list[str]:
    """Get unique tickers from all watchlists."""
    rows = db.query(WatchlistItem.ticker).distinct().all()
    return [r[0] for r in rows]


def _fetch_news(
    tickers: list[str] | None = None,
    search_query: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Placeholder — will integrate with pygooglenews + finviz via DataService.

    Returns a list of news item dicts with keys:
    title, url, source, published, ticker, summary
    """
    return []


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    filter: str = Query("all"),
    q: str = Query(""),
    db: Session = Depends(get_db),
):
    tickers = None
    if filter == "portfolio":
        tickers = _get_portfolio_tickers(db)
    elif filter == "watchlist":
        tickers = _get_watchlist_tickers(db)
    elif filter == "custom" and q:
        tickers = [t.strip().upper() for t in q.split(",") if t.strip()]

    news_items = _fetch_news(tickers=tickers, search_query=q if filter == "custom" else None)

    return templates.TemplateResponse("news.html", {
        "request": request,
        "active_page": "news",
        "news_items": news_items,
        "active_filter": filter,
        "search_query": q,
    })


@router.get("/hx/news/feed", response_class=HTMLResponse)
def news_feed_partial(
    request: Request,
    filter: str = Query("all"),
    q: str = Query(""),
    page: int = Query(1),
    db: Session = Depends(get_db),
):
    tickers = None
    if filter == "portfolio":
        tickers = _get_portfolio_tickers(db)
    elif filter == "watchlist":
        tickers = _get_watchlist_tickers(db)
    elif filter == "custom" and q:
        tickers = [t.strip().upper() for t in q.split(",") if t.strip()]

    news_items = _fetch_news(
        tickers=tickers,
        search_query=q if filter == "custom" else None,
        limit=20,
    )

    return templates.TemplateResponse("partials/news_feed.html", {
        "request": request,
        "news_items": news_items,
        "active_filter": filter,
        "search_query": q,
        "page": page,
    })
