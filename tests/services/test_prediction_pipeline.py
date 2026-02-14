from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import (
    AnalystScore,
    AnalystSnapshot,
    ConsensusSnapshot,
    Portfolio,
    Position,
    Watchlist,
    WatchlistItem,
)
from app.repositories.prediction_repository import PredictionRepository
from app.services.prediction_service import PredictionSnapshotService


class StubFinvizProvider:
    def __init__(self, ratings_by_ticker: dict[str, list[dict[str, object]]]) -> None:
        self.ratings_by_ticker = ratings_by_ticker

    async def get_analyst_ratings(self, ticker: str) -> list[dict[str, object]]:
        return list(self.ratings_by_ticker.get(ticker, []))


class StubYFinanceProvider:
    def __init__(
        self,
        current_prices: dict[str, float],
        consensus_by_ticker: dict[str, dict[str, object]] | None = None,
        prices_on_date: dict[str, float | None] | None = None,
    ) -> None:
        self.current_prices = current_prices
        self.consensus_by_ticker = consensus_by_ticker or {}
        self.prices_on_date = prices_on_date or {}

    async def get_current_price(self, ticker: str) -> float:
        return self.current_prices[ticker]

    async def get_consensus_targets(self, ticker: str) -> dict[str, object]:
        return dict(self.consensus_by_ticker[ticker])

    async def get_price_on_date(self, ticker: str, target_date: date) -> float | None:
        return self.prices_on_date.get(ticker)


def _seed_tracked_ticker(db: Session, ticker: str) -> None:
    portfolio = Portfolio(name="Main")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    db.add(Position(portfolio_id=portfolio.id, ticker=ticker, shares=10, avg_cost=100.0))

    watchlist = Watchlist(name="Primary")
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    db.add(WatchlistItem(watchlist_id=watchlist.id, ticker=ticker.lower()))
    db.commit()


@pytest.mark.asyncio
async def test_run_daily_snapshot_upserts_existing_rows(db_session: Session) -> None:
    _seed_tracked_ticker(db_session, "AAPL")

    finviz = StubFinvizProvider(
        {
            "AAPL": [
                {
                    "firm": "Goldman Sachs",
                    "action": "Reiterate",
                    "rating": "Buy",
                    "price_target": "$185",
                }
            ]
        }
    )
    yfinance = StubYFinanceProvider(
        current_prices={"AAPL": 150.0},
        consensus_by_ticker={
            "AAPL": {
                "low": 120.0,
                "avg": 170.0,
                "median": 168.0,
                "high": 200.0,
                "count": 30,
                "consensus": "buy",
                "current": 150.0,
            }
        },
    )
    service = PredictionSnapshotService(yfinance_provider=yfinance, finviz_provider=finviz, repository=PredictionRepository())

    run_day = date(2026, 2, 1)
    first = await service.run_daily_snapshot(db_session, run_date=run_day)

    assert first == {"tracked": 1, "ok": 1, "failed": 0}
    analyst_rows = db_session.scalars(select(AnalystSnapshot)).all()
    consensus_rows = db_session.scalars(select(ConsensusSnapshot)).all()
    assert len(analyst_rows) == 1
    assert len(consensus_rows) == 1
    assert analyst_rows[0].price_target == 185.0
    assert consensus_rows[0].target_avg == 170.0

    finviz.ratings_by_ticker["AAPL"][0]["price_target"] = "$190"
    yfinance.consensus_by_ticker["AAPL"]["avg"] = 175.0
    yfinance.consensus_by_ticker["AAPL"]["current"] = 152.0
    yfinance.current_prices["AAPL"] = 152.0

    second = await service.run_daily_snapshot(db_session, run_date=run_day)
    assert second == {"tracked": 1, "ok": 1, "failed": 0}

    analyst_rows = db_session.scalars(select(AnalystSnapshot)).all()
    consensus_rows = db_session.scalars(select(ConsensusSnapshot)).all()
    assert len(analyst_rows) == 1
    assert len(consensus_rows) == 1
    assert analyst_rows[0].price_target == 190.0
    assert analyst_rows[0].current_price == 152.0
    assert consensus_rows[0].target_avg == 175.0
    assert consensus_rows[0].current_price == 152.0


@pytest.mark.asyncio
async def test_run_daily_snapshot_dedupes_duplicate_firms(db_session: Session) -> None:
    _seed_tracked_ticker(db_session, "AAPL")

    finviz = StubFinvizProvider(
        {
            "AAPL": [
                {
                    "firm": "Cantor Fitzgerald",
                    "action": "Initiated",
                    "rating": "Overweight",
                    "price_target": None,
                },
                {
                    "firm": "Cantor Fitzgerald",
                    "action": "Initiated",
                    "rating": "Overweight",
                    "price_target": "$182",
                },
            ]
        }
    )
    yfinance = StubYFinanceProvider(
        current_prices={"AAPL": 150.0},
        consensus_by_ticker={
            "AAPL": {
                "low": 120.0,
                "avg": 170.0,
                "median": 168.0,
                "high": 200.0,
                "count": 30,
                "consensus": "buy",
                "current": 150.0,
            }
        },
    )
    service = PredictionSnapshotService(yfinance_provider=yfinance, finviz_provider=finviz, repository=PredictionRepository())

    result = await service.run_daily_snapshot(db_session, run_date=date(2026, 2, 14))
    assert result == {"tracked": 1, "ok": 1, "failed": 0}

    analyst_rows = db_session.scalars(select(AnalystSnapshot).where(AnalystSnapshot.ticker == "AAPL")).all()
    assert len(analyst_rows) == 1
    assert analyst_rows[0].firm == "Cantor Fitzgerald"
    assert analyst_rows[0].price_target == 182.0


