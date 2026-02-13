from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.services.prediction_service import PredictionService


class _ConsensusProvider:
    async def get_consensus_targets(self, symbol: str) -> dict[str, object]:
        _ = symbol
        return {"avg": 293.06952}


@pytest.mark.asyncio
async def test_prediction_summary_uses_live_consensus_when_db_empty(db_session: Session) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)
    service = PredictionService(session_factory=factory, yfinance_provider=_ConsensusProvider())

    summary = await service.get_prediction_summary("AAPL")

    assert summary["active"] == 0
    assert summary["resolved"] == 0
    assert summary["consensus_target"] == "$293.07"
