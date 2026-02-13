from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


PanelStatus = Literal["ok", "error", "stale"]


class DataPanelResult(BaseModel):
    status: PanelStatus
    data: Any | None = None
    message: str | None = None


class PartialDataResult(BaseModel):
    symbol: str
    panels: dict[str, DataPanelResult] = Field(default_factory=dict)


class AnalystRating(BaseModel):
    firm: str
    analyst_name: str | None = None
    action: str | None = None
    rating: str
    price_target: float | None = None
    source: str = "unknown"


class ConsensusTargets(BaseModel):
    low: float | None = None
    avg: float | None = None
    median: float | None = None
    high: float | None = None
    count: int | None = None
    consensus: str | None = None
    current: float


class SnapshotOutcome(BaseModel):
    actual_price: float | None = None
    actual_return: float | None = None
    prediction_error: float | None = None
    directionally_correct: bool | None = None
    unresolvable: bool = False


class PredictionScore(BaseModel):
    firm: str
    ticker: str | None = None
    total_predictions: int
    success_rate: float | None = None
    avg_return_error: float | None = None
    avg_absolute_error: float | None = None
    directional_accuracy: float | None = None
    composite_score: float | None = None


class PredictionSnapshotRequest(BaseModel):
    ticker: str
    snapshot_date: date
