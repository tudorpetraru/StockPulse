"""UI smoke tests — all main routes return 200 and render key headings."""
from __future__ import annotations


def test_dashboard_smoke(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"StockPulse" in r.content
    assert b"Portfolio Summary" in r.content


def test_portfolio_smoke(client):
    r = client.get("/portfolio")
    assert r.status_code == 200
    assert b"StockPulse" in r.content


def test_watchlist_smoke(client):
    r = client.get("/watchlist")
    assert r.status_code == 200
    assert b"Watchlist" in r.content


def test_news_smoke(client):
    r = client.get("/news")
    assert r.status_code == 200
    assert b"News Feed" in r.content


def test_nav_links_present(client):
    """All primary nav links should be in the base template."""
    r = client.get("/")
    content = r.content.decode()
    assert 'href="/"' in content
    assert 'href="/portfolio"' in content
    assert 'href="/watchlist"' in content
    assert 'href="/news"' in content
    assert 'href="/screener"' in content


def test_search_box_present(client):
    r = client.get("/")
    assert b"Search ticker" in r.content
    assert b"search-modal" in r.content
