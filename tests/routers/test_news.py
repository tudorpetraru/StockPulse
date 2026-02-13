"""Tests for news router — page load and filter modes."""
from __future__ import annotations


def test_news_page_returns_200(client):
    response = client.get("/news")
    assert response.status_code == 200
    assert b"News Feed" in response.content


def test_news_page_filter_all(client):
    response = client.get("/news?filter=all")
    assert response.status_code == 200


def test_news_page_filter_portfolio(client, sample_portfolio):
    response = client.get("/news?filter=portfolio")
    assert response.status_code == 200


def test_news_page_filter_watchlist(client, sample_watchlist):
    response = client.get("/news?filter=watchlist")
    assert response.status_code == 200


def test_news_page_filter_custom(client):
    response = client.get("/news?filter=custom&q=AI+semiconductor")
    assert response.status_code == 200


def test_news_feed_htmx(client):
    response = client.get("/hx/news/feed?filter=all")
    assert response.status_code == 200


def test_news_title_and_source_normalization(client):
    async def _fake_get_news(symbol: str, limit: int = 20):
        _ = limit
        return [
            {
                "Title": f"{symbol} Uppercase Title",
                "Link": "https://example.com/upper",
                "Source": {"displayName": "Mapped Source"},
                "Date": "2026-02-13",
            },
            {
                "title": f"{symbol} lowercase title",
                "url": "https://example.com/lower",
                "source": "Lower Source",
                "date": "2026-02-13",
            },
        ]

    client.app.state.data_service.get_news = _fake_get_news
    response = client.get("/hx/news/feed?filter=all")
    assert response.status_code == 200
    assert b"Uppercase Title" in response.content
    assert b"lowercase title" in response.content
    assert b"Mapped Source" in response.content
    assert b"Untitled" not in response.content


def test_news_invalid_symbol_not_rendered_as_ticker(client):
    async def _fake_get_news(symbol: str, limit: int = 20):
        _ = (symbol, limit)
        return [
            {
                "title": "Macro headline",
                "url": "https://example.com/macro",
                "source": "Macro Source",
                "symbol": "US STOCK MARKET",
                "date": "2026-02-13",
            }
        ]

    client.app.state.data_service.get_news = _fake_get_news
    response = client.get("/hx/news/feed?filter=all")
    assert response.status_code == 200
    assert b"Macro headline" in response.content
    assert b"/ticker/US STOCK MARKET" not in response.content


def test_news_empty_state_message(client):
    response = client.get("/hx/news/feed?filter=all")
    assert response.status_code == 200
    assert b"No news available" in response.content or b"news" in response.content.lower()


def test_news_query_too_long(client):
    response = client.get("/news?filter=custom&q=" + ("x" * 700))
    assert response.status_code == 422
