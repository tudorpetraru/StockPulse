from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.error_handler import generic_exception_handler


def test_500_does_not_leak_internals_html() -> None:
    app = FastAPI()
    app.add_exception_handler(Exception, generic_exception_handler)

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("secret database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text


def test_500_does_not_leak_internals_json() -> None:
    app = FastAPI()
    app.add_exception_handler(Exception, generic_exception_handler)

    @app.get("/api/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("secret database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/boom")

    assert response.status_code == 500
    payload = response.json()
    assert payload == {"error": "An internal error occurred. Please try again."}

