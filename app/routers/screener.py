"""
Screener router — full page + HTMX results partial + CSV export + preset CRUD.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_data_service
from app.models.db_models import ScreenerPreset
from app.services.data_service import DataService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Jinja2 ────────────────────────────────────────────────────────────────

def _templates():
    from fastapi.templating import Jinja2Templates
    return Jinja2Templates(directory="app/templates")


# ── Filter extraction helper ─────────────────────────────────────────────

_FILTER_FIELDS = [
    "pe_min", "pe_max", "fwd_pe_min", "fwd_pe_max",
    "pb_min", "pb_max", "mkt_cap",
    "eps_min", "eps_max", "roe_min", "roe_max",
    "rsi_min", "rsi_max", "sma50_pos",
    "insider_min", "insider_max",
]


def _extract_filters(form: dict[str, Any]) -> dict[str, Any]:
    """Pull filter values from a form submission."""
    filters: dict[str, Any] = {}
    for key in _FILTER_FIELDS:
        val = form.get(key)
        if val is not None and val != "":
            # Numeric fields
            if key.endswith(("_min", "_max")):
                try:
                    filters[key] = float(val)
                except ValueError:
                    continue
            else:
                filters[key] = val
    return filters


# ── Sorting / pagination ─────────────────────────────────────────────────

_DEFAULT_PER_PAGE = 25
_SORTABLE_COLS = {"ticker", "company", "price", "change_pct", "mkt_cap", "pe", "eps", "volume"}


def _sort_results(
    results: list[dict[str, Any]],
    sort_by: str = "mkt_cap",
    sort_dir: str = "desc",
) -> list[dict[str, Any]]:
    if sort_by not in _SORTABLE_COLS:
        sort_by = "mkt_cap"
    reverse = sort_dir == "desc"
    key_name = "mkt_cap_num" if sort_by == "mkt_cap" else sort_by
    try:
        return sorted(results, key=lambda r: (r.get(key_name) is None, r.get(key_name, 0)), reverse=reverse)
    except TypeError:
        return results


def _paginate(
    results: list[dict[str, Any]], page: int = 1, per_page: int = _DEFAULT_PER_PAGE
) -> tuple[list[dict[str, Any]], int, int]:
    """Return (page_items, total_count, total_pages)."""
    total = len(results)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return results[start : start + per_page], total, total_pages


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("/screener", response_class=HTMLResponse)
async def screener_page(request: Request, db: Session = Depends(get_db)):
    templates = _templates()
    presets = _list_presets(db)
    return templates.TemplateResponse("screener.html", {
        "request": request,
        "presets": presets,
    })


@router.post("/hx/screener/results", response_class=HTMLResponse)
async def hx_screener_results(
    request: Request,
    sort_by: str = Query("mkt_cap"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(_DEFAULT_PER_PAGE, ge=5, le=100),
    ds: DataService = Depends(get_data_service),
):
    templates = _templates()
    form = await request.form()
    filters = _extract_filters(dict(form))

    try:
        all_results = await ds.screen_stocks(filters)
        status = "ok"
    except Exception:
        logger.exception("Screener query error")
        all_results = []
        status = "error"

    all_results = _sort_results(all_results, sort_by, sort_dir)
    items, total, total_pages = _paginate(all_results, page, per_page)

    return templates.TemplateResponse("partials/screener_results.html", {
        "request": request,
        "results": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "status": status,
    })


# ── CSV export ────────────────────────────────────────────────────────────

@router.post("/api/screener/export")
async def screener_export(
    request: Request,
    ds: DataService = Depends(get_data_service),
):
    form = await request.form()
    filters = _extract_filters(dict(form))

    try:
        results = await ds.screen_stocks(filters)
    except Exception:
        results = []

    results = _sort_results(results)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["ticker", "company", "price", "change_pct", "mkt_cap", "pe", "eps", "volume"])
    writer.writeheader()
    for r in results:
        writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=screener_export.csv"},
    )


# ── Preset CRUD ───────────────────────────────────────────────────────────

@router.get("/api/screener/presets")
async def list_presets(db: Session = Depends(get_db)):
    return JSONResponse(content=_list_presets(db))


@router.post("/api/screener/presets")
async def save_preset(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    name = (body.get("name") or "Untitled").strip()[:120]
    filters = body.get("filters", {})
    filters_json = json.dumps(filters)

    existing = db.query(ScreenerPreset).filter(ScreenerPreset.name == name).first()
    if existing:
        existing.filters = filters_json
        db.commit()
        db.refresh(existing)
        return JSONResponse(content=_serialize_preset(existing), status_code=200)

    preset = ScreenerPreset(name=name, filters=filters_json)
    db.add(preset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse(content={"error": "Preset name already exists"}, status_code=409)
    db.refresh(preset)
    return JSONResponse(content=_serialize_preset(preset), status_code=201)


@router.delete("/api/screener/presets/{preset_id}")
async def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = None
    if preset_id.isdigit():
        preset = db.get(ScreenerPreset, int(preset_id))
    if preset is None:
        preset = db.query(ScreenerPreset).filter(ScreenerPreset.name == preset_id).first()
    if preset:
        db.delete(preset)
        db.commit()
    return JSONResponse(content={"ok": True})


def _serialize_preset(preset: ScreenerPreset) -> dict[str, Any]:
    try:
        filters = json.loads(preset.filters)
    except json.JSONDecodeError:
        filters = {}
    return {"id": preset.id, "name": preset.name, "filters": filters}


def _list_presets(db: Session) -> list[dict[str, Any]]:
    rows = db.query(ScreenerPreset).order_by(ScreenerPreset.created_at.desc()).all()
    return [_serialize_preset(p) for p in rows]
