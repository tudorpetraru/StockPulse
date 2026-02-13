from __future__ import annotations

from datetime import date

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.models.db_models import AnalystScore, AnalystSnapshot, ConsensusSnapshot, Position, WatchlistItem


class PredictionRepository:
    """Database operations for prediction tracking workflows."""

    def get_all_tracked_tickers(self, db: Session) -> list[str]:
        position_tickers = db.scalars(select(func.upper(Position.ticker))).all()
        watchlist_tickers = db.scalars(select(func.upper(WatchlistItem.ticker))).all()
        return sorted(set([t for t in position_tickers + watchlist_tickers if t]))

    def get_analyst_snapshot(self, db: Session, ticker: str, snapshot_date: date, firm: str) -> AnalystSnapshot | None:
        return db.scalar(
            select(AnalystSnapshot).where(
                and_(
                    AnalystSnapshot.ticker == ticker,
                    AnalystSnapshot.snapshot_date == snapshot_date,
                    AnalystSnapshot.firm == firm,
                )
            )
        )

    def get_consensus_snapshot(self, db: Session, ticker: str, snapshot_date: date) -> ConsensusSnapshot | None:
        return db.scalar(
            select(ConsensusSnapshot).where(
                and_(ConsensusSnapshot.ticker == ticker, ConsensusSnapshot.snapshot_date == snapshot_date)
            )
        )

    def list_pending_analyst_snapshots(self, db: Session, reference_date: date) -> list[AnalystSnapshot]:
        return db.scalars(
            select(AnalystSnapshot).where(
                and_(
                    AnalystSnapshot.target_date <= reference_date,
                    AnalystSnapshot.actual_price_at_target.is_(None),
                    AnalystSnapshot.is_unresolvable.is_(False),
                    AnalystSnapshot.is_backfilled.is_(False),
                    AnalystSnapshot.price_target.is_not(None),
                )
            )
        ).all()

    def list_pending_consensus_snapshots(self, db: Session, reference_date: date) -> list[ConsensusSnapshot]:
        return db.scalars(
            select(ConsensusSnapshot).where(
                and_(
                    ConsensusSnapshot.target_date <= reference_date,
                    ConsensusSnapshot.actual_price_at_target.is_(None),
                )
            )
        ).all()

    def list_resolved_analyst_snapshots(self, db: Session) -> list[AnalystSnapshot]:
        return db.scalars(
            select(AnalystSnapshot).where(
                and_(
                    AnalystSnapshot.actual_price_at_target.is_not(None),
                    AnalystSnapshot.price_target.is_not(None),
                    AnalystSnapshot.prediction_error.is_not(None),
                    AnalystSnapshot.is_unresolvable.is_(False),
                    AnalystSnapshot.is_backfilled.is_(False),
                )
            )
        ).all()

    def clear_scores(self, db: Session) -> None:
        db.execute(delete(AnalystScore))

