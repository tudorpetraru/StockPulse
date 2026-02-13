"""Portfolio router — CRUD for portfolios and positions with live quote hydration."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_data_service
from app.errors import SERVICE_RECOVERABLE_ERRORS
from app.models.db_models import Portfolio, Position
from app.services.chart_service import build_portfolio_positions_chart, build_portfolio_sector_chart
from app.services.data_service import DataService

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_SORTABLE_FIELDS = {"ticker", "shares", "current", "value", "pl", "day_change"}


def _get_or_create_default_portfolio(db: Session) -> Portfolio:
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        portfolio = Portfolio(name="Main Portfolio")
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio


def _parse_sort(sort_by: str, sort_dir: str) -> tuple[str, str]:
    by = sort_by if sort_by in _SORTABLE_FIELDS else "ticker"
    direction = "desc" if sort_dir == "desc" else "asc"
    return by, direction


def _sort_position_rows(rows: list[dict[str, Any]], sort_by: str, sort_dir: str) -> list[dict[str, Any]]:
    by, direction = _parse_sort(sort_by, sort_dir)
    reverse = direction == "desc"
    if by == "ticker":
        return sorted(rows, key=lambda row: str(row["position"].ticker), reverse=reverse)
    return sorted(rows, key=lambda row: float(row.get(by) or 0.0), reverse=reverse)


def _compute_portfolio_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    total_cost = sum(float(row["cost"]) for row in rows)
    total_value = sum(float(row["value"]) for row in rows)
    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100.0) if total_cost > 0 else 0.0
    day_pl = sum(float(row["day_change"]) for row in rows)
    previous_value = total_value - day_pl
    day_pl_pct = (day_pl / previous_value * 100.0) if previous_value > 0 else 0.0
    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "day_pl": day_pl,
        "day_pl_pct": day_pl_pct,
    }


async def _safe_price_lookup(ds: DataService, ticker: str, refresh: bool) -> dict[str, Any]:
    try:
        return await ds.get_price(ticker, bypass_cache=refresh)
    except TypeError:
        return await ds.get_price(ticker)


async def _hydrate_positions(
    positions: list[Position],
    ds: DataService,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    async def hydrate(position: Position) -> dict[str, Any]:
        current = float(position.avg_cost)
        change_per_share = 0.0
        change_pct = 0.0
        try:
            price_info = await _safe_price_lookup(ds, position.ticker, refresh)
            current = float(price_info.get("price") or current)
            change_per_share = float(price_info.get("change") or 0.0)
            change_pct = float(price_info.get("change_pct") or 0.0)
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Portfolio quote lookup failed for %s: %s", position.ticker, exc)

        cost = float(position.shares * position.avg_cost)
        value = float(position.shares * current)
        pl = value - cost
        pl_pct = (pl / cost * 100.0) if cost > 0 else 0.0
        day_change = float(position.shares * change_per_share)
        return {
            "position": position,
            "current": current,
            "value": value,
            "cost": cost,
            "pl": pl,
            "pl_pct": pl_pct,
            "day_change": day_change,
            "day_change_pct": change_pct,
            "shares": float(position.shares),
        }

    rows = await asyncio.gather(*(hydrate(position) for position in positions))
    return list(rows)


async def _render_portfolio_table(
    request: Request,
    portfolio_id: int,
    db: Session,
    ds: DataService,
    sort_by: str = "ticker",
    sort_dir: str = "asc",
    refresh: bool = False,
) -> HTMLResponse:
    portfolio = db.get(Portfolio, portfolio_id)
    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id)
        .order_by(Position.ticker)
        .all()
    ) if portfolio else []
    quote_rows = await _hydrate_positions(positions, ds, refresh=refresh)
    sort_by, sort_dir = _parse_sort(sort_by, sort_dir)
    quote_rows = _sort_position_rows(quote_rows, sort_by, sort_dir)
    stats = _compute_portfolio_stats(quote_rows)
    return templates.TemplateResponse("partials/portfolio_table.html", {
        "request": request,
        "active_portfolio": portfolio,
        "quote_rows": quote_rows,
        "stats": stats,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "last_refreshed": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    })


@router.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(
    request: Request,
    portfolio_id: int | None = Query(None),
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    portfolios = db.query(Portfolio).order_by(Portfolio.name).all()
    if not portfolios:
        _get_or_create_default_portfolio(db)
        portfolios = db.query(Portfolio).order_by(Portfolio.name).all()

    active = db.get(Portfolio, portfolio_id) if portfolio_id else portfolios[0]
    if not active:
        active = portfolios[0]

    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == active.id)
        .order_by(Position.ticker)
        .all()
    )
    quote_rows = await _hydrate_positions(positions, ds, refresh=refresh)
    sort_by, sort_dir = _parse_sort(sort_by, sort_dir)
    quote_rows = _sort_position_rows(quote_rows, sort_by, sort_dir)
    stats = _compute_portfolio_stats(quote_rows)

    return templates.TemplateResponse("portfolio.html", {
        "request": request,
        "active_page": "portfolio",
        "portfolios": portfolios,
        "active_portfolio": active,
        "quote_rows": quote_rows,
        "stats": stats,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "last_refreshed": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    })


@router.get("/hx/portfolio/table", response_class=HTMLResponse)
async def portfolio_table(
    request: Request,
    portfolio_id: int = Query(...),
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    return await _render_portfolio_table(
        request=request,
        portfolio_id=portfolio_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
        refresh=refresh,
    )


@router.get("/api/chart/portfolio/{portfolio_id}/sector")
async def portfolio_sector_chart(
    portfolio_id: int,
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id)
        .order_by(Position.ticker)
        .all()
    )
    quote_rows = await _hydrate_positions(positions, ds, refresh=False)
    if not quote_rows:
        return JSONResponse(content=build_portfolio_sector_chart([]))

    profiles = await asyncio.gather(
        *(ds.get_profile(row["position"].ticker) for row in quote_rows),
        return_exceptions=True,
    )
    by_sector: dict[str, float] = {}
    for row, profile in zip(quote_rows, profiles, strict=False):
        sector = "N/A"
        if isinstance(profile, dict):
            sector = str(profile.get("sector") or "N/A")
        value = float(row["value"])
        by_sector[sector] = by_sector.get(sector, 0.0) + value

    points = [{"label": sector, "value": value} for sector, value in by_sector.items() if value > 0]
    return JSONResponse(content=build_portfolio_sector_chart(points))


@router.get("/api/chart/portfolio/{portfolio_id}/positions")
async def portfolio_positions_chart(
    portfolio_id: int,
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id)
        .order_by(Position.ticker)
        .all()
    )
    quote_rows = await _hydrate_positions(positions, ds, refresh=False)
    points = [
        {"label": row["position"].ticker, "value": float(row["value"])}
        for row in quote_rows
        if float(row["value"]) > 0
    ]
    return JSONResponse(content=build_portfolio_positions_chart(points))


@router.post("/api/portfolios", response_class=HTMLResponse)
def create_portfolio(
    request: Request,
    name: str = Form(..., max_length=200),
    description: str = Form("", max_length=2000),
    db: Session = Depends(get_db),
):
    _ = request
    portfolio = Portfolio(name=name, description=description or None)
    db.add(portfolio)
    db.commit()
    return RedirectResponse(f"/portfolio?portfolio_id={portfolio.id}", status_code=303)


@router.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio:
        db.delete(portfolio)
        db.commit()
    return {"ok": True}


@router.post("/api/positions", response_class=HTMLResponse)
async def add_position(
    request: Request,
    portfolio_id: int = Form(...),
    ticker: str = Form(..., max_length=20, pattern=r"^\s*[A-Za-z0-9.\-]{1,10}\s*$"),
    shares: float = Form(..., gt=0, le=1e9),
    avg_cost: float = Form(..., ge=0, le=1e9),
    date_acquired: str = Form(""),
    notes: str = Form("", max_length=2000),
    sort_by: str = Form("ticker"),
    sort_dir: str = Form("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    acquired = None
    if date_acquired:
        try:
            acquired = date.fromisoformat(date_acquired)
        except ValueError:
            pass

    position = Position(
        portfolio_id=portfolio_id,
        ticker=ticker.upper().strip(),
        shares=shares,
        avg_cost=avg_cost,
        date_acquired=acquired,
        notes=notes or None,
    )
    db.add(position)
    db.commit()

    return await _render_portfolio_table(
        request=request,
        portfolio_id=portfolio_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.put("/api/positions/{position_id}", response_class=HTMLResponse)
async def update_position(
    request: Request,
    position_id: int,
    ticker: str = Form(..., max_length=20, pattern=r"^\s*[A-Za-z0-9.\-]{1,10}\s*$"),
    shares: float = Form(..., gt=0, le=1e9),
    avg_cost: float = Form(..., ge=0, le=1e9),
    date_acquired: str = Form(""),
    notes: str = Form("", max_length=2000),
    sort_by: str = Form("ticker"),
    sort_dir: str = Form("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    position = db.get(Position, position_id)
    if not position:
        return HTMLResponse("Position not found", status_code=404)

    position.ticker = ticker.upper().strip()
    position.shares = shares
    position.avg_cost = avg_cost
    position.notes = notes or None
    if date_acquired:
        try:
            position.date_acquired = date.fromisoformat(date_acquired)
        except ValueError:
            pass
    db.commit()

    return await _render_portfolio_table(
        request=request,
        portfolio_id=position.portfolio_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.delete("/api/positions/{position_id}", response_class=HTMLResponse)
async def delete_position(
    request: Request,
    position_id: int,
    sort_by: str = Query("ticker"),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
):
    position = db.get(Position, position_id)
    if not position:
        return HTMLResponse("Position not found", status_code=404)

    portfolio_id = position.portfolio_id
    db.delete(position)
    db.commit()
    return await _render_portfolio_table(
        request=request,
        portfolio_id=portfolio_id,
        db=db,
        ds=ds,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
