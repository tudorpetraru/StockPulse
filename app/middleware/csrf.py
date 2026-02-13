"""Double-submit cookie CSRF protection."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"
_FORM_FIELD = "csrf_token"


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS:
            response = await call_next(request)
            if _COOKIE_NAME not in request.cookies:
                token = secrets.token_urlsafe(32)
                response.set_cookie(
                    _COOKIE_NAME,
                    token,
                    httponly=False,
                    samesite="strict",
                    path="/",
                )
            return response

        cookie_token = request.cookies.get(_COOKIE_NAME)
        if not cookie_token:
            return JSONResponse({"error": "Missing CSRF cookie"}, status_code=403)

        submitted = request.headers.get(_HEADER_NAME)
        if not submitted:
            content_type = request.headers.get("content-type", "").lower()
            if "form" in content_type:
                form = await request.form()
                submitted = str(form.get(_FORM_FIELD, ""))

        if not submitted or not secrets.compare_digest(str(submitted), cookie_token):
            return JSONResponse({"error": "CSRF token mismatch"}, status_code=403)

        return await call_next(request)

