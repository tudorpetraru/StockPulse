from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.middleware.csrf import CSRFMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/form")
    def form() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.post("/submit")
    def submit(request: Request, value: str = Form("x")) -> dict[str, str]:
        _ = request
        return {"value": value}

    return app


def test_post_without_csrf_returns_403() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.post("/submit", data={"value": "x"})
    assert response.status_code == 403


def test_post_with_csrf_header_succeeds() -> None:
    app = _build_app()
    with TestClient(app) as client:
        initial = client.get("/form")
        token = initial.cookies.get("csrf_token")
        assert token
        response = client.post(
            "/submit",
            data={"value": "ok"},
            headers={"x-csrf-token": token},
            cookies={"csrf_token": token},
        )
    assert response.status_code == 200
    assert response.json()["value"] == "ok"


def test_post_with_csrf_form_field_succeeds() -> None:
    app = _build_app()
    with TestClient(app) as client:
        initial = client.get("/form")
        token = initial.cookies.get("csrf_token")
        assert token
        response = client.post(
            "/submit",
            data={"value": "ok", "csrf_token": token},
            cookies={"csrf_token": token},
        )
    assert response.status_code == 200

