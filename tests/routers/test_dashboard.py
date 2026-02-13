"""Tests for dashboard router."""
from __future__ import annotations


def test_dashboard_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_contains_portfolio_summary(client):
    response = client.get("/")
    assert b"Portfolio Summary" in response.content


def test_dashboard_contains_market_snapshot(client):
    response = client.get("/")
    assert b"Market Snapshot" in response.content


def test_dashboard_contains_prediction_tracker(client):
    response = client.get("/")
    assert b"Prediction Tracker" in response.content


def test_dashboard_with_portfolio(client, sample_portfolio):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Test Portfolio" in response.content


def test_dashboard_with_watchlist_movers(client, sample_watchlist):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Watchlist Movers" in response.content
