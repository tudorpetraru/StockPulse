"""
Ticker router — full page + HTMX partials + chart JSON APIs.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.dependencies import get_data_service, get_prediction_service
from app.errors import ROUTE_RECOVERABLE_ERRORS
from app.services.chart_service import build_price_chart, build_consensus_chart
from app.services.data_service import DataService
from app.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)
router = APIRouter()
_CONSENSUS_PERIOD_TO_YF = {"1Y": "1y", "2Y": "2y", "ALL": "max"}
_CONSENSUS_PERIOD_TO_DAYS = {"1Y": 365, "2Y": 730}

# ── Jinja2 helper ─────────────────────────────────────────────────────────

def _templates():
    """Lazy import to avoid circular deps during test collection."""
    from fastapi.templating import Jinja2Templates
    return Jinja2Templates(directory="app/templates")


def _parse_iso_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text.split("T", 1)[0])
    except ValueError:
        return None


# ── Full page ─────────────────────────────────────────────────────────────

@router.get("/ticker/{symbol}", response_class=HTMLResponse)
async def ticker_page(
    request: Request,
    symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()

    try:
        profile = await ds.get_profile(symbol)
        price_info = await ds.get_price(symbol)
        metrics = await ds.get_metrics(symbol)
        analysts = await ds.get_analyst_ratings(symbol)
        peers = await ds.get_peers(symbol)
        history = await ds.get_price_history(symbol, period="1y")
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("Error fetching ticker data for %s", symbol)
        profile = {"name": symbol, "symbol": symbol, "sector": "N/A",
                    "industry": "N/A", "exchange": "N/A", "description": ""}
        price_info = {"price": 0, "change": 0, "change_pct": 0, "updated": "N/A"}
        metrics = {k: "N/A" for k in [
            "pe", "fwd_pe", "peg", "mkt_cap", "ev_ebitda", "beta",
            "ps", "pb", "roe", "profit_margin", "debt_equity", "insider_own",
        ]}
        analysts = {"consensus": "N/A", "count": 0, "low": "N/A",
                     "avg": "N/A", "high": "N/A", "ratings": []}
        peers = []
        history = []

    price_chart = build_price_chart(history, symbol, "1Y")

    return templates.TemplateResponse("ticker.html", {
        "request": request,
        "symbol": symbol,
        "profile": profile,
        "price": price_info,
        "metrics": metrics,
        "analysts": analysts,
        "peers": peers,
        "price_chart": price_chart,
    })


# ── HTMX partials ────────────────────────────────────────────────────────

@router.get("/hx/ticker/{symbol}/financials", response_class=HTMLResponse)
async def hx_financials(
    request: Request,
    symbol: str,
    period: str = Query("annual"),
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_financials(symbol, period)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("financials error %s", symbol)
        data = {"income": [], "balance": [], "cashflow": []}
        status = "error"
    return templates.TemplateResponse("partials/ticker_financials.html", {
        "request": request, "symbol": symbol, "financials": data,
        "period": period, "status": status,
    })


@router.get("/hx/ticker/{symbol}/analysts", response_class=HTMLResponse)
async def hx_analysts(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_analyst_ratings(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("analysts error %s", symbol)
        data = {"consensus": "N/A", "count": 0, "low": "N/A",
                 "avg": "N/A", "high": "N/A", "ratings": []}
        status = "error"
    return templates.TemplateResponse("partials/ticker_overview.html", {
        "request": request, "symbol": symbol, "analysts": data, "status": status,
    })


@router.get("/hx/ticker/{symbol}/news", response_class=HTMLResponse)
async def hx_news(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        items = await ds.get_news(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("news error %s", symbol)
        items = []
        status = "error"
    return templates.TemplateResponse("partials/ticker_news.html", {
        "request": request, "symbol": symbol, "news": items, "status": status,
    })


@router.get("/hx/ticker/{symbol}/insiders", response_class=HTMLResponse)
async def hx_insiders(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        trades = await ds.get_insider_trades(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("insiders error %s", symbol)
        trades = []
        status = "error"
    return templates.TemplateResponse("partials/ticker_insiders.html", {
        "request": request, "symbol": symbol, "insiders": trades, "status": status,
    })


@router.get("/hx/ticker/{symbol}/holders", response_class=HTMLResponse)
async def hx_holders(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_holders(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("holders error %s", symbol)
        data = {"institutional": [], "mutual_fund": []}
        status = "error"
    return templates.TemplateResponse("partials/ticker_holders.html", {
        "request": request, "symbol": symbol, "holders": data, "status": status,
    })


@router.get("/hx/ticker/{symbol}/earnings", response_class=HTMLResponse)
async def hx_earnings(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_earnings(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("earnings error %s", symbol)
        data = {"history": [], "next_date": "N/A"}
        status = "error"
    return templates.TemplateResponse("partials/ticker_earnings.html", {
        "request": request, "symbol": symbol, "earnings": data, "status": status,
    })


@router.get("/hx/ticker/{symbol}/predictions", response_class=HTMLResponse)
async def hx_predictions(
    request: Request, symbol: str,
    ds: DataService = Depends(get_data_service),
    ps: PredictionService = Depends(get_prediction_service),
):
    symbol = symbol.upper()
    templates = _templates()
    settings = get_settings()
    schedule_hour = int(settings.prediction_snapshot_hour_et)
    display_hour = schedule_hour % 12 or 12
    am_pm = "AM" if schedule_hour < 12 else "PM"
    prediction_schedule_text = f"Mon-Fri at {display_hour}:00 {am_pm} ET"
    try:
        summary = await ps.get_prediction_summary(symbol)
        # Keep "Current Consensus Target" aligned with the live analyst panel
        # shown on ticker overview to avoid mixed-source discrepancies.
        analysts = await ds.get_analyst_ratings(symbol)
        live_avg = analysts.get("avg") if isinstance(analysts, dict) else None
        if live_avg and str(live_avg) != "N/A":
            live_avg_text = str(live_avg)
            summary["consensus_target"] = live_avg_text if live_avg_text.startswith("$") else f"${live_avg_text}"
        scorecard = await ps.get_analyst_scorecard(symbol)
        history = await ps.get_prediction_history(symbol)
        status = "ok"
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("predictions error %s", symbol)
        summary = {"active": 0, "resolved": 0, "accuracy": None, "consensus_target": "N/A"}
        scorecard = []
        history = []
        status = "error"

    cold_start = summary.get("resolved", 0) == 0
    auto_snapshot_on_load = status == "ok" and len(history) == 0
    return templates.TemplateResponse("partials/ticker_predictions.html", {
        "request": request, "symbol": symbol,
        "summary": summary, "scorecard": scorecard,
        "predictions": history, "cold_start": cold_start,
        "prediction_schedule_text": prediction_schedule_text,
        "auto_snapshot_on_load": auto_snapshot_on_load,
        "status": status,
    })


# ── Chart JSON APIs ──────────────────────────────────────────────────────

@router.get("/api/chart/{symbol}/price")
async def chart_price(
    symbol: str, period: str = Query("1Y"),
    ds: DataService = Depends(get_data_service),
):
    symbol = symbol.upper()
    from app.services.chart_service import yfinance_period
    yf_period = yfinance_period(period)
    try:
        history = await ds.get_price_history(symbol, period=yf_period)
    except ROUTE_RECOVERABLE_ERRORS:
        history = []
    chart = build_price_chart(history, symbol, period)
    return JSONResponse(content=chart)


@router.get("/api/chart/{symbol}/consensus")
async def chart_consensus(
    symbol: str, period: str = Query("2Y"),
    ds: DataService = Depends(get_data_service),
    ps: PredictionService = Depends(get_prediction_service),
):
    symbol = symbol.upper()
    period_label = (period or "2Y").upper()
    if period_label not in _CONSENSUS_PERIOD_TO_YF:
        period_label = "2Y"
    yf_period = _CONSENSUS_PERIOD_TO_YF[period_label]
    try:
        prices = await ds.get_price_history(symbol, period=yf_period)
        snapshots = await ps.get_consensus_history(symbol)
    except ROUTE_RECOVERABLE_ERRORS:
        prices, snapshots = [], []

    lookback_days = _CONSENSUS_PERIOD_TO_DAYS.get(period_label)
    if lookback_days is not None:
        cutoff = date.today() - timedelta(days=lookback_days)
        prices = [row for row in prices if (_parse_iso_date(row.get("date")) or date.min) >= cutoff]
        snapshots = [row for row in snapshots if (_parse_iso_date(row.get("date")) or date.min) >= cutoff]

    period_text = "All" if period_label == "ALL" else period_label
    chart = build_consensus_chart(
        [{"date": p["date"], "close": p["close"]} for p in prices],
        snapshots, symbol, period_text,
    )
    return JSONResponse(content=chart)
