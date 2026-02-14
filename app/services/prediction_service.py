from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import SERVICE_RECOVERABLE_ERRORS
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
            except SERVICE_RECOVERABLE_ERRORS as exc:
                failed += 1
                logger.warning("Snapshot failed for %s: %s", ticker, exc)
                db.rollback()
        db.commit()
        return {"tracked": len(tickers), "ok": ok, "failed": failed}

    async def run_snapshot_for_symbol(
        self,
        db: Session,
        ticker: str,
        run_date: date | None = None,
    ) -> dict[str, int | str]:
        snapshot_date = run_date or date.today()
        symbol = ticker.strip().upper()
        if not symbol:
            return {"tracked": 0, "ok": 0, "failed": 1, "ticker": ""}
        try:
            await self._snapshot_analyst_ratings(db, symbol, snapshot_date)
            await self._snapshot_consensus(db, symbol, snapshot_date)
            db.commit()
            return {"tracked": 1, "ok": 1, "failed": 0, "ticker": symbol}
        except SERVICE_RECOVERABLE_ERRORS as exc:
            logger.warning("Snapshot failed for %s: %s", symbol, exc)
            db.rollback()
            return {"tracked": 1, "ok": 0, "failed": 1, "ticker": symbol}

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

        deduped_rows: dict[str, dict[str, object]] = {}
        for row in ratings:
            if not isinstance(row, dict):
                continue
            firm = str(row.get("firm") or row.get("analyst_name") or "").strip()
            if not firm:
                continue
            key = firm.casefold()
            existing = deduped_rows.get(key)
            if existing is None:
                deduped_rows[key] = {**row, "firm": firm}
                continue
            # Prefer records that include a usable target when duplicate firms appear.
            if _to_float(existing.get("price_target")) is None and _to_float(row.get("price_target")) is not None:
                deduped_rows[key] = {**row, "firm": firm}

        for row in deduped_rows.values():
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


