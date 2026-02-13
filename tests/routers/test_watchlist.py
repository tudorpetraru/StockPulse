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
