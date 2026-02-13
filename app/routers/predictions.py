"""
Predictions router — API endpoints + analyst leaderboard page.

Scoring constants (from IMPLEMENTATION_PLAN §4 shared contracts):
  - Success threshold: abs(error) < 0.10
  - Minimum resolved: 5
  - Composite: 0.4*success + 0.3*directional + 0.3*(1 - abs_error), clamped 0..1
  - Badge colours: ≥70 green, 50-69 amber, <50 red
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.dependencies import get_prediction_service
from app.errors import ROUTE_RECOVERABLE_ERRORS
from app.middleware.rate_limit import limiter
from app.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)
router = APIRouter()

def _templates():
    from fastapi.templating import Jinja2Templates
    return Jinja2Templates(directory="app/templates")


# ── Prediction API endpoints ─────────────────────────────────────────────

@router.get("/api/predictions/{symbol}/analysts")
async def prediction_analysts(
    symbol: str,
    ps: PredictionService = Depends(get_prediction_service),
):
    """Analyst scorecard for a specific ticker, ranked by composite score."""
    symbol = symbol.upper()
    try:
        data = await ps.get_analyst_scorecard(symbol)
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("prediction_analysts error %s", symbol)
        data = []
    return JSONResponse(content=data)


@router.get("/api/predictions/{symbol}/consensus-history")
async def prediction_consensus_history(
    symbol: str,
    ps: PredictionService = Depends(get_prediction_service),
):
    """Consensus snapshots for the symbol (used by consensus chart)."""
    symbol = symbol.upper()
    try:
        data = await ps.get_consensus_history(symbol)
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("consensus_history error %s", symbol)
        data = []
    return JSONResponse(content=data)


@router.get("/api/predictions/top-analysts")
async def prediction_top_analysts(
    sector: str | None = Query(None),
    symbol: str | None = Query(None),
    ps: PredictionService = Depends(get_prediction_service),
):
    """Global analyst leaderboard. Optional sector/symbol filters."""
    try:
        data = await ps.get_top_analysts(sector=sector, symbol=symbol)
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("top_analysts error")
        data = []
    return JSONResponse(content=data)


@router.get("/api/predictions/{symbol}/analyst/{firm}")
async def prediction_firm_history(
    symbol: str,
    firm: str,
    ps: PredictionService = Depends(get_prediction_service),
):
    """Prediction history for one firm on one ticker."""
    symbol = symbol.upper()
    try:
        data = await ps.get_firm_history(symbol, firm)
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("firm_history error %s %s", symbol, firm)
        data = []
    return JSONResponse(content=data)


@router.post("/api/predictions/snapshot/run")
@limiter.limit("2/minute")
async def prediction_snapshot_run(
    request: Request,
    ps: PredictionService = Depends(get_prediction_service),
):
    """Trigger a manual prediction snapshot run."""
    _ = request
    try:
        result = await ps.run_snapshot()
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("snapshot_run error")
        result = {"status": "error", "message": "Snapshot run failed"}
    return JSONResponse(content=result)


# ── Analyst Leaderboard page ─────────────────────────────────────────────

@router.get("/analysts", response_class=HTMLResponse)
async def analysts_page(
    request: Request,
    sector: str | None = Query(None),
    symbol: str | None = Query(None),
    ps: PredictionService = Depends(get_prediction_service),
):
    templates = _templates()
    try:
        leaderboard = await ps.get_top_analysts(sector=sector, symbol=symbol)
    except ROUTE_RECOVERABLE_ERRORS:
        logger.exception("analysts_page error")
        leaderboard = []

    return templates.TemplateResponse("analysts.html", {
        "request": request,
        "leaderboard": leaderboard,
        "sector_filter": sector or "",
        "symbol_filter": symbol or "",
    })
