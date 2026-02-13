"""Tests for the screener router – page, results, sort, pagination, CSV, presets."""
from __future__ import annotations

import csv
import io
import json


class TestScreenerPage:
    def test_screener_page_200(self, client):
        """GET /screener returns 200."""
        resp = client.get("/screener")
        assert resp.status_code == 200
        assert "Stock Screener" in resp.text

    def test_screener_results_post(self, client):
        """POST /hx/screener/results returns HTML partial."""
        resp = client.post("/hx/screener/results", data={})
        assert resp.status_code == 200
        # Should be a partial (no full HTML doc)
        assert "<html" not in resp.text.lower()[:200]

    def test_screener_sort(self, client):
        """Sort parameter is accepted."""
        resp = client.post(
            "/hx/screener/results?sort_by=mkt_cap&sort_dir=desc",
            data={},
        )
        assert resp.status_code == 200

    def test_screener_pagination(self, client):
        """Pagination parameter is accepted."""
        resp = client.post("/hx/screener/results?page=2", data={})
        assert resp.status_code == 200


class TestScreenerCSV:
    def test_csv_export(self, client):
        """POST /api/screener/export returns CSV content type."""
        resp = client.post("/api/screener/export", data={})
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_csv_injection_escaped(self, client):
        async def fake_screen_stocks(filters):
            _ = filters
            return [
                {
                    "ticker": "SAFE",
                    "company": "=CMD()",
                    "price": "1",
                    "change_pct": "0",
                    "mkt_cap": "1B",
                    "pe": "10",
                    "eps": "1.2",
                    "volume": "1000",
                }
            ]

        client.app.state.data_service.screen_stocks = fake_screen_stocks
        response = client.post("/api/screener/export", data={})
        assert response.status_code == 200

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert rows
        assert rows[0]["company"].startswith("'=")
        assert not rows[0]["company"].startswith("=")


class TestScreenerPresets:
    def test_preset_crud(self, client):
        """Create, list, and delete a preset."""
        # Create
        resp = client.post(
            "/api/screener/presets",
            content=json.dumps({"name": "Test Preset", "filters": {"pe_max": 20}}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        preset = resp.json()
        assert preset["name"] == "Test Preset"
        preset_id = preset["id"]

        # List
        resp = client.get("/api/screener/presets")
        assert resp.status_code == 200
        presets = resp.json()
        assert any(p["id"] == preset_id for p in presets)

        # Delete
        resp = client.delete(f"/api/screener/presets/{preset_id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = client.get("/api/screener/presets")
        presets = resp.json()
        assert not any(p["id"] == preset_id for p in presets)

    def test_preset_payload_too_large(self, client):
        resp = client.post(
            "/api/screener/presets",
            content=json.dumps({"name": "Big Preset", "filters": {"blob": "x" * 20_000}}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413
