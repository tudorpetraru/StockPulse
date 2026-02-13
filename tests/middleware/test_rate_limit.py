from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


def test_rate_limit_triggers() -> None:
    limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
    app = FastAPI()
    app.add_middleware(SlowAPIMiddleware)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.post("/limited")
    @limiter.limit("2/minute")
    def limited(request: Request) -> dict[str, bool]:
        _ = request
        return {"ok": True}

    with TestClient(app) as client:
        r1 = client.post("/limited")
        r2 = client.post("/limited")
        r3 = client.post("/limited")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429

