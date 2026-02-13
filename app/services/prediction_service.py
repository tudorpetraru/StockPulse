from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.db_models import AnalystScore, AnalystSnapshot, ConsensusSnapshot
from app.repositories.prediction_repository import PredictionRepository
from app.services.providers.finviz_provider import FinvizProvider
from app.services.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoreConfig:
    success_threshold: float = 0.10
    min_predictions: int = 5


class PredictionSnapshotService:
    def __init__(
        self,
        yfinance_provider: YFinanceProvider,
        finviz_provider: FinvizProvider,
        score_cfg: ScoreConfig | None = None,
        repository: PredictionRepository | None = None,
    ) -> None:
        self.yfinance = yfinance_provider
        self.finviz = finviz_provider
        self.score_cfg = score_cfg or ScoreConfig()
        self.repository = repository or PredictionRepository()

    async def run_daily_snapshot(self, db: Session, run_date: date | None = None) -> dict[str, int]:
        snapshot_date = run_date or date.today()
        tickers = self.repository.get_all_tracked_tickers(db)
        ok = 0
        failed = 0
        for ticker in tickers:
            try:
                await self._snapshot_analyst_ratings(db, ticker, snapshot_date)
                await self._snapshot_consensus(db, ticker, snapshot_date)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("Snapshot failed for %s: %s", ticker, exc)
                db.rollback()
        db.commit()
        return {"tracked": len(tickers), "ok": ok, "failed": failed}

    async def evaluate_expired_predictions(self, db: Session, today: date | None = None) -> dict[str, int]:
        reference = today or date.today()
        pending_analyst = self.repository.list_pending_analyst_snapshots(db, reference)

        resolved = 0
        unresolved = 0
        for snapshot in pending_analyst:
            actual = await self.yfinance.get_price_on_date(snapshot.ticker, snapshot.target_date)
            if actual is None:
                snapshot.is_unresolvable = True
                unresolved += 1
                continue

            predicted_return = self.compute_predicted_return(snapshot.price_target, snapshot.current_price)
            actual_return = self.compute_actual_return(actual, snapshot.current_price)
            error = predicted_return - actual_return
            snapshot.actual_price_at_target = actual
            snapshot.actual_return = actual_return
            snapshot.prediction_error = error
            snapshot.is_directionally_correct = self.is_directionally_correct(predicted_return, actual_return)
            resolved += 1

        pending_consensus = self.repository.list_pending_consensus_snapshots(db, reference)

        for snapshot in pending_consensus:
            actual = await self.yfinance.get_price_on_date(snapshot.ticker, snapshot.target_date)
            if actual is None:
                continue
            snapshot.actual_price_at_target = actual
            if snapshot.target_avg is not None:
                predicted_return = self.compute_predicted_return(snapshot.target_avg, snapshot.current_price)
                actual_return = self.compute_actual_return(actual, snapshot.current_price)
                snapshot.consensus_was_correct = self.is_directionally_correct(predicted_return, actual_return)

        db.commit()
        return {"resolved": resolved, "unresolvable": unresolved}

    async def recompute_scores(self, db: Session) -> dict[str, int]:
        self.repository.clear_scores(db)
        rows = self.repository.list_resolved_analyst_snapshots(db)

        grouped_global: dict[str, list[AnalystSnapshot]] = {}
        grouped_ticker: dict[tuple[str, str], list[AnalystSnapshot]] = {}
        for row in rows:
            grouped_global.setdefault(row.firm, []).append(row)
            grouped_ticker.setdefault((row.firm, row.ticker), []).append(row)

        total_written = 0
        now = datetime.utcnow()

        for firm, records in grouped_global.items():
            score = self._build_score(firm=firm, ticker=None, rows=records, last_updated=now)
            db.add(score)
            total_written += 1

        for (firm, ticker), records in grouped_ticker.items():
            score = self._build_score(firm=firm, ticker=ticker, rows=records, last_updated=now)
            db.add(score)
            total_written += 1

        db.commit()
        return {"scores_written": total_written, "source_rows": len(rows)}

    async def run_nightly_pipeline(self, db: Session, run_date: date | None = None) -> dict[str, dict[str, int]]:
        snapshot = await self.run_daily_snapshot(db, run_date=run_date)
        evaluate = await self.evaluate_expired_predictions(db, today=run_date)
        recompute = await self.recompute_scores(db)
        return {"snapshot": snapshot, "evaluate": evaluate, "recompute": recompute}

    def _build_score(self, firm: str, ticker: str | None, rows: list[AnalystSnapshot], last_updated: datetime) -> AnalystScore:
        total = len(rows)
        if total < self.score_cfg.min_predictions:
            return AnalystScore(
                firm=firm,
                ticker=ticker,
                total_predictions=total,
                success_rate=None,
                avg_return_error=None,
                avg_absolute_error=None,
                directional_accuracy=None,
                composite_score=None,
                best_call_ticker=None,
                worst_call_ticker=None,
                last_updated=last_updated,
            )

        errors = [abs(r.prediction_error or 0.0) for r in rows]
        raw_errors = [r.prediction_error or 0.0 for r in rows]
        directional = [bool(r.is_directionally_correct) for r in rows if r.is_directionally_correct is not None]
        success_count = sum(1 for e in errors if e < self.score_cfg.success_threshold)

        success_rate = success_count / total
        avg_abs_error = sum(errors) / total
        avg_return_error = sum(raw_errors) / total
        directional_accuracy = sum(1 for d in directional if d) / len(directional) if directional else 0.0
        composite = self.composite_score(success_rate, directional_accuracy, avg_abs_error)

        sorted_rows = sorted(rows, key=lambda r: abs(r.prediction_error or 0.0))
        best = sorted_rows[0].ticker if sorted_rows else None
        worst = sorted_rows[-1].ticker if sorted_rows else None

        return AnalystScore(
            firm=firm,
            ticker=ticker,
            total_predictions=total,
            success_rate=success_rate,
            avg_return_error=avg_return_error,
            avg_absolute_error=avg_abs_error,
            directional_accuracy=directional_accuracy,
            composite_score=composite,
            best_call_ticker=best,
            worst_call_ticker=worst,
            last_updated=last_updated,
        )

    @staticmethod
    def compute_predicted_return(price_target: float | None, current_price: float) -> float:
        if price_target is None or current_price == 0:
            return 0.0
        return (price_target - current_price) / current_price

    @staticmethod
    def compute_actual_return(actual_price: float, current_price: float) -> float:
        if current_price == 0:
            return 0.0
        return (actual_price - current_price) / current_price

    @staticmethod
    def is_directionally_correct(predicted_return: float, actual_return: float) -> bool:
        return (predicted_return > 0 and actual_return > 0) or (predicted_return < 0 and actual_return < 0) or (
            predicted_return == 0 and actual_return == 0
        )

    @staticmethod
    def composite_score(success_rate: float, directional_accuracy: float, avg_absolute_error: float) -> float:
        score = 0.4 * success_rate + 0.3 * directional_accuracy + 0.3 * (1 - avg_absolute_error)
        return max(0.0, min(1.0, score))

    async def _snapshot_analyst_ratings(self, db: Session, ticker: str, snapshot_date: date) -> None:
        ratings = await self.finviz.get_analyst_ratings(ticker)
        current_price = await self.yfinance.get_current_price(ticker)

        for row in ratings:
            firm = str(row.get("firm") or "Unknown")
            existing = self.repository.get_analyst_snapshot(db, ticker=ticker, snapshot_date=snapshot_date, firm=firm)
            price_target = _to_float(row.get("price_target"))
            implied_return = self.compute_predicted_return(price_target, current_price) if price_target is not None else None
            target_date = snapshot_date + timedelta(days=365)

            if existing:
                existing.analyst_name = row.get("analyst_name")
                existing.action = row.get("action")
                existing.rating = str(row.get("rating") or "N/A")
                existing.price_target = price_target
                existing.current_price = current_price
                existing.implied_return = implied_return
                existing.target_date = target_date
                existing.source = "finvizfinance"
            else:
                db.add(
                    AnalystSnapshot(
                        ticker=ticker,
                        snapshot_date=snapshot_date,
                        firm=firm,
                        analyst_name=row.get("analyst_name"),
                        action=row.get("action"),
                        rating=str(row.get("rating") or "N/A"),
                        price_target=price_target,
                        current_price=current_price,
                        implied_return=implied_return,
                        target_date=target_date,
                        source="finvizfinance",
                    )
                )

    async def _snapshot_consensus(self, db: Session, ticker: str, snapshot_date: date) -> None:
        targets = await self.yfinance.get_consensus_targets(ticker)
        current_price = _to_float(targets.get("current"))
        if current_price is None:
            current_price = await self.yfinance.get_current_price(ticker)

        target_avg = _to_float(targets.get("avg"))
        implied_upside = self.compute_predicted_return(target_avg, current_price) if target_avg is not None else None

        existing = self.repository.get_consensus_snapshot(db, ticker=ticker, snapshot_date=snapshot_date)

        payload = {
            "target_low": _to_float(targets.get("low")),
            "target_avg": target_avg,
            "target_median": _to_float(targets.get("median")),
            "target_high": _to_float(targets.get("high")),
            "analyst_count": _to_int(targets.get("count")),
            "consensus_rating": targets.get("consensus"),
            "current_price": current_price,
            "implied_upside": implied_upside,
            "target_date": snapshot_date + timedelta(days=365),
            "source": "yfinance",
        }

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            return

        db.add(
            ConsensusSnapshot(
                ticker=ticker,
                snapshot_date=snapshot_date,
                **payload,
            )
        )


async def refresh_tracked_prices(
    db: Session,
    yfinance_provider: YFinanceProvider,
    repository: PredictionRepository | None = None,
) -> dict[str, int]:
    repo = repository or PredictionRepository()
    tickers = repo.get_all_tracked_tickers(db)
    refreshed = 0
    failed = 0
    for ticker in tickers:
        try:
            await yfinance_provider.get_current_price(ticker)
            refreshed += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return {"tickers": len(tickers), "refreshed": refreshed, "failed": failed}


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
