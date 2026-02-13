"""Dashboard router — home page with summary cards.

Owned by Agent C.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Portfolio, Position, Watchlist, WatchlistItem

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _portfolio_summary(db: Session) -> dict:
    """Compute aggregate portfolio stats for the dashboard card."""
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        return {
            "total_value": 0,
            "total_cost": 0,
            "total_pl": 0,
            "total_pl_pct": 0,
            "day_pl": 0,
            "day_pl_pct": 0,
            "position_count": 0,
            "name": "No Portfolio",
        }

    positions = db.query(Position).filter(Position.portfolio_id == portfolio.id).all()
    total_cost = sum(p.shares * p.avg_cost for p in positions)
    # Current prices come from cache/provider once integrated with Agent A's DataService.
    # Placeholder: use avg_cost so P&L starts at 0.
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
        "position_count": len(positions),
        "name": portfolio.name,
    }


def _watchlist_movers(db: Session) -> list[dict]:
    """Get watchlist items for the movers card."""
    items = db.query(WatchlistItem).limit(6).all()
    return [
        {"ticker": item.ticker, "price": 0.0, "change_pct": 0.0}
        for item in items
    ]


def _recent_news() -> list[dict]:
    """Placeholder — will pull from pygooglenews / finviz via DataService."""
    return []


def _market_snapshot() -> list[dict]:
    """Placeholder — will pull index data from yfinance."""
    return [
        {"name": "S&P 500", "symbol": "^GSPC", "value": 0, "change_pct": 0},
        {"name": "NASDAQ", "symbol": "^IXIC", "value": 0, "change_pct": 0},
        {"name": "DOW", "symbol": "^DJI", "value": 0, "change_pct": 0},
    ]


def _prediction_widget(db: Session) -> dict:
    """Placeholder prediction tracker widget data."""
    return {
        "tracking": 0,
        "resolved_month": 0,
        "monthly_accuracy": None,
        "top_analysts": [],
        "recent_resolutions": [],
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "portfolio": _portfolio_summary(db),
        "movers": _watchlist_movers(db),
        "news": _recent_news(),
        "market": _market_snapshot(),
        "predictions": _prediction_widget(db),
    })
