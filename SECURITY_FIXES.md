# StockPulse Security Fix Specs

Seven actionable fix specs, ordered by effort (lowest first). Each spec includes the exact files to touch, the code changes, and a test plan.

---

## Fix 1: Security Headers Middleware

**Effort**: ~15 min | **Risk**: None | **Priority**: Medium

### Problem
No `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, or `Referrer-Policy` headers. The app is vulnerable to clickjacking and MIME-sniffing attacks.

### Changes

**File: `app/middleware/__init__.py`** (new)
```python
"""Empty init."""
```

**File: `app/middleware/security_headers.py`** (new)
```python
"""Middleware that adds security headers to every response."""
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net https://cdn.plot.ly 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none';"
        )
        return response
```

**File: `app/main.py`** (modify — add after `app = FastAPI(...)`)
```python
from app.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)
```

### Test Plan
```python
# tests/middleware/test_security_headers.py
def test_security_headers_present(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
```

---

## Fix 2: CSV Injection Escaping

**Effort**: ~10 min | **Risk**: None | **Priority**: Low

### Problem
`/api/screener/export` writes provider data into CSV cells. If a company name starts with `=`, `+`, `-`, `@`, `\t`, or `\r`, Excel/Sheets will execute it as a formula (e.g., `=HYPERLINK("http://evil.com","click")`).

### Changes

**File: `app/routers/screener.py`** (modify — add helper + update `screener_export`)

Add this helper function:
```python
def _csv_safe(value: str) -> str:
    """Prevent CSV injection by escaping formula-triggering prefixes."""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s
```

Update the writer loop in `screener_export`:
```python
# Before:
writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

# After:
writer.writerow({k: _csv_safe(str(r.get(k, ""))) for k in writer.fieldnames})
```

### Test Plan
```python
# In tests/routers/test_screener.py — add to TestScreenerCSV
def test_csv_injection_escaped(client):
    """Formula prefixes in data should be escaped with leading apostrophe."""
    # Mock data_service to return a row with formula prefix
    import csv, io
    # ... setup mock that returns company="=CMD()" ...
    r = client.post("/api/screener/export")
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        for val in row.values():
            assert not val.startswith("="), f"Unescaped formula: {val}"
```

---

## Fix 3: Input Validation with Length Limits

**Effort**: ~30 min | **Risk**: Low | **Priority**: Medium

### Problem
Several `Form()` fields accept unbounded strings. A malicious or buggy client could POST a 10 MB `description`, `notes`, or `name` field, bloating the SQLite database.

### Changes

**File: `app/routers/portfolio.py`** (modify all Form fields)

```python
# create_portfolio — add length limits
name: str = Form(..., max_length=200),
description: str = Form("", max_length=2000),

# add_position / update_position — add length limits + ticker validation
ticker: str = Form(..., max_length=10, pattern=r"^[A-Za-z0-9.\-]{1,10}$"),
notes: str = Form("", max_length=2000),
shares: float = Form(..., gt=0, le=1e9),
avg_cost: float = Form(..., ge=0, le=1e9),
```

**File: `app/routers/watchlist.py`** (modify all Form fields)

```python
# create_watchlist
name: str = Form(..., max_length=200),

# add_watchlist_item
ticker: str = Form(..., max_length=10),
notes: str = Form("", max_length=2000),

# update_watchlist_item
notes: str = Form("", max_length=2000),

# quick_add_watchlist
symbol: str = Form(..., max_length=10),
```

**File: `app/routers/news.py`** (modify query param)

```python
# news_page and news_feed_partial
q: str = Query("", max_length=500),
```

**File: `app/routers/screener.py`** (modify preset body validation)

Add after parsing the JSON body in `save_preset`:
```python
# Limit filters JSON size
if len(filters_json) > 10_000:
    return JSONResponse(content={"error": "Filters payload too large"}, status_code=413)
```

### Test Plan
```python
# tests/routers/test_portfolio.py — add
def test_create_portfolio_name_too_long(client):
    r = client.post("/api/portfolios", data={"name": "x" * 300})
    assert r.status_code == 422  # FastAPI validation error

def test_add_position_negative_shares(client, sample_portfolio):
    r = client.post("/api/positions", data={
        "portfolio_id": sample_portfolio.id,
        "ticker": "AAPL", "shares": "-10", "avg_cost": "100",
    })
    assert r.status_code == 422
```

---

## Fix 4: `reload=True` Gated by Environment

**Effort**: ~5 min | **Risk**: None | **Priority**: Low

### Problem
`run.py` hardcodes `reload=True`, which is a development-only feature that watches the filesystem and auto-restarts. Should not be on in production.

### Changes

**File: `app/config.py`** (add environment field)
```python
environment: str = Field(default="development", alias="ENVIRONMENT")
```

**File: `run.py`** (modify)
```python
from app.config import get_settings

settings = get_settings()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=(settings.environment != "production"),
    )
