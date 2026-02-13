from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False
    )

    positions: Mapped[list[Position]] = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("shares > 0", name="ck_positions_shares_gt_zero"),
        CheckConstraint("avg_cost >= 0", name="ck_positions_avg_cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    date_acquired: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    portfolio: Mapped[Portfolio] = relationship("Portfolio", back_populates="positions")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_items_watchlist_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    watchlist: Mapped[Watchlist] = relationship("Watchlist", back_populates="items")


class ScreenerPreset(Base):
    __tablename__ = "screener_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    filters: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)


class AnalystSnapshot(Base):
    __tablename__ = "analyst_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", "firm", name="uq_analyst_snapshot_ticker_date_firm"),
        Index("ix_analyst_snapshots_ticker_date", "ticker", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    firm: Mapped[str] = mapped_column(String(255), nullable=False)
    analyst_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rating: Mapped[str] = mapped_column(String(64), nullable=False)
    price_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    implied_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_price_at_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    prediction_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_directionally_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_backfilled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_unresolvable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="finvizfinance", server_default="finvizfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)


class ConsensusSnapshot(Base):
    __tablename__ = "consensus_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_consensus_snapshot_ticker_date"),
        Index("ix_consensus_snapshots_ticker_date", "ticker", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyst_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consensus_rating: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    implied_upside: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_price_at_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    consensus_was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="yfinance", server_default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)


class AnalystScore(Base):
    __tablename__ = "analyst_scores"
    __table_args__ = (UniqueConstraint("firm", "ticker", name="uq_analyst_scores_firm_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firm: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_return_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    directional_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_call_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    worst_call_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