@pytest.mark.asyncio
async def test_evaluate_expired_predictions_resolves_and_marks_unresolvable(db_session: Session) -> None:
    snapshot_date = date(2025, 1, 1)
    target_date = snapshot_date + timedelta(days=365)

    db_session.add_all(
        [
            AnalystSnapshot(
                ticker="AAPL",
                snapshot_date=snapshot_date,
                firm="Goldman Sachs",
                rating="Buy",
                price_target=120.0,
                current_price=100.0,
                implied_return=0.2,
                target_date=target_date,
            ),
            AnalystSnapshot(
                ticker="MSFT",
                snapshot_date=snapshot_date,
                firm="UBS",
                rating="Buy",
                price_target=130.0,
                current_price=100.0,
                implied_return=0.3,
                target_date=target_date,
            ),
        ]
    )
    db_session.add(
        ConsensusSnapshot(
            ticker="AAPL",
            snapshot_date=snapshot_date,
            target_low=90.0,
            target_avg=120.0,
            target_median=118.0,
            target_high=150.0,
            analyst_count=22,
            consensus_rating="buy",
            current_price=100.0,
            implied_upside=0.2,
            target_date=target_date,
        )
    )
    db_session.commit()

    finviz = StubFinvizProvider({})
    yfinance = StubYFinanceProvider(
        current_prices={"AAPL": 100.0, "MSFT": 100.0},
        prices_on_date={"AAPL": 110.0, "MSFT": None},
    )
    service = PredictionSnapshotService(yfinance_provider=yfinance, finviz_provider=finviz, repository=PredictionRepository())

    result = await service.evaluate_expired_predictions(db_session, today=date(2026, 2, 1))
    assert result == {"resolved": 1, "unresolvable": 1}

    aapl = db_session.scalar(select(AnalystSnapshot).where(AnalystSnapshot.ticker == "AAPL"))
    msft = db_session.scalar(select(AnalystSnapshot).where(AnalystSnapshot.ticker == "MSFT"))
    consensus = db_session.scalar(select(ConsensusSnapshot).where(ConsensusSnapshot.ticker == "AAPL"))

    assert aapl is not None
    assert aapl.actual_price_at_target == 110.0
    assert round(aapl.actual_return or 0.0, 4) == 0.1
    assert round(aapl.prediction_error or 0.0, 4) == 0.1
    assert aapl.is_directionally_correct is True

    assert msft is not None
    assert msft.is_unresolvable is True
    assert msft.actual_price_at_target is None

    assert consensus is not None
    assert consensus.actual_price_at_target == 110.0
    assert consensus.consensus_was_correct is True


@pytest.mark.asyncio
async def test_recompute_scores_builds_global_and_ticker_rows(db_session: Session) -> None:
    snapshot_date = date(2025, 1, 1)
    def add_snapshot(firm: str, ticker: str, err: float, direction: bool, day_offset: int) -> None:
        row_snapshot_date = snapshot_date + timedelta(days=day_offset)
        row_target_date = row_snapshot_date + timedelta(days=365)
        db_session.add(
            AnalystSnapshot(
                ticker=ticker,
                snapshot_date=row_snapshot_date,
                firm=firm,
                rating="Buy",
                price_target=120.0,
                current_price=100.0,
                implied_return=0.2,
                target_date=row_target_date,
                actual_price_at_target=110.0,
                actual_return=0.1,
                prediction_error=err,
                is_directionally_correct=direction,
            )
        )

    for idx, (err, direction) in enumerate([(0.05, True), (0.08, True), (0.12, True), (0.02, True), (0.15, False)]):
        add_snapshot("Goldman Sachs", "AAPL" if err < 0.1 else "MSFT", err, direction, day_offset=idx)

    for idx, (err, direction) in enumerate([(0.03, True), (0.2, False), (0.25, False)], start=10):
        add_snapshot("UBS", "TSLA", err, direction, day_offset=idx)

    db_session.commit()

    finviz = StubFinvizProvider({})
    yfinance = StubYFinanceProvider(current_prices={"AAPL": 100.0, "MSFT": 100.0, "TSLA": 100.0})
    service = PredictionSnapshotService(yfinance_provider=yfinance, finviz_provider=finviz, repository=PredictionRepository())

    result = await service.recompute_scores(db_session)
    assert result == {"scores_written": 5, "source_rows": 8}

    scores = db_session.scalars(select(AnalystScore)).all()
    assert len(scores) == 5

    gs_global = db_session.scalar(
        select(AnalystScore).where(AnalystScore.firm == "Goldman Sachs", AnalystScore.ticker.is_(None))
    )
    assert gs_global is not None
    assert gs_global.total_predictions == 5
    assert gs_global.composite_score is not None
    assert 0.0 <= (gs_global.composite_score or 0.0) <= 1.0

    ubs_global = db_session.scalar(select(AnalystScore).where(AnalystScore.firm == "UBS", AnalystScore.ticker.is_(None)))
    assert ubs_global is not None
    assert ubs_global.total_predictions == 3
    assert ubs_global.composite_score is None
