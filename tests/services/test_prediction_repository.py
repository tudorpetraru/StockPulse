from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.db_models import AnalystSnapshot, ConsensusSnapshot, Portfolio, Position, Watchlist, WatchlistItem
from app.repositories.prediction_repository import PredictionRepository


def test_get_all_tracked_tickers_deduplicates_and_normalizes(db_session: Session) -> None:
    portfolio = Portfolio(name="Main")
    db_session.add(portfolio)
    db_session.commit()
    db_session.refresh(portfolio)

    watchlist = Watchlist(name="Core")
    db_session.add(watchlist)
    db_session.commit()
    db_session.refresh(watchlist)

    db_session.add_all(
        [
            Position(portfolio_id=portfolio.id, ticker="aapl", shares=10, avg_cost=100.0),
            Position(portfolio_id=portfolio.id, ticker="MSFT", shares=5, avg_cost=200.0),
            WatchlistItem(watchlist_id=watchlist.id, ticker="AAPL"),
            WatchlistItem(watchlist_id=watchlist.id, ticker="tsla"),
        ]
    )
    db_session.commit()

    repo = PredictionRepository()
    assert repo.get_all_tracked_tickers(db_session) == ["AAPL", "MSFT", "TSLA"]


def test_pending_and_resolved_queries(db_session: Session) -> None:
    repo = PredictionRepository()
    snapshot_date = date(2025, 1, 1)
    target_date = snapshot_date + timedelta(days=365)

    # Pending analyst (eligible)
    db_session.add(
        AnalystSnapshot(
            ticker="AAPL",
            snapshot_date=snapshot_date,
            firm="Firm A",
            rating="Buy",
            price_target=120.0,
            current_price=100.0,
            implied_return=0.2,
            target_date=target_date,
        )
    )
    # Already resolved analyst (eligible for resolved query)
    db_session.add(
        AnalystSnapshot(
            ticker="MSFT",
            snapshot_date=snapshot_date,
            firm="Firm B",
            rating="Buy",
            price_target=130.0,
            current_price=100.0,
            implied_return=0.3,
            target_date=target_date,
            actual_price_at_target=140.0,
            actual_return=0.4,
            prediction_error=-0.1,
            is_directionally_correct=True,
        )
    )
    # Pending consensus
    db_session.add(
        ConsensusSnapshot(
            ticker="AAPL",
            snapshot_date=snapshot_date,
            target_low=90.0,
            target_avg=120.0,
            target_median=118.0,
            target_high=150.0,
            analyst_count=20,
            consensus_rating="buy",
            current_price=100.0,
            implied_upside=0.2,
            target_date=target_date,
        )
    )
    db_session.commit()

    pending_analyst = repo.list_pending_analyst_snapshots(db_session, reference_date=date(2026, 1, 2))
    pending_consensus = repo.list_pending_consensus_snapshots(db_session, reference_date=date(2026, 1, 2))
    resolved = repo.list_resolved_analyst_snapshots(db_session)

    assert len(pending_analyst) == 1
    assert pending_analyst[0].ticker == "AAPL"
    assert len(pending_consensus) == 1
    assert pending_consensus[0].ticker == "AAPL"
    assert len(resolved) == 1
    assert resolved[0].ticker == "MSFT"

