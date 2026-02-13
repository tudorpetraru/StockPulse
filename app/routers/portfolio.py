"""Portfolio router — CRUD for portfolios and positions with HTMX table refresh.

Owned by Agent C.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Portfolio, Position

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Helpers ──


def _get_or_create_default_portfolio(db: Session) -> Portfolio:
    """Ensure at least one portfolio exists."""
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        portfolio = Portfolio(name="Main Portfolio")
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio


def _portfolio_stats(positions: list[Position]) -> dict:
    """Compute aggregate stats from a list of positions."""
    total_cost = sum(p.shares * p.avg_cost for p in positions)
    # Live prices come from DataService post-integration. Placeholder: value = cost.
    total_value = total_cost
    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0
    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "day_pl": 0,
        "day_pl_pct": 0,
    }


# ── Full Page ──


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(
    request: Request,
    portfolio_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    portfolios = db.query(Portfolio).order_by(Portfolio.name).all()
    if not portfolios:
        _get_or_create_default_portfolio(db)
        portfolios = db.query(Portfolio).order_by(Portfolio.name).all()

    if portfolio_id:
        active = db.get(Portfolio, portfolio_id)
    else:
        active = portfolios[0]

    if not active:
        active = portfolios[0]

    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == active.id)
        .order_by(Position.ticker)
        .all()
    )
    stats = _portfolio_stats(positions)

    return templates.TemplateResponse("portfolio.html", {
        "request": request,
        "active_page": "portfolio",
        "portfolios": portfolios,
        "active_portfolio": active,
        "positions": positions,
        "stats": stats,
    })


# ── HTMX Partial: positions table ──


@router.get("/hx/portfolio/table", response_class=HTMLResponse)
def portfolio_table(
    request: Request,
    portfolio_id: int = Query(...),
    db: Session = Depends(get_db),
):
    portfolio = db.get(Portfolio, portfolio_id)
    positions = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id)
        .order_by(Position.ticker)
        .all()
    ) if portfolio else []
    stats = _portfolio_stats(positions)

    return templates.TemplateResponse("partials/portfolio_table.html", {
        "request": request,
        "active_portfolio": portfolio,
        "positions": positions,
        "stats": stats,
    })


# ── CRUD: Create Portfolio ──


@router.post("/api/portfolios", response_class=HTMLResponse)
def create_portfolio(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    portfolio = Portfolio(name=name, description=description or None)
    db.add(portfolio)
    db.commit()
    return RedirectResponse(f"/portfolio?portfolio_id={portfolio.id}", status_code=303)


# ── CRUD: Delete Portfolio ──


@router.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio:
        db.delete(portfolio)
        db.commit()
    return {"ok": True}


# ── CRUD: Add Position ──


@router.post("/api/positions", response_class=HTMLResponse)
def add_position(
    request: Request,
    portfolio_id: int = Form(...),
    ticker: str = Form(...),
    shares: float = Form(...),
    avg_cost: float = Form(...),
    date_acquired: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
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

    # Return updated table via HTMX
    return portfolio_table(request, portfolio_id=portfolio_id, db=db)


# ── CRUD: Update Position ──


@router.put("/api/positions/{position_id}", response_class=HTMLResponse)
def update_position(
    request: Request,
    position_id: int,
    ticker: str = Form(...),
    shares: float = Form(...),
    avg_cost: float = Form(...),
    date_acquired: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
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
    return portfolio_table(request, portfolio_id=position.portfolio_id, db=db)


# ── CRUD: Delete Position ──


@router.delete("/api/positions/{position_id}", response_class=HTMLResponse)
def delete_position(
    request: Request,
    position_id: int,
    db: Session = Depends(get_db),
):
    position = db.get(Position, position_id)
    if not position:
        return HTMLResponse("Position not found", status_code=404)

    portfolio_id = position.portfolio_id
    db.delete(position)
    db.commit()
    return portfolio_table(request, portfolio_id=portfolio_id, db=db)