```

### Test Plan
Manual — set `ENVIRONMENT=production` in `.env` and verify uvicorn starts without reload.

---

## Fix 5: CSRF Protection for State-Changing Endpoints

**Effort**: ~45 min | **Risk**: Low-Medium (touches templates + routers) | **Priority**: High

### Problem
All `POST`, `PUT`, `DELETE` endpoints accept requests without any CSRF validation. If a user is tricked into visiting a malicious page while StockPulse is running, that page can submit forms to `localhost:8000` and modify portfolios, watchlists, or screener presets.

### Approach
Use a **double-submit cookie** pattern — no session storage needed:
1. Middleware sets a `csrf_token` cookie on every GET response
2. State-changing requests must include the token in a hidden form field or `X-CSRF-Token` header
3. Middleware compares cookie value to submitted value

### Changes

**File: `app/middleware/csrf.py`** (new)
```python
"""Double-submit cookie CSRF protection."""
import secrets
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"
_FORM_FIELD = "csrf_token"


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Safe methods: ensure token cookie exists, then proceed
        if request.method in _SAFE_METHODS:
            response = await call_next(request)
            if _COOKIE_NAME not in request.cookies:
                token = secrets.token_urlsafe(32)
                response.set_cookie(
                    _COOKIE_NAME, token,
                    httponly=False,   # JS needs to read it for HTMX/fetch
                    samesite="strict",
                    path="/",
                )
            return response

        # Unsafe methods: validate token
        cookie_token = request.cookies.get(_COOKIE_NAME)
        if not cookie_token:
            return JSONResponse({"error": "Missing CSRF cookie"}, status_code=403)

        # Check header first (HTMX / fetch), then form field
        submitted = request.headers.get(_HEADER_NAME)
        if not submitted:
            # Try to peek at form data (only for form-encoded bodies)
            content_type = request.headers.get("content-type", "")
            if "form" in content_type:
                form = await request.form()
                submitted = form.get(_FORM_FIELD)

        if not submitted or not secrets.compare_digest(submitted, cookie_token):
            return JSONResponse({"error": "CSRF token mismatch"}, status_code=403)

        return await call_next(request)
```

**File: `app/main.py`** (add middleware — order matters, CSRF before security headers)
```python
from app.middleware.csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)
```

**File: `app/templates/base.html`** (add HTMX config to auto-send token)
```html
<!-- After HTMX script tag -->
<script>
  // Auto-attach CSRF token to all HTMX requests
  document.addEventListener('htmx:configRequest', function(evt) {
    const token = document.cookie.split('; ')
      .find(c => c.startsWith('csrf_token='))
      ?.split('=')[1];
    if (token) {
      evt.detail.headers['x-csrf-token'] = token;
    }
  });
</script>
```

**All form templates** (add hidden field):
```html
<!-- In every <form> that uses POST/PUT/DELETE -->
<input type="hidden" name="csrf_token" id="csrf-token">
<script>
  document.getElementById('csrf-token').value =
    document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] || '';
</script>
```

**All `fetch()` calls in templates** (e.g., screener preset save/delete):
```javascript
// Add to fetch headers:
headers: {
  'Content-Type': 'application/json',
  'x-csrf-token': document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] || '',
}
```

**Tests**: Update `conftest.py` to either:
- Disable CSRF middleware in test app, OR
- Set the cookie + header on every test request

```python
# Simplest approach: skip CSRF in test app
# In conftest.py, don't add CSRFMiddleware to test_app
```

### Test Plan
```python
# tests/middleware/test_csrf.py
def test_post_without_csrf_returns_403(client):
    r = client.post("/api/portfolios", data={"name": "Hacked"})
    assert r.status_code == 403

def test_post_with_csrf_succeeds(client):
    # GET first to get cookie
    r = client.get("/portfolio")
    token = r.cookies.get("csrf_token")
    r2 = client.post(
        "/api/portfolios",
        data={"name": "Legit", "csrf_token": token},
        cookies={"csrf_token": token},
    )
    assert r2.status_code in (200, 303)

