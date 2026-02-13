"""Tests for portfolio router — page load, CRUD operations, HTMX table refresh."""
from __future__ import annotations


def test_portfolio_page_returns_200(client):
    """First visit creates default portfolio."""
    response = client.get("/portfolio")
    assert response.status_code == 200
    assert b"Main Portfolio" in response.content


def test_portfolio_page_shows_positions(client, sample_portfolio):
    response = client.get(f"/portfolio?portfolio_id={sample_portfolio.id}")
    assert response.status_code == 200
    assert b"AAPL" in response.content
    assert b"NVDA" in response.content
    assert b"MSFT" in response.content


def test_portfolio_table_htmx(client, sample_portfolio):
    response = client.get(f"/hx/portfolio/table?portfolio_id={sample_portfolio.id}")
    assert response.status_code == 200
    assert b"AAPL" in response.content


def test_portfolio_table_refresh_uses_bypass_cache(client, sample_portfolio):
    async def _fake_get_price(symbol: str, bypass_cache: bool = False):
        _ = symbol
        return {
            "price": 150.0 if bypass_cache else 100.0,
            "change": 1.5 if bypass_cache else 1.0,
            "change_pct": 1.5 if bypass_cache else 1.0,
            "updated": "now",
        }

    client.app.state.data_service.get_price = _fake_get_price
    baseline = client.get(f"/hx/portfolio/table?portfolio_id={sample_portfolio.id}")
    refreshed = client.get(f"/hx/portfolio/table?portfolio_id={sample_portfolio.id}&refresh=1")
    assert baseline.status_code == 200
    assert refreshed.status_code == 200
    assert b"$100.00" in baseline.content
    assert b"$150.00" in refreshed.content


def test_add_position(client, sample_portfolio):
    response = client.post("/api/positions", data={
        "portfolio_id": sample_portfolio.id,
        "ticker": "googl",
        "shares": "25",
        "avg_cost": "175.00",
    })
    assert response.status_code == 200
    assert b"GOOGL" in response.content


def test_add_position_uppercase(client, sample_portfolio):
    """Ticker should be uppercased."""
    response = client.post("/api/positions", data={
        "portfolio_id": sample_portfolio.id,
        "ticker": "  tsla  ",
        "shares": "10",
        "avg_cost": "250.00",
    })
    assert response.status_code == 200
    assert b"TSLA" in response.content


def test_delete_position(client, sample_portfolio, db_session):
    from app.models.db_models import Position
    pos = db_session.query(Position).filter(Position.ticker == "AAPL").first()
    assert pos is not None

    response = client.delete(f"/api/positions/{pos.id}")
    assert response.status_code == 200
    assert b"AAPL" not in response.content


def test_create_portfolio(client):
    response = client.post("/api/portfolios", data={"name": "IRA Account"}, follow_redirects=False)
    assert response.status_code == 303
    assert "/portfolio?portfolio_id=" in response.headers["location"]


def test_delete_portfolio(client, sample_portfolio):
    response = client.delete(f"/api/portfolios/{sample_portfolio.id}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_create_portfolio_name_too_long(client):
    response = client.post("/api/portfolios", data={"name": "x" * 300}, follow_redirects=False)
    assert response.status_code == 422


def test_add_position_negative_shares(client, sample_portfolio):
    response = client.post(
        "/api/positions",
        data={
            "portfolio_id": sample_portfolio.id,
            "ticker": "AAPL",
            "shares": "-10",
            "avg_cost": "100",
        },
    )
    assert response.status_code == 422
