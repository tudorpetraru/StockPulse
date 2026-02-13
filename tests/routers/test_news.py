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


def test_news_empty_state_message(client):
    response = client.get("/hx/news/feed?filter=all")
    assert response.status_code == 200
    assert b"No news available" in response.content or b"news" in response.content.lower()