def test_csrf_mismatch_returns_403(client):
    r = client.get("/portfolio")
    r2 = client.post(
        "/api/portfolios",
        data={"name": "Hacked", "csrf_token": "wrong"},
        cookies={"csrf_token": r.cookies.get("csrf_token")},
    )
    assert r2.status_code == 403
```

---

## Fix 6: Rate Limiting

**Effort**: ~30 min | **Risk**: Low | **Priority**: Medium

### Problem
No request throttling. A script could hammer `/api/screener/export` or `/api/positions` thousands of times, overwhelming external provider APIs (yfinance, finviz) and filling the database.

### Changes

**File: `requirements.txt`** (add)
```
slowapi>=0.1.9,<1.0
```

**File: `app/middleware/rate_limit.py`** (new)
```python
"""Rate limiting configuration."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
```

**File: `app/main.py`** (add)
```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.middleware.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Apply stricter limits to expensive endpoints** (modify routers):
```python
# app/routers/screener.py — screener hits external APIs
from app.middleware.rate_limit import limiter

@router.post("/hx/screener/results", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def hx_screener_results(request: Request, ...):
    ...

@router.post("/api/screener/export")
@limiter.limit("5/minute")
async def screener_export(request: Request, ...):
    ...

# app/routers/predictions.py — snapshot trigger
@router.post("/api/predictions/snapshot/run")
@limiter.limit("2/minute")
async def prediction_snapshot_run(request: Request, ...):
    ...
```

### Test Plan
```python
# tests/middleware/test_rate_limit.py
def test_rate_limit_triggers(client):
    # Hammer an endpoint beyond limit
    for _ in range(12):
        client.post("/hx/screener/results")
    r = client.post("/hx/screener/results")
    assert r.status_code == 429
```

---

## Fix 7: Error Response Standardization

**Effort**: ~20 min | **Risk**: None | **Priority**: Low

### Problem
Unhandled exceptions return FastAPI's default 500 response which includes the exception class name and can leak internal info. Several routers also use bare `except Exception` which catches too broadly.

### Changes

**File: `app/middleware/error_handler.py`** (new)
```python
"""Global exception handler — returns safe error pages."""
import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)


async def generic_exception_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)

    # Return JSON for API routes, HTML for pages
    if request.url.path.startswith("/api/") or request.url.path.startswith("/hx/"):
        return JSONResponse(
            content={"error": "An internal error occurred. Please try again."},
            status_code=500,
        )

    return HTMLResponse(
        content="<h1>Something went wrong</h1><p>Please try again or go back to the <a href='/'>dashboard</a>.</p>",
        status_code=500,
    )
```

**File: `app/main.py`** (add after app creation)
```python
from app.middleware.error_handler import generic_exception_handler
app.add_exception_handler(Exception, generic_exception_handler)
```

### Test Plan
```python
# tests/middleware/test_error_handler.py
def test_500_does_not_leak_internals(client, monkeypatch):
    """Verify error responses don't contain stack traces."""
    def boom(*a, **kw):
        raise RuntimeError("secret database password is hunter2")
    monkeypatch.setattr("app.routers.dashboard._portfolio_summary", boom)
    r = client.get("/")
    assert r.status_code == 500
    assert b"hunter2" not in r.content
    assert b"RuntimeError" not in r.content
```

---

## Implementation Order (Recommended)

| # | Fix | Effort | Can Parallel? |
|---|-----|--------|---------------|
| 1 | Security Headers | 15 min | Yes |
| 2 | CSV Injection | 10 min | Yes |
| 4 | Reload Flag | 5 min | Yes |
| 3 | Input Validation | 30 min | Yes |
| 7 | Error Standardization | 20 min | Yes |
| 6 | Rate Limiting | 30 min | After pip install |
| 5 | CSRF Protection | 45 min | Last (touches all templates) |

Fixes 1, 2, 3, 4, 7 are all independent — can be done in parallel.
Fix 6 requires a new pip dependency.
Fix 5 should go last since it modifies every form template and needs HTMX config changes.

---

## Out of Scope (Noted for Later)

- **Authentication/Authorization** — Major feature, not a quick fix. Needs its own design doc (session-based vs JWT, user model, registration flow, data isolation).
- **HTTPS** — Localhost dev tool; handled by deployment config if ever deployed.
- **Dependency audit** (`pip-audit`) — Worth running but separate from code fixes.
