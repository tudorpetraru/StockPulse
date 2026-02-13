"""
Ticker router — full page + HTMX partials + chart JSON APIs.

Depends on Agent A's DataService and PredictionService.  Until that
branch is merged we use lightweight stubs (see _stubs module below).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.services.chart_service import build_price_chart, build_consensus_chart

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Agent-A interfaces (stubbed until rebase) ─────────────────────────────

try:
    from app.services.data_service import DataService  # type: ignore[import]
    from app.services.prediction_service import PredictionService  # type: ignore[import]
except ImportError:

    class DataService:  # type: ignore[no-redef]
        """Minimal stub – every method returns empty/sensible defaults."""

        async def get_profile(self, symbol: str) -> dict[str, Any]:
            return {
                "name": symbol, "symbol": symbol, "sector": "N/A",
                "industry": "N/A", "exchange": "N/A", "description": "",
            }

        async def get_price(self, symbol: str) -> dict[str, Any]:
            return {"price": 0.0, "change": 0.0, "change_pct": 0.0, "updated": "N/A"}

        async def get_metrics(self, symbol: str) -> dict[str, Any]:
            keys = [
                "pe", "fwd_pe", "peg", "mkt_cap", "ev_ebitda", "beta",
                "ps", "pb", "roe", "profit_margin", "debt_equity", "insider_own",
            ]
            return {k: "N/A" for k in keys}

        async def get_analyst_ratings(self, symbol: str) -> dict[str, Any]:
            return {"consensus": "N/A", "count": 0, "low": "N/A",
                     "avg": "N/A", "high": "N/A", "ratings": []}

        async def get_financials(self, symbol: str, period: str = "annual") -> dict[str, Any]:
            return {"income": [], "balance": [], "cashflow": []}

        async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
            return []

        async def get_insider_trades(self, symbol: str) -> list[dict[str, Any]]:
            return []

        async def get_holders(self, symbol: str) -> dict[str, Any]:
            return {"institutional": [], "mutual_fund": []}

        async def get_earnings(self, symbol: str) -> dict[str, Any]:
            return {"history": [], "next_date": "N/A"}

        async def get_price_history(self, symbol: str, period: str = "1y") -> list[dict[str, Any]]:
            return []

        async def get_peers(self, symbol: str) -> list[dict[str, Any]]:
            return []

    class PredictionService:  # type: ignore[no-redef]
        async def get_analyst_scorecard(self, symbol: str) -> list[dict[str, Any]]:
            return []

        async def get_consensus_history(self, symbol: str) -> list[dict[str, Any]]:
            return []

        async def get_prediction_summary(self, symbol: str) -> dict[str, Any]:
            return {"active": 0, "resolved": 0, "accuracy": None, "consensus_target": "N/A"}

        async def get_prediction_history(self, symbol: str) -> list[dict[str, Any]]:
            return []


def _get_data_service() -> DataService:
    return DataService()


def _get_prediction_service() -> PredictionService:
    return PredictionService()


# ── Jinja2 helper ─────────────────────────────────────────────────────────

def _templates():
    """Lazy import to avoid circular deps during test collection."""
    from fastapi.templating import Jinja2Templates
    return Jinja2Templates(directory="app/templates")


# ── Full page ─────────────────────────────────────────────────────────────

@router.get("/ticker/{symbol}", response_class=HTMLResponse)
async def ticker_page(
    request: Request,
    symbol: str,
    ds: DataService = Depends(_get_data_service),
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
    except Exception:
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
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_financials(symbol, period)
        status = "ok"
    except Exception:
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
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_analyst_ratings(symbol)
        status = "ok"
    except Exception:
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
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        items = await ds.get_news(symbol)
        status = "ok"
    except Exception:
        logger.exception("news error %s", symbol)
        items = []
        status = "error"
    return templates.TemplateResponse("partials/ticker_news.html", {
        "request": request, "symbol": symbol, "news": items, "status": status,
    })


@router.get("/hx/ticker/{symbol}/insiders", response_class=HTMLResponse)
async def hx_insiders(
    request: Request, symbol: str,
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        trades = await ds.get_insider_trades(symbol)
        status = "ok"
    except Exception:
        logger.exception("insiders error %s", symbol)
        trades = []
        status = "error"
    return templates.TemplateResponse("partials/ticker_insiders.html", {
        "request": request, "symbol": symbol, "insiders": trades, "status": status,
    })


@router.get("/hx/ticker/{symbol}/holders", response_class=HTMLResponse)
async def hx_holders(
    request: Request, symbol: str,
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_holders(symbol)
        status = "ok"
    except Exception:
        logger.exception("holders error %s", symbol)
        data = {"institutional": [], "mutual_fund": []}
        status = "error"
    return templates.TemplateResponse("partials/ticker_holders.html", {
        "request": request, "symbol": symbol, "holders": data, "status": status,
    })


@router.get("/hx/ticker/{symbol}/earnings", response_class=HTMLResponse)
async def hx_earnings(
    request: Request, symbol: str,
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        data = await ds.get_earnings(symbol)
        status = "ok"
    except Exception:
        logger.exception("earnings error %s", symbol)
        data = {"history": [], "next_date": "N/A"}
        status = "error"
    return templates.TemplateResponse("partials/ticker_earnings.html", {
        "request": request, "symbol": symbol, "earnings": data, "status": status,
    })


@router.get("/hx/ticker/{symbol}/predictions", response_class=HTMLResponse)
async def hx_predictions(
    request: Request, symbol: str,
    ps: PredictionService = Depends(_get_prediction_service),
):
    symbol = symbol.upper()
    templates = _templates()
    try:
        summary = await ps.get_prediction_summary(symbol)
        scorecard = await ps.get_analyst_scorecard(symbol)
        history = await ps.get_prediction_history(symbol)
        status = "ok"
    except Exception:
        logger.exception("predictions error %s", symbol)
        summary = {"active": 0, "resolved": 0, "accuracy": None, "consensus_target": "N/A"}
        scorecard = []
        history = []
        status = "error"

    cold_start = summary.get("resolved", 0) == 0
    return templates.TemplateResponse("partials/ticker_predictions.html", {
        "request": request, "symbol": symbol,
        "summary": summary, "scorecard": scorecard,
        "predictions": history, "cold_start": cold_start,
        "status": status,
    })


# ── Chart JSON APIs ──────────────────────────────────────────────────────

@router.get("/api/chart/{symbol}/price")
async def chart_price(
    symbol: str, period: str = Query("1Y"),
    ds: DataService = Depends(_get_data_service),
):
    symbol = symbol.upper()
    from app.services.chart_service import yfinance_period
    yf_period = yfinance_period(period)
    try:
        history = await ds.get_price_history(symbol, period=yf_period)
    except Exception:
        history = []
    chart = build_price_chart(history, symbol, period)
    return JSONResponse(content=chart)


@router.get("/api/chart/{symbol}/consensus")
async def chart_consensus(
    symbol: str, period: str = Query("2Y"),
    ds: DataService = Depends(_get_data_service),
    ps: PredictionService = Depends(_get_prediction_service),
):
    symbol = symbol.upper()
    try:
        prices = await ds.get_price_history(symbol, period="2y")
        snapshots = await ps.get_consensus_history(symbol)
    except Exception:
        prices, snapshots = [], []
    chart = build_consensus_chart(
        [{"date": p["date"], "close": p["close"]} for p in prices],
        snapshots, symbol, period,
    )
    return JSONResponse(content=chart)
