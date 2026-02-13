"""Watchlist router — multiple named watchlists with CRUD and HTMX table refresh.

Owned by Agent C.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Watchlist, WatchlistItem

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_or_create_default_watchlist(db: Session) -> Watchlist:
    wl = db.query(Watchlist).first()
    if not wl:
        wl = Watchlist(name="My Watchlist")
        db.add(wl)
        db.commit()
        db.refresh(wl)
    return wl


# ── Full Page ──


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(
    request: Request,
    watchlist_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    watchlists = db.query(Watchlist).order_by(Watchlist.name).all()
    if not watchlists:
        _get_or_create_default_watchlist(db)
        watchlists = db.query(Watchlist).order_by(Watchlist.name).all()

    if watchlist_id:
        active = db.get(Watchlist, watchlist_id)
    else:
        active = watchlists[0]

    if not active:
        active = watchlists[0]

    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == active.id)
        .order_by(WatchlistItem.ticker)
        .all()
    )

    return templates.TemplateResponse("watchlist.html", {
        "request": request,
        "active_page": "watchlist",
        "watchlists": watchlists,
        "active_watchlist": active,
        "items": items,
    })


# ── HTMX Partial: watchlist table ──


@router.get("/hx/watchlist/table/{watchlist_id}", response_class=HTMLResponse)
def watchlist_table(
    request: Request,
    watchlist_id: int,
    db: Session = Depends(get_db),
):
    watchlist = db.get(Watchlist, watchlist_id)
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.ticker)
        .all()
    ) if watchlist else []

    return templates.TemplateResponse("partials/watchlist_table.html", {
        "request": request,
        "active_watchlist": watchlist,
        "items": items,
    })


# ── CRUD: Create Watchlist ──


@router.post("/api/watchlists", response_class=HTMLResponse)
def create_watchlist(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    wl = Watchlist(name=name)
    db.add(wl)
    db.commit()
    return RedirectResponse(f"/watchlist?watchlist_id={wl.id}", status_code=303)


# ── CRUD: Delete Watchlist ──


@router.delete("/api/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    wl = db.get(Watchlist, watchlist_id)
    if wl:
        db.delete(wl)
        db.commit()
    return {"ok": True}


# ── CRUD: Add Item ──


@router.post("/api/watchlist-items", response_class=HTMLResponse)
def add_watchlist_item(
    request: Request,
    watchlist_id: int = Form(...),
    ticker: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
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

    return watchlist_table(request, watchlist_id=watchlist_id, db=db)


# ── CRUD: Update Item Notes ──


@router.put("/api/watchlist-items/{item_id}", response_class=HTMLResponse)
def update_watchlist_item(
    request: Request,
    item_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    item = db.get(WatchlistItem, item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    item.notes = notes or None
    db.commit()
    return watchlist_table(request, watchlist_id=item.watchlist_id, db=db)


# ── CRUD: Remove Item ──


@router.delete("/api/watchlist-items/{item_id}", response_class=HTMLResponse)
def delete_watchlist_item(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    item = db.get(WatchlistItem, item_id)
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    watchlist_id = item.watchlist_id
    db.delete(item)
    db.commit()
    return watchlist_table(request, watchlist_id=watchlist_id, db=db)
