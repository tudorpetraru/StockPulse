"""Tests for the ticker router – route status codes, partials, chart APIs."""
from __future__ import annotations

from datetime import date, timedelta


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

    def test_hx_holders_renders_ownership_and_change_columns(self, client):
        async def _fake_holders(symbol: str):
            _ = symbol
            return {
                "institutional": [
                    {
                        "name": "Fund A",
                        "shares": 100.0,
                        "pct_in": 25.0,
                        "pct_change": 10.0,
                        "value": 3000.0,
                        "date": "2025-12-31",
                    },
                    {
                        "name": "Fund B",
                        "shares": 300.0,
                        "pct_in": 75.0,
                        "pct_change": -10.0,
                        "value": 1000.0,
                        "date": "2025-12-31",
                    },
                ],
                "mutual_fund": [],
            }

        client.app.state.data_service.get_holders = _fake_holders
        response = client.get("/hx/ticker/AAPL/holders")
        assert response.status_code == 200
        assert "% In (of AAPL shares)" in response.text
        assert "Change vs Prev Filing" in response.text
        assert "+10.00%" in response.text
        assert "-10.00%" in response.text
        assert "25.00%" in response.text
        assert "75.00%" in response.text

    def test_hx_holders_uses_requested_symbol_in_headers(self, client):
        async def _fake_holders(symbol: str):
            _ = symbol
            return {
                "institutional": [
                    {
                        "name": "Fund X",
                        "shares": 1.0,
                        "pct_in": 0.1,
                        "pct_change": 0.01,
                        "value": 1000.0,
                        "date": "2025-12-31",
                    }
                ],
                "mutual_fund": [],
            }

        client.app.state.data_service.get_holders = _fake_holders
        response = client.get("/hx/ticker/NVDA/holders")
        assert response.status_code == 200
        assert "% In (of NVDA shares)" in response.text
        assert "NVDA Position Value" in response.text
        assert "AAPL Position Value" not in response.text

    def test_hx_earnings_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/earnings")

    def test_hx_predictions_200(self, client):
        self._assert_partial(client, "/hx/ticker/AAPL/predictions")

    def test_hx_predictions_renders_captured_records_table(self, client):
        async def _fake_prediction_summary(symbol: str):
            _ = symbol
            return {"active": 1, "resolved": 1, "accuracy": 75.0, "consensus_target": "$150.00"}

        async def _fake_prediction_history(symbol: str):
            _ = symbol
            return [
                {
                    "snapshot_date": "2026-02-10",
                    "date": "Feb 10",
                    "year": 2026,
                    "firm": "Demo Research",
                    "source": "finvizfinance",
                    "rating": "Buy",
                    "action": "Upgrade",
                    "target": "150.00",
                    "implied_return": "8.0%",
                    "resolved": True,
                    "resolve_date": "2026-02-12",
                    "actual_price": "148.00",
                    "actual_return": "6.5%",
                    "accurate": True,
                    "error_pct": "1.5%",
                    "days_left": 0,
                }
            ]

        client.app.state.prediction_service.get_prediction_summary = _fake_prediction_summary
        client.app.state.prediction_service.get_prediction_history = _fake_prediction_history
        response = client.get("/hx/ticker/AAPL/predictions")
        assert response.status_code == 200
        assert "Captured Prediction Records" in response.text
        assert "Snapshot Date" in response.text
        assert "Demo Research" in response.text
        assert "2026-02-10" in response.text
        assert "finvizfinance" in response.text

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

    def test_consensus_chart_period_filters_data_window(self, client):
        old_date = (date.today() - timedelta(days=900)).isoformat()
        mid_date = (date.today() - timedelta(days=500)).isoformat()
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        called_periods: list[str] = []

        async def _fake_price_history(symbol: str, period: str = "1y"):
            _ = symbol
            called_periods.append(period)
            return [
                {"date": old_date, "close": 80.0},
                {"date": mid_date, "close": 90.0},
                {"date": recent_date, "close": 100.0},
            ]

        async def _fake_consensus_history(symbol: str):
            _ = symbol
            return [
                {"date": old_date, "avg_target": 85.0, "low_target": 80.0, "high_target": 95.0, "resolved": False, "accurate": None},
                {"date": mid_date, "avg_target": 92.0, "low_target": 88.0, "high_target": 98.0, "resolved": False, "accurate": None},
                {"date": recent_date, "avg_target": 110.0, "low_target": 105.0, "high_target": 120.0, "resolved": False, "accurate": None},
            ]

        client.app.state.data_service.get_price_history = _fake_price_history
        client.app.state.prediction_service.get_consensus_history = _fake_consensus_history

        one_year_resp = client.get("/api/chart/AAPL/consensus?period=1Y")
        assert one_year_resp.status_code == 200
        one_year_body = one_year_resp.json()
        assert called_periods[-1] == "1y"
        assert one_year_body["layout"]["title"]["text"].endswith("(1Y)")
        assert one_year_body["data"][0]["x"] == [recent_date]

        all_resp = client.get("/api/chart/AAPL/consensus?period=All")
        assert all_resp.status_code == 200
        all_body = all_resp.json()
        assert called_periods[-1] == "max"
        assert all_body["layout"]["title"]["text"].endswith("(All)")
        assert all_body["data"][0]["x"] == [old_date, mid_date, recent_date]
