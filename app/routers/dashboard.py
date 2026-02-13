"""Dashboard router — home page with summary cards.

Owned by Agent C.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_data_service, get_prediction_service
from app.errors import SERVICE_RECOVERABLE_ERRORS
from app.models.db_models import AnalystSnapshot, ConsensusSnapshot, Portfolio, Position, WatchlistItem
from app.services.data_service import DataService
from app.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _price_metrics(ds: DataService, symbol: str) -> tuple[float, float, float]:
    """Return (last_price, prev_price, change_pct)."""
    history = await ds.get_price_history(symbol, period="5d")
    closes = [float(item.get("close", 0.0)) for item in history if isinstance(item, dict) and item.get("close") is not None]
    if len(closes) >= 2:
        last_price = closes[-1]
        prev_price = closes[-2]
        change_pct = ((last_price - prev_price) / prev_price * 100.0) if prev_price else 0.0
        return last_price, prev_price, change_pct

    if len(closes) == 1:
        return closes[0], closes[0], 0.0

    fallback = await ds.get_price(symbol)
    price = float(fallback.get("price") or 0.0)
    pct = float(fallback.get("change_pct") or 0.0)
    prev = price / (1 + (pct / 100.0)) if pct != -100 else price
    return price, prev, pct


async def _portfolio_summary(db: Session, ds: DataService) -> dict:
    """Compute aggregate portfolio stats for the dashboard card using current prices."""
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
    if not positions:
        return {
            "total_value": 0,
            "total_cost": 0,
            "total_pl": 0,
            "total_pl_pct": 0,
            "day_pl": 0,
            "day_pl_pct": 0,
            "position_count": 0,
            "name": portfolio.name,
        }

    price_rows = await asyncio.gather(
        *(_price_metrics(ds, position.ticker.upper()) for position in positions),
        return_exceptions=True,
    )

    total_cost = sum(p.shares * p.avg_cost for p in positions)
    total_value = 0.0
    day_pl = 0.0
    for position, price_row in zip(positions, price_rows, strict=False):
        if isinstance(price_row, Exception):
            logger.warning("Portfolio price lookup failed for %s: %s", position.ticker, price_row)
            latest = position.avg_cost
            previous = position.avg_cost
        else:
            latest, previous, _ = price_row
        total_value += latest * position.shares
        day_pl += (latest - previous) * position.shares

    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0
    day_base = total_value - day_pl
    day_pl_pct = (day_pl / day_base * 100) if day_base > 0 else 0.0

    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "day_pl": day_pl,
        "day_pl_pct": day_pl_pct,
        "position_count": len(positions),
        "name": portfolio.name,
    }


async def _watchlist_movers(db: Session, ds: DataService) -> list[dict]:
    """Get watchlist movers ranked by absolute daily change."""
    items = db.query(WatchlistItem).order_by(WatchlistItem.added_at.desc()).limit(12).all()
    symbols: list[str] = []
    for item in items:
        ticker = item.ticker.upper()
        if ticker not in symbols:
            symbols.append(ticker)
        if len(symbols) >= 6:
            break

    movers: list[dict] = []
    for symbol in symbols:
        try:
            latest, _, change_pct = await _price_metrics(ds, symbol)
            movers.append({"ticker": symbol, "price": latest, "change_pct": change_pct})
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Watchlist mover lookup failed for %s: %s", symbol, exc)
            movers.append({"ticker": symbol, "price": 0.0, "change_pct": 0.0})
    return sorted(movers, key=lambda row: abs(float(row.get("change_pct", 0.0))), reverse=True)[:6]


async def _recent_news(db: Session, ds: DataService) -> list[dict]:
    tickers = [row[0].upper() for row in db.query(Position.ticker).distinct().all()[:3]]
    if not tickers:
        tickers = [row[0].upper() for row in db.query(WatchlistItem.ticker).distinct().all()[:3]]
    if not tickers:
        tickers = ["SPY"]

    batches = await asyncio.gather(*(ds.get_news(ticker, limit=3) for ticker in tickers), return_exceptions=True)
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ticker, batch in zip(tickers, batches, strict=False):
        if isinstance(batch, Exception):
            logger.warning("Dashboard news lookup failed for %s: %s", ticker, batch)
            continue
        for row in batch:
            if not isinstance(row, dict):
                continue
            url = str(row.get("link") or row.get("url") or "").strip()
            title = str(row.get("title") or "").strip()
            key = (url, title)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "title": title or "Untitled",
                    "url": url or "#",
                    "source": row.get("source") or "Unknown",
                    "published": row.get("date") or row.get("published") or row.get("time_ago") or "recent",
                    "ticker": row.get("ticker") or ticker,
                }
            )
    return items[:5]


async def _market_snapshot(ds: DataService) -> list[dict]:
    symbols = [
        ("S&P 500", "^GSPC"),
        ("NASDAQ", "^IXIC"),
        ("DOW", "^DJI"),
    ]
    rows: list[dict] = []
    for name, symbol in symbols:
        try:
            last_price, _, change_pct = await _price_metrics(ds, symbol)
            rows.append({"name": name, "symbol": symbol, "value": last_price, "change_pct": change_pct})
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Market snapshot lookup failed for %s: %s", symbol, exc)
            rows.append({"name": name, "symbol": symbol, "value": 0, "change_pct": 0})
    return rows


async def _prediction_widget(db: Session, ps: PredictionService) -> dict:
    """Prediction tracker widget data from DB + prediction service."""
    now = datetime.now(UTC).date()
    month_start = now.replace(day=1)

    tracking = (
        db.query(AnalystSnapshot)
        .filter(AnalystSnapshot.actual_price_at_target.is_(None), AnalystSnapshot.is_unresolvable.is_(False))
        .count()
    )
    resolved_month = (
        db.query(AnalystSnapshot)
        .filter(
            AnalystSnapshot.actual_price_at_target.is_not(None),
            AnalystSnapshot.target_date >= month_start,
            AnalystSnapshot.target_date <= now,
        )
        .count()
    )

    monthly_consensus = (
        db.query(ConsensusSnapshot)
        .filter(
            ConsensusSnapshot.consensus_was_correct.is_not(None),
            ConsensusSnapshot.target_date >= month_start,
            ConsensusSnapshot.target_date <= now,
        )
        .all()
    )
    monthly_accuracy = None
    if monthly_consensus:
        monthly_accuracy = (
            sum(1 for row in monthly_consensus if row.consensus_was_correct is True) / len(monthly_consensus)
        ) * 100.0

    leaderboard = await ps.get_top_analysts()
    top_analysts = [{"firm": row["firm"], "score": round(float(row.get("composite", 0.0)))} for row in leaderboard[:3]]

    return {
        "tracking": tracking,
        "resolved_month": resolved_month,
        "monthly_accuracy": monthly_accuracy,
        "top_analysts": top_analysts,
        "recent_resolutions": [],
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    ds: DataService = Depends(get_data_service),
    ps: PredictionService = Depends(get_prediction_service),
):
    portfolio, movers, news, market, predictions = await asyncio.gather(
        _portfolio_summary(db, ds),
        _watchlist_movers(db, ds),
        _recent_news(db, ds),
        _market_snapshot(ds),
        _prediction_widget(db, ps),
    )
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "portfolio": portfolio,
        "movers": movers,
        "news": news,
        "market": market,
        "predictions": predictions,
    })