class PredictionService:
    """Query facade for prediction APIs/UI, plus manual snapshot trigger."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        score_cfg: ScoreConfig | None = None,
        snapshot_service: PredictionSnapshotService | None = None,
        yfinance_provider: YFinanceProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._score_cfg = score_cfg or ScoreConfig()
        self._snapshot_service = snapshot_service
        self._yfinance_provider = yfinance_provider

    async def get_analyst_scorecard(self, symbol: str) -> list[dict[str, object]]:
        upper_symbol = symbol.upper()
        with self._session_factory() as db:
            rows = (
                db.query(AnalystSnapshot)
                .filter(func.upper(AnalystSnapshot.ticker) == upper_symbol)
                .order_by(AnalystSnapshot.snapshot_date.desc())
                .all()
            )

        if not rows:
            return []

        by_firm: dict[str, list[AnalystSnapshot]] = {}
        for row in rows:
            by_firm.setdefault(row.firm, []).append(row)

        result: list[dict[str, object]] = []
        for firm, records in by_firm.items():
            latest = records[0]
            resolved = [r for r in records if r.prediction_error is not None and not r.is_unresolvable]
            total = len(records)
            insufficient = len(resolved) < self._score_cfg.min_predictions

            success_rate = 0.0
            direction_rate = 0.0
            avg_error = 0.0
            composite = 0.0
            if not insufficient:
                errors = [abs(r.prediction_error or 0.0) for r in resolved]
                success_rate = (sum(1 for e in errors if e < self._score_cfg.success_threshold) / len(resolved)) * 100
                direction_rate = (
                    sum(1 for r in resolved if r.is_directionally_correct is True) / len(resolved)
                ) * 100
                avg_error = (sum(errors) / len(resolved)) * 100
                composite = (
                    PredictionSnapshotService.composite_score(
                        success_rate=success_rate / 100,
                        directional_accuracy=direction_rate / 100,
                        avg_absolute_error=avg_error / 100,
                    )
                    * 100
                )

            result.append(
                {
                    "firm": firm,
                    "total_predictions": total,
                    "insufficient": insufficient,
                    "success_rate": success_rate,
                    "direction_rate": direction_rate,
                    "avg_error": avg_error,
                    "composite": composite,
                    "latest_rating": latest.rating or "N/A",
                    "latest_target": f"{latest.price_target:.2f}" if latest.price_target is not None else "N/A",
                }
            )

        return sorted(
            result,
            key=lambda row: (bool(row.get("insufficient")), -float(row.get("composite") or 0.0)),
        )

    async def get_consensus_history(self, symbol: str) -> list[dict[str, object]]:
        upper_symbol = symbol.upper()
        with self._session_factory() as db:
            rows = (
                db.query(ConsensusSnapshot)
                .filter(func.upper(ConsensusSnapshot.ticker) == upper_symbol)
                .order_by(ConsensusSnapshot.snapshot_date.asc())
                .all()
            )
        return [
            {
                "date": row.snapshot_date.isoformat(),
                "avg_target": row.target_avg,
                "low_target": row.target_low,
                "high_target": row.target_high,
                "resolved": row.actual_price_at_target is not None,
                "accurate": row.consensus_was_correct,
            }
            for row in rows
        ]

    async def get_top_analysts(
        self,
        *,
        sector: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, object]]:
        with self._session_factory() as db:
            ticker_rows = db.query(AnalystScore).filter(
                AnalystScore.ticker.is_not(None), AnalystScore.composite_score.is_not(None)
            ).all()
            global_rows = db.query(AnalystScore).filter(
                AnalystScore.ticker.is_(None), AnalystScore.composite_score.is_not(None)
            ).all()

        filtered_ticker_rows = ticker_rows
        if symbol:
            upper_symbol = symbol.upper()
            filtered_ticker_rows = [row for row in filtered_ticker_rows if (row.ticker or "").upper() == upper_symbol]

        if sector:
            filtered_ticker_rows = await self._filter_scores_by_sector(filtered_ticker_rows, sector)

        if symbol or sector:
            return self._aggregate_ticker_scores(filtered_ticker_rows)

        tickers_per_firm: dict[str, set[str]] = {}
        for row in ticker_rows:
            if row.ticker:
                tickers_per_firm.setdefault(row.firm, set()).add(row.ticker)

        leaderboard: list[dict[str, object]] = []
        for score in global_rows:
            if (
                score.success_rate is None
                or score.directional_accuracy is None
                or score.avg_absolute_error is None
                or score.composite_score is None
            ):
                continue
            leaderboard.append(
                {
                    "firm": score.firm,
                    "total_predictions": score.total_predictions,
                    "tickers_covered": len(tickers_per_firm.get(score.firm, set())),
                    "success_rate": score.success_rate * 100,
                    "direction_rate": score.directional_accuracy * 100,
                    "avg_error": score.avg_absolute_error * 100,
                    "composite": score.composite_score * 100,
                    "best_call": (
                        {"symbol": score.best_call_ticker, "detail": "best call"}
                        if score.best_call_ticker
                        else None
                    ),
                    "worst_call": (
                        {"symbol": score.worst_call_ticker, "detail": "worst call"}
                        if score.worst_call_ticker
                        else None
                    ),
                }
            )
        return leaderboard

    async def _filter_scores_by_sector(self, rows: list[AnalystScore], sector: str) -> list[AnalystScore]:
        if self._yfinance_provider is None:
            return []

        target = sector.strip().lower()
        if not target:
            return rows

        tickers = sorted({(row.ticker or "").upper() for row in rows if row.ticker})
        ticker_sectors: dict[str, str] = {}
        for ticker in tickers:
            try:
                profile = await self._yfinance_provider.get_company_profile(ticker)
                profile_sector = str(profile.get("sector") or "").strip()
                if profile_sector:
                    ticker_sectors[ticker] = profile_sector.lower()
            except SERVICE_RECOVERABLE_ERRORS:
                continue
        return [row for row in rows if row.ticker and ticker_sectors.get(row.ticker.upper()) == target]

    def _aggregate_ticker_scores(self, rows: list[AnalystScore]) -> list[dict[str, object]]:
        grouped: dict[str, list[AnalystScore]] = defaultdict(list)
        for row in rows:
            grouped[row.firm].append(row)

        leaderboard: list[dict[str, object]] = []
        for firm, firm_rows in grouped.items():
            valid = [
                row
                for row in firm_rows
                if row.success_rate is not None
                and row.directional_accuracy is not None
                and row.avg_absolute_error is not None
                and row.composite_score is not None
            ]
            if not valid:
                continue

            total_predictions = sum(row.total_predictions for row in valid)
            if total_predictions <= 0:
                continue

            def weighted(attr: str) -> float:
                return (
                    sum(float(getattr(row, attr) or 0.0) * row.total_predictions for row in valid) / total_predictions
                )

            best = max(valid, key=lambda row: float(row.composite_score or 0.0))
            worst = min(valid, key=lambda row: float(row.composite_score or 0.0))
            tickers_covered = len({row.ticker for row in valid if row.ticker})

            leaderboard.append(
                {
                    "firm": firm,
                    "total_predictions": total_predictions,
                    "tickers_covered": tickers_covered,
                    "success_rate": weighted("success_rate") * 100,
                    "direction_rate": weighted("directional_accuracy") * 100,
                    "avg_error": weighted("avg_absolute_error") * 100,
                    "composite": weighted("composite_score") * 100,
                    "best_call": {"symbol": best.ticker, "detail": "best call"} if best.ticker else None,
                    "worst_call": {"symbol": worst.ticker, "detail": "worst call"} if worst.ticker else None,
                }
            )

        leaderboard.sort(key=lambda row: float(row.get("composite") or 0.0), reverse=True)
        return leaderboard

    async def get_firm_history(self, symbol: str, firm: str) -> list[dict[str, object]]:
        upper_symbol = symbol.upper()
        with self._session_factory() as db:
            rows = (
                db.query(AnalystSnapshot)
                .filter(
                    func.upper(AnalystSnapshot.ticker) == upper_symbol,
                    func.lower(AnalystSnapshot.firm) == firm.lower(),
                )
                .order_by(AnalystSnapshot.snapshot_date.desc())
                .all()
            )
        return [
            {
                "date": row.snapshot_date.isoformat(),
                "firm": row.firm,
                "rating": row.rating,
                "target": row.price_target,
                "implied_return": row.implied_return,
                "resolved": row.actual_price_at_target is not None,
            }
            for row in rows
        ]

    async def run_snapshot(self) -> dict[str, object]:
        if self._snapshot_service is None:
            return {"status": "error", "message": "Snapshot service unavailable"}
        db = self._session_factory()
        try:
            result = await self._snapshot_service.run_daily_snapshot(db)
            return {"status": "ok", "snapshots_created": result.get("ok", 0), **result}
        finally:
            db.close()

    async def run_snapshot_for_symbol(self, symbol: str) -> dict[str, object]:
        if self._snapshot_service is None:
            return {"status": "error", "message": "Snapshot service unavailable"}
        db = self._session_factory()
        try:
            result = await self._snapshot_service.run_snapshot_for_symbol(db, symbol)
            return {"status": "ok", "snapshots_created": result.get("ok", 0), **result}
        finally:
            db.close()

    async def get_prediction_summary(self, symbol: str) -> dict[str, object]:
        upper_symbol = symbol.upper()
        today = date.today()
        with self._session_factory() as db:
            rows = db.query(AnalystSnapshot).filter(func.upper(AnalystSnapshot.ticker) == upper_symbol).all()
            consensus_rows = (
                db.query(ConsensusSnapshot)
                .filter(func.upper(ConsensusSnapshot.ticker) == upper_symbol)
                .order_by(ConsensusSnapshot.snapshot_date.desc())
                .all()
            )

        resolved = sum(1 for row in rows if row.actual_price_at_target is not None and not row.is_unresolvable)
        active = sum(1 for row in rows if row.actual_price_at_target is None and not row.is_unresolvable and row.target_date >= today)

        resolved_consensus = [row for row in consensus_rows if row.consensus_was_correct is not None]
        accuracy = None
        if resolved_consensus:
            accuracy = (
                sum(1 for row in resolved_consensus if row.consensus_was_correct is True) / len(resolved_consensus)
            ) * 100

        latest_target = next((row.target_avg for row in consensus_rows if row.target_avg is not None), None)
        if latest_target is None and self._yfinance_provider is not None:
            try:
                live_consensus = await self._yfinance_provider.get_consensus_targets(upper_symbol)
                latest_target = _to_float(live_consensus.get("avg"))
            except SERVICE_RECOVERABLE_ERRORS as exc:
                logger.debug("Live consensus summary fallback unavailable for %s: %s", upper_symbol, exc)
        return {
            "active": active,
            "resolved": resolved,
            "accuracy": accuracy,
            "consensus_target": f"${latest_target:.2f}" if latest_target is not None else "N/A",
        }

    async def get_prediction_history(self, symbol: str) -> list[dict[str, object]]:
        upper_symbol = symbol.upper()
        today = date.today()
        with self._session_factory() as db:
            rows = (
                db.query(AnalystSnapshot)
                .filter(func.upper(AnalystSnapshot.ticker) == upper_symbol)
                .order_by(AnalystSnapshot.snapshot_date.desc())
                .limit(50)
                .all()
            )

        history: list[dict[str, object]] = []
        for row in rows:
            resolved = row.actual_price_at_target is not None
            error = abs(row.prediction_error) if row.prediction_error is not None else None
            history.append(
                {
                    "snapshot_date": row.snapshot_date.isoformat(),
                    "date": row.snapshot_date.strftime("%b %d"),
                    "year": row.snapshot_date.year,
                    "firm": row.firm,
                    "source": row.source,
                    "rating": row.rating,
                    "action": row.action or "Updated",
                    "target": f"{row.price_target:.2f}" if row.price_target is not None else "N/A",
                    "implied_return": _fmt_pct(row.implied_return),
                    "resolved": resolved,
                    "resolve_date": row.target_date.isoformat() if row.target_date else "N/A",
                    "actual_price": f"{row.actual_price_at_target:.2f}" if row.actual_price_at_target is not None else "N/A",
                    "actual_return": _fmt_pct(row.actual_return),
                    "accurate": bool(error is not None and error < self._score_cfg.success_threshold),
                    "error_pct": _fmt_pct(error),
                    "days_left": max((row.target_date - today).days, 0) if row.target_date else 0,
                }
            )
        return history


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
        except SERVICE_RECOVERABLE_ERRORS:
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


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"
