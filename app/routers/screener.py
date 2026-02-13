"""
Screener router — full page + HTMX results partial + CSV export + preset CRUD.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Agent-A interface (stubbed) ───────────────────────────────────────────
# Use a standalone stub so we don't depend on Agent A's DataService constructor.

class _DataServiceStub:
    """Minimal stub until Agent A's DataService is wired in."""
    async def screen_stocks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return []


def _get_data_service() -> _DataServiceStub:
    return _DataServiceStub()


# ── Presets storage (JSON file until Agent A provides DB layer) ───────────

_PRESETS_PATH = Path("data/screener_presets.json")


def _load_presets() -> list[dict[str, Any]]:
    if _PRESETS_PATH.exists():
        return json.loads(_PRESETS_PATH.read_text())
    return []


def _save_presets(presets: list[dict[str, Any]]) -> None:
    _PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PRESETS_PATH.write_text(json.dumps(presets, indent=2))


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
    try:
        return sorted(results, key=lambda r: (r.get(sort_by) is None, r.get(sort_by, 0)), reverse=reverse)
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
async def screener_page(request: Request):
    templates = _templates()
    presets = _load_presets()
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
    ds: DataService = Depends(_get_data_service),
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
    ds: DataService = Depends(_get_data_service),
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
async def list_presets():
    return JSONResponse(content=_load_presets())


@router.post("/api/screener/presets")
async def save_preset(request: Request):
    body = await request.json()
    name = body.get("name", "Untitled")
    filters = body.get("filters", {})
    presets = _load_presets()
    preset = {
        "id": str(uuid4()),
        "name": name,
        "filters": filters,
    }
    presets.append(preset)
    _save_presets(presets)
    return JSONResponse(content=preset, status_code=201)


@router.delete("/api/screener/presets/{preset_id}")
async def delete_preset(preset_id: str):
    presets = _load_presets()
    presets = [p for p in presets if p["id"] != preset_id]
    _save_presets(presets)
    return JSONResponse(content={"ok": True})
