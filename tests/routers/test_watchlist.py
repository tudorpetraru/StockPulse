"""Tests for watchlist router — page load, CRUD operations, HTMX table refresh."""
from __future__ import annotations


def test_watchlist_page_returns_200(client):
    """First visit creates default watchlist."""
    response = client.get("/watchlist")
    assert response.status_code == 200
    assert b"My Watchlist" in response.content


def test_watchlist_page_shows_items(client, sample_watchlist):
    response = client.get(f"/watchlist?watchlist_id={sample_watchlist.id}")
    assert response.status_code == 200
    assert b"TSLA" in response.content
    assert b"PLTR" in response.content


def test_watchlist_table_htmx(client, sample_watchlist):
    response = client.get(f"/hx/watchlist/table/{sample_watchlist.id}")
    assert response.status_code == 200
    assert b"SNOW" in response.content


def test_watchlist_table_refresh_uses_bypass_cache(client, sample_watchlist):
    async def _fake_get_price(symbol: str, bypass_cache: bool = False):
        _ = symbol
        return {
            "price": 150.0 if bypass_cache else 100.0,
            "change": 1.5 if bypass_cache else 1.0,
            "change_pct": 1.5 if bypass_cache else 1.0,
            "updated": "now",
        }

    async def _fake_get_metrics(symbol: str, bypass_cache: bool = False):
        _ = (symbol, bypass_cache)
        return {"pe": "20"}

    async def _fake_get_price_history(symbol: str, period: str = "1y", bypass_cache: bool = False):
        _ = (symbol, period, bypass_cache)
        return [
            {"date": "2026-02-12", "close": 95.0},
            {"date": "2026-02-13", "close": 105.0},
        ]

    client.app.state.data_service.get_price = _fake_get_price
    client.app.state.data_service.get_metrics = _fake_get_metrics
    client.app.state.data_service.get_price_history = _fake_get_price_history

    baseline = client.get(f"/hx/watchlist/table/{sample_watchlist.id}")
    refreshed = client.get(f"/hx/watchlist/table/{sample_watchlist.id}?refresh=1")
    assert baseline.status_code == 200
    assert refreshed.status_code == 200
    assert b"$100.00" in baseline.content
    assert b"$150.00" in refreshed.content


def test_add_watchlist_item(client, sample_watchlist):
    response = client.post("/api/watchlist-items", data={
        "watchlist_id": sample_watchlist.id,
        "ticker": "  meta  ",
    })
    assert response.status_code == 200
    assert b"META" in response.content


def test_add_duplicate_item(client, sample_watchlist):
    """Duplicate ticker should not create a second row."""
    response = client.post("/api/watchlist-items", data={
        "watchlist_id": sample_watchlist.id,
        "ticker": "TSLA",
    })
    assert response.status_code == 200
    # TSLA should appear exactly once in table
    content = response.content.decode()
    assert content.count('class="ticker-link">TSLA</a>') == 1


def test_delete_watchlist_item(client, sample_watchlist, db_session):
    from app.models.db_models import WatchlistItem
    item = db_session.query(WatchlistItem).filter(WatchlistItem.ticker == "PLTR").first()
    assert item is not None

    response = client.delete(f"/api/watchlist-items/{item.id}")
    assert response.status_code == 200
    assert b"PLTR" not in response.content


def test_create_watchlist(client):
    response = client.post("/api/watchlists", data={"name": "Dividend Picks"}, follow_redirects=False)
    assert response.status_code == 303
    assert "/watchlist?watchlist_id=" in response.headers["location"]


def test_delete_watchlist(client, sample_watchlist):
    response = client.delete(f"/api/watchlists/{sample_watchlist.id}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_create_watchlist_name_too_long(client):
    response = client.post("/api/watchlists", data={"name": "x" * 300}, follow_redirects=False)
    assert response.status_code == 422


def test_add_watchlist_invalid_ticker(client, sample_watchlist):
    response = client.post(
        "/api/watchlist-items",
        data={"watchlist_id": sample_watchlist.id, "ticker": "INVALID TICKER"},
    )
    assert response.status_code == 422
