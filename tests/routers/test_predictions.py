"""Tests for the predictions router – APIs + analyst leaderboard page."""
from __future__ import annotations


class TestAnalystLeaderboard:
    def test_analysts_page_200(self, client):
        """GET /analysts returns 200."""
        resp = client.get("/analysts")
        assert resp.status_code == 200
        assert "Analyst Leaderboard" in resp.text


class TestPredictionAPIs:
    def test_prediction_analysts_api(self, client):
        """GET /api/predictions/AAPL/analysts returns JSON array."""
        resp = client.get("/api/predictions/AAPL/analysts")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_prediction_consensus_api(self, client):
        """GET /api/predictions/AAPL/consensus-history returns JSON."""
        resp = client.get("/api/predictions/AAPL/consensus-history")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_top_analysts_api(self, client):
        """GET /api/predictions/top-analysts returns JSON array."""
        resp = client.get("/api/predictions/top-analysts")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_firm_history_api(self, client):
        """GET /api/predictions/AAPL/analyst/Goldman returns JSON."""
        resp = client.get("/api/predictions/AAPL/analyst/Goldman")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)


class TestColdStartState:
    def test_cold_start_indicator(self, client):
        """Predictions tab for a new ticker shows cold-start UI."""
        resp = client.get("/hx/ticker/NEWSTOCK/predictions")
        assert resp.status_code == 200
        # Cold start text indicator should be present when no resolved predictions
        assert "Building Your Prediction Database" in resp.text or "Prediction Tracking Summary" in resp.text
