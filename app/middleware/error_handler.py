"""Global exception handler that avoids leaking internal details."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)


async def generic_exception_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)

    path = request.url.path
    if path.startswith("/api/") or path.startswith("/hx/"):
        return JSONResponse(
            content={"error": "An internal error occurred. Please try again."},
            status_code=500,
        )

    return HTMLResponse(
        content="<h1>Something went wrong</h1><p>Please try again or go back to the <a href='/'>dashboard</a>.</p>",
        status_code=500,
    )

