"""Tests for the ticker router – route status codes, partials, chart APIs."""
from __future__ import annotations


class TestTickerPage:
    def test_ticker_page_200(self, client):
        """GET /ticker/AAPL returns 200 and contains the symbol."""
        resp = client.get("/ticker/AAPL")
        assert resp.status_code == 200
        assert "AAPL" in resp.text

    def test_ticker_unknown_symbol(self, client):
        """Unknown symbol still returns 200 (no 500 crash)."""
        resp = client.get("/ticker/XYZZ99")
        assert resp.status_code == 200


class TestTickerPartials:
    """Every HTMX partial should return 200 and NOT contain <html> (fragment)."""

    def _assert_partial(self, client, path: str):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "<html" not in resp.text.lower()[:200], f"Partial should not be a full page: {path}"

    def test_hx_financials_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/financials")

    def test_hx_financials_renders_populated_rows(self, client):
        async def _fake_financials(symbol: str, period: str = "annual"):
            _ = (symbol, period)
            return {
                "columns": ["2025", "2024"],
                "income": [{"label": "Revenue", "values": ["10.00B", "9.50B"]}],
                "balance": [],
                "cashflow": [],
            }

        client.app.state.data_service.get_financials = _fake_financials
        response = client.get("/hx/ticker/AAPL/financials")
        assert response.status_code == 200
        assert "Revenue" in response.text
        assert "10.00B" in response.text
        assert "<built-in method values" not in response.text

    def test_hx_news_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/news")

    def test_hx_insiders_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/insiders")

    def test_hx_holders_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/holders")

    def test_hx_earnings_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/earnings")

    def test_hx_predictions_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/predictions")

    def test_hx_analysts_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/analysts")


class TestChartAPIs:
    def test_price_chart_json(self, client):
        """GET /api/chart/AAPL/price returns JSON with 'data' key."""
        resp = client.get("/api/chart/AAPL/price?period=1Y")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert "data" in body
        assert "layout" in body

    def test_consensus_chart_json(self, client):
        resp = client.get("/api/chart/AAPL/consensus?period=2Y")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
