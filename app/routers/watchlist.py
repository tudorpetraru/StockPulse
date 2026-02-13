"""Watchlist router — named watchlists with live quote hydration and HTMX table refresh."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_data_service
from app.errors import SERVICE_RECOVERABLE_ERRORS
from app.models.db_models import Watchlist, WatchlistItem
from app.services.data_service import DataService

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_SORTABLE_FIELDS = {"ticker", "price", "change", "pe"}


def _get_or_create_default_watchlist(db: Session) -> Watchlist:
    wl = db.query(Watchlist).first()
    if not wl:
        wl = Watchlist(name="My Watchlist")
        db.add(wl)
        db.commit()
        db.refresh(wl)
    return wl


def _parse_sort(sort_by: str, sort_dir: str) -> tuple[str, str]:
    by = sort_by if sort_by in _SORTABLE_FIELDS else "ticker"
    direction = "desc" if sort_dir == "desc" else "asc"
    return by, direction


def _sort_watch_rows(rows: list[dict[str, Any]], sort_by: str, sort_dir: str) -> list[dict[str, Any]]:
    by, direction = _parse_sort(sort_by, sort_dir)
    reverse = direction == "desc"
    if by == "ticker":
        return sorted(rows, key=lambda row: str(row["item"].ticker), reverse=reverse)
    key_name = "change_pct" if by == "change" else by
    return sorted(rows, key=lambda row: float(row.get(key_name) or 0.0), reverse=reverse)


async def _safe_price_lookup(ds: DataService, ticker: str, refresh: bool) -> dict[str, Any]:
    try:
        return await ds.get_price(ticker, bypass_cache=refresh)
    except TypeError:
        return await ds.get_price(ticker)


async def _safe_metrics_lookup(ds: DataService, ticker: str, refresh: bool) -> dict[str, Any]:
    try:
        return await ds.get_metrics(ticker, bypass_cache=refresh)
    except TypeError:
        return await ds.get_metrics(ticker)


async def _safe_price_history_lookup(ds: DataService, ticker: str, refresh: bool) -> list[dict[str, Any]]:
    try:
        return await ds.get_price_history(ticker, period="1y", bypass_cache=refresh)
    except TypeError:
        return await ds.get_price_history(ticker, period="1y")


def _format_range(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "N/A"
    return f"${low:.2f} - ${high:.2f}"


async def _hydrate_watch_items(
    items: list[WatchlistItem],
    ds: DataService,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    async def hydrate(item: WatchlistItem) -> dict[str, Any]:
        price = None
        change_pct = None
        pe = "N/A"
        range_52w = "N/A"

        try:
            price_info = await _safe_price_lookup(ds, item.ticker, refresh)
            raw_price = price_info.get("price")
            raw_change = price_info.get("change_pct")
            if raw_price is not None:
                price = float(raw_price)
            if raw_change is not None:
                change_pct = float(raw_change)
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Watchlist price lookup failed for %s: %s", item.ticker, exc)

        try:
            metrics = await _safe_metrics_lookup(ds, item.ticker, refresh)
            pe = str(metrics.get("pe") or "N/A")
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Watchlist metrics lookup failed for %s: %s", item.ticker, exc)

        try:
            history = await _safe_price_history_lookup(ds, item.ticker, refresh)
            closes = [float(row["close"]) for row in history if isinstance(row, dict) and row.get("close") is not None]
            if closes:
                range_52w = _format_range(min(closes), max(closes))
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Watchlist history lookup failed for %s: %s", item.ticker, exc)

        return {
            "item": item,
            "price": price,
            "change_pct": change_pct,
            "range_52w": range_52w,
            "pe": pe,
        }

    rows = await asyncio.gather(*(hydrate(item) for item in items))
    return list(rows)


async def _render_watchlist_table(
    request: Request,
    watchlist_id: int,
    db: Session,
    ds: DataService,
    sort_by: str = "ticker",
    sort_dir: str = "asc",
    refresh: bool = False,
) -> HTMLResponse:
    watchlist = db.get(Watchlist, watchlist_id)
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.ticker)
        .all()
    ) if watchlist else []
    watch_rows = await _hydrate_watch_items(items, ds, refresh=refresh)
    sort_by, sort_dir = _parse_sort(sort_by, sort_dir)
    watch_rows = _sort_watch_rows(watch_rows, sort_by, sort_dir)
    return templates.TemplateResponse("partials/watchlist_table.html", {
        "request": request,
        "active_watchlist": watchlist,
        "watch_rows": watch_rows,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    })


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(
    request: Request,
    watchlist_id: int | None = Query(None),
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    watchlists = db.query(Watchlist).order_by(Watchlist.name).all()
    if not watchlists:
        _get_or_create_default_watchlist(db)
        watchlists = db.query(Watchlist).order_by(Watchlist.name).all()

    active = db.get(Watchlist, watchlist_id) if watchlist_id else watchlists[0]
    if not active:
        active = watchlists[0]

    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == active.id)
        .order_by(WatchlistItem.ticker)
        .all()
    )
    watch_rows = await _hydrate_watch_items(items, ds, refresh=refresh)
    sort_by, sort_dir = _parse_sort(sort_by, sort_dir)
    watch_rows = _sort_watch_rows(watch_rows, sort_by, sort_dir)

    return templates.TemplateResponse("watchlist.html", {
        "request": request,
        "active_page": "watchlist",
        "watchlists": watchlists,
        "active_watchlist": active,
        "watch_rows": watch_rows,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "last_refreshed": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    })


@router.get("/hx/watchlist/table/{watchlist_id}", response_class=HTMLResponse)
async def watchlist_table(
    request: Request,
    watchlist_id: int,
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    return await _render_watchlist_table(
        request=request,
        watchlist_id=watchlist_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
        refresh=refresh,
    )


@router.post("/api/watchlists", response_class=HTMLResponse)
def create_watchlist(
    request: Request,
    name: str = Form(..., max_length=200),
    db: Session = Depends(get_db),
):
    _ = request
    wl = Watchlist(name=name)
    db.add(wl)
    db.commit()
    return RedirectResponse(f"/watchlist?watchlist_id={wl.id}", status_code=303)


@router.delete("/api/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    wl = db.get(Watchlist, watchlist_id)
    if wl:
        db.delete(wl)
        db.commit()
    return {"ok": True}


@router.post("/api/watchlist/add")
def quick_add_watchlist(
    symbol: str = Form(..., max_length=20, pattern=r"^\s*[A-Za-z0-9.\-]{1,10}\s*$"),
    watchlist_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    ticker_clean = symbol.upper().strip()
    if not ticker_clean:
        return {"ok": False, "error": "Missing symbol"}

    watchlist = db.get(Watchlist, watchlist_id) if watchlist_id else None
    if watchlist is None:
        watchlist = _get_or_create_default_watchlist(db)

    exists = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.ticker == ticker_clean)
        .first()
    )
    if not exists:
        db.add(WatchlistItem(watchlist_id=watchlist.id, ticker=ticker_clean))
        db.commit()
    return {"ok": True, "watchlist_id": watchlist.id, "ticker": ticker_clean}


@router.post("/api/watchlist-items", response_class=HTMLResponse)
async def add_watchlist_item(
    request: Request,
    watchlist_id: int = Form(...),
    ticker: str = Form(..., max_length=20, pattern=r"^\s*[A-Za-z0-9.\-]{1,10}\s*$"),
    notes: str = Form("", max_length=2000),
    sort_by: str = Form("ticker"),
    sort_dir: str = Form("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    ticker_clean = ticker.upper().strip()
    exists = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.ticker == ticker_clean)
        .first()
    )
    if not exists:
        item = WatchlistItem(
            watchlist_id=watchlist_id,
            ticker=ticker_clean,
            notes=notes or None,
        )
        db.add(item)
        db.commit()

    return await _render_watchlist_table(
        request=request,
        watchlist_id=watchlist_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.put("/api/watchlist-items/{item_id}", response_class=HTMLResponse)
async def update_watchlist_item(
    request: Request,
    item_id: int,
    notes: str = Form("", max_length=2000),
    sort_by: str = Form("ticker"),
    sort_dir: str = Form("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    item = db.get(WatchlistItem, item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    item.notes = notes or None
    db.commit()
    return await _render_watchlist_table(
        request=request,
        watchlist_id=item.watchlist_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.delete("/api/watchlist-items/{item_id}", response_class=HTMLResponse)
async def delete_watchlist_item(
    request: Request,
    item_id: int,
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    item = db.get(WatchlistItem, item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    watchlist_id = item.watchlist_id
    db.delete(item)
    db.commit()
    return await _render_watchlist_table(
        request=request,
        watchlist_id=watchlist_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
