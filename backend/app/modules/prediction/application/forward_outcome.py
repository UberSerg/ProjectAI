"""Forward Outcome Evaluator V0 — mature 20-observation mechanical returns.

Reuses Dataset PIT V2 ForwardReturnLabelCalculator + H4A mechanical adjustment.
Never mutates original ForwardPrediction numeric fields.
Never applies dividends / total return.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.market.models import Candle
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.market.application.mechanical_adjustment import MechanicalAction, load_mechanical_actions
from app.modules.prediction.application.forward_config import FORWARD_BASIC_FS_CODE, FORWARD_BASIC_FS_VERSION
from app.modules.prediction.infrastructure import forward_outcome_repository as repo
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction, ForwardPredictionBatch

HORIZON = 20
EVALUATOR_VERSION = repo.EVALUATOR_VERSION


@dataclass
class OutcomeEvalResult:
    status: str
    summary: dict[str, Any]


def _feature_set_id(session: Session):
    row = session.scalar(
        select(FeatureSet).where(
            FeatureSet.code == FORWARD_BASIC_FS_CODE,
            FeatureSet.version == FORWARD_BASIC_FS_VERSION,
        )
    )
    return row.id if row is not None else None


def _discontinuity_dates(session: Session, instrument_id: int, feature_set_id: int | None) -> set[date]:
    if feature_set_id is None:
        return set()
    rows = session.scalars(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == instrument_id,
            InstrumentFeatureDaily.feature_set_id == feature_set_id,
        )
    ).all()
    out: set[date] = set()
    for row in rows:
        flags = row.quality_flags or {}
        if flags.get("price_discontinuity"):
            out.add(row.date)
    return out


def _price_observations(session: Session, instrument_id: int) -> list[PriceObservation]:
    candles = list(
        session.scalars(
            select(Candle)
            .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
            .order_by(Candle.timestamp.asc())
        ).all()
    )
    return [
        PriceObservation(date=c.timestamp.date(), close=float(c.close), candle_id=c.id)
        for c in candles
        if c.close is not None
    ]


def count_future_trading_observations(session: Session, as_of: date, instrument_id: int | None = None) -> int:
    """Count genuine trading observations strictly after as_of (not calendar days)."""
    stmt = select(Candle).where(Candle.timeframe == "1d")
    if instrument_id is not None:
        stmt = stmt.where(Candle.instrument_id == instrument_id)
    dates = sorted({c.timestamp.date() for c in session.scalars(stmt).all() if c.timestamp.date() > as_of})
    return len(dates)


def cohort_future_observation_count(session: Session, as_of: date) -> int:
    """Batch-level maturity proxy: distinct market dates after as_of with any candle."""
    rows = session.scalars(select(Candle).where(Candle.timeframe == "1d")).all()
    dates = sorted({c.timestamp.date() for c in rows if c.timestamp.date() > as_of})
    return len(dates)


def _spearman(pred: list[float], realized: list[float]) -> float | None:
    n = len(pred)
    if n < 2:
        return None
    # Rank with average ties via scipy-free implementation
    def ranks(vals: list[float]) -> np.ndarray:
        order = np.argsort(vals)
        r = np.empty(n, dtype=float)
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = 0.5 * (i + j) + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rp = ranks(pred)
    rr = ranks(realized)
    rp = rp - rp.mean()
    rr = rr - rr.mean()
    denom = float(np.sqrt((rp * rp).sum() * (rr * rr).sum()))
    if denom <= 0:
        return None
    return float((rp * rr).sum() / denom)


def _evaluate_one(
    session: Session,
    pred: ForwardPrediction,
    *,
    feature_set_id: int | None,
    actions_by_inst: dict[int, list[MechanicalAction]],
) -> tuple[dict[str, Any], bool]:
    """Return outcome values dict and whether newly matured evaluation was produced."""
    existing = repo.get_existing_outcome(session, pred.id)
    if existing is not None and existing.status in {"EVALUATED", "INVALID"}:
        return repo.serialize_outcome(existing), False

    observations = _price_observations(session, pred.instrument_id)
    future_count = sum(1 for o in observations if o.date > pred.as_of_date)
    if future_count < HORIZON:
        values = {
            "forward_prediction_id": pred.id,
            "batch_id": pred.batch_id,
            "as_of_date": pred.as_of_date,
            "instrument_id": pred.instrument_id,
            "ticker": pred.ticker,
            "horizon_observations": HORIZON,
            "evaluator_version": EVALUATOR_VERSION,
            "target_date": None,
            "predicted_return_20d": float(pred.predicted_return_20d),
            "realized_return_20d": None,
            "prediction_error": None,
            "absolute_error": None,
            "direction_correct": None,
            "mechanical_ca_normalized": False,
            "quality_status": "PENDING",
            "status": "PENDING_OUTCOME",
            "label_flags": {"future_observations": future_count, "required": HORIZON},
            "evaluated_at": None,
        }
        row, created = repo.upsert_outcome_row(session, values)
        if not created and row.status == "PENDING_OUTCOME":
            row.label_flags = values["label_flags"]
            session.flush()
        repo.touch_prediction_outcome_status(session, pred, "PENDING_OUTCOME")
        return repo.serialize_outcome(row), False

    calc = ForwardReturnLabelCalculator(horizons=[HORIZON])
    disc = _discontinuity_dates(session, pred.instrument_id, feature_set_id)
    result = calc.calculate(
        observations,
        as_of=pred.as_of_date,
        discontinuity_dates=disc,
        mechanical_actions=actions_by_inst.get(pred.instrument_id, []),
        price_basis="mechanical_adjusted",
    )
    realized = result.labels.forward_return_20d
    target_date = result.labels.target_date_20d
    flags = dict(result.label_flags or {})
    valid = bool(result.label_valid.get("20d"))
    ca_norm = bool(flags.get("mechanical_ca_normalized_20d"))

    if not valid or realized is None:
        status = "INVALID"
        quality = "INVALID"
        err = abs_err = direction = None
        realized_f = None
    else:
        status = "EVALUATED"
        quality = "OK"
        realized_f = float(realized)
        err = realized_f - float(pred.predicted_return_20d)
        abs_err = abs(err)
        direction = (float(pred.predicted_return_20d) >= 0) == (realized_f >= 0)

    values = {
        "forward_prediction_id": pred.id,
        "batch_id": pred.batch_id,
        "as_of_date": pred.as_of_date,
        "instrument_id": pred.instrument_id,
        "ticker": pred.ticker,
        "horizon_observations": HORIZON,
        "evaluator_version": EVALUATOR_VERSION,
        "target_date": target_date,
        "predicted_return_20d": float(pred.predicted_return_20d),
        "realized_return_20d": realized_f,
        "prediction_error": err,
        "absolute_error": abs_err,
        "direction_correct": direction,
        "mechanical_ca_normalized": ca_norm,
        "quality_status": quality,
        "status": status,
        "label_flags": flags,
        "evaluated_at": datetime.now(UTC),
    }
    row, created = repo.upsert_outcome_row(session, values)
    if not created and row.status == "PENDING_OUTCOME" and status in {"EVALUATED", "INVALID"}:
        for k, v in values.items():
            if k in {"forward_prediction_id", "batch_id", "evaluator_version", "horizon_observations"}:
                continue
            setattr(row, k, v)
        session.flush()
        created = True
    repo.touch_prediction_outcome_status(session, pred, status if status != "EVALUATED" else "EVALUATED")
    return repo.serialize_outcome(row), created


def _batch_metrics(outcomes: list[repo.ForwardPredictionOutcome]) -> dict[str, Any]:
    evaluated = [o for o in outcomes if o.status == "EVALUATED" and o.realized_return_20d is not None]
    invalid = [o for o in outcomes if o.status == "INVALID"]
    pending = [o for o in outcomes if o.status == "PENDING_OUTCOME"]
    if not evaluated:
        status = "PENDING" if pending and not invalid else ("PARTIALLY_MATURED" if pending else "PENDING")
        if invalid and not pending and not evaluated:
            status = "INVALID"
        return {
            "status": status,
            "eligible_count": len(outcomes),
            "evaluated_count": 0,
            "invalid_count": len(invalid),
            "pending_count": len(pending),
            "mean_predicted": None,
            "mean_realized": None,
            "mae": None,
            "rmse": None,
            "directional_accuracy": None,
            "spearman_rank_ic": None,
            "top20_realized_mean": None,
            "bottom20_realized_mean": None,
            "top_minus_bottom_spread": None,
            "metrics": {},
        }

    preds = [float(o.predicted_return_20d) for o in evaluated]
    reals = [float(o.realized_return_20d) for o in evaluated]  # type: ignore[arg-type]
    errors = [float(o.absolute_error or 0.0) for o in evaluated]
    sq = [(float(o.prediction_error or 0.0)) ** 2 for o in evaluated]
    dirs = [1.0 if o.direction_correct else 0.0 for o in evaluated if o.direction_correct is not None]
    order = sorted(range(len(preds)), key=lambda i: -preds[i])
    n = len(order)
    top_n = max(1, int(round(n * 0.2)))
    top_idx = order[:top_n]
    bottom_idx = order[-top_n:]
    top_mean = float(np.mean([reals[i] for i in top_idx]))
    bottom_mean = float(np.mean([reals[i] for i in bottom_idx]))
    status = "EVALUATED" if not pending else "PARTIALLY_MATURED"
    return {
        "status": status,
        "eligible_count": len(outcomes),
        "evaluated_count": len(evaluated),
        "invalid_count": len(invalid),
        "pending_count": len(pending),
        "mean_predicted": float(np.mean(preds)),
        "mean_realized": float(np.mean(reals)),
        "mae": float(np.mean(errors)),
        "rmse": float(np.sqrt(np.mean(sq))),
        "directional_accuracy": float(np.mean(dirs)) if dirs else None,
        "spearman_rank_ic": _spearman(preds, reals),
        "top20_realized_mean": top_mean,
        "bottom20_realized_mean": bottom_mean,
        "top_minus_bottom_spread": top_mean - bottom_mean,
        "metrics": {"top_n": top_n, "bottom_n": top_n},
    }


def evaluate_forward_outcomes(
    session: Session,
    *,
    batch_id: int | None = None,
) -> OutcomeEvalResult:
    """Evaluate matured Forward predictions. Idempotent. Never fabricates outcomes."""
    from sqlalchemy import select as sa_select

    from app.modules.prediction.infrastructure.forward_outcome_models import ForwardPredictionOutcome

    feature_set_id = _feature_set_id(session)
    preds = repo.list_pending_predictions(session, batch_id=batch_id)
    if not preds:
        return OutcomeEvalResult(status="NO_CHANGES", summary={"evaluated_new": 0, "batches": []})

    instrument_ids = sorted({p.instrument_id for p in preds})
    actions_by_inst = {iid: load_mechanical_actions(session, iid) for iid in instrument_ids}

    created = 0
    matured = 0
    for pred in preds:
        _, is_new = _evaluate_one(session, pred, feature_set_id=feature_set_id, actions_by_inst=actions_by_inst)
        if is_new:
            created += 1
            matured += 1

    batch_ids = sorted({p.batch_id for p in preds})
    batch_summaries: list[dict[str, Any]] = []
    for bid in batch_ids:
        outcomes = list(
            session.scalars(
                sa_select(ForwardPredictionOutcome).where(ForwardPredictionOutcome.batch_id == bid)
            ).all()
        )
        metrics = _batch_metrics(outcomes)
        batch = session.get(ForwardPredictionBatch, bid)
        obs = cohort_future_observation_count(session, batch.as_of_date) if batch is not None else 0
        metrics["metrics"] = {
            **(metrics.get("metrics") or {}),
            "future_trading_observations": obs,
            "required_observations": HORIZON,
            "as_of": batch.as_of_date.isoformat() if batch else None,
        }
        values = {
            "batch_id": bid,
            "evaluator_version": EVALUATOR_VERSION,
            "horizon_observations": HORIZON,
            "evaluated_at": datetime.now(UTC) if metrics["evaluated_count"] else None,
            **metrics,
        }
        row, _ = repo.upsert_batch_evaluation(session, values)
        batch_summaries.append(repo.serialize_batch_evaluation(row) or {})

    status = "NO_CHANGES" if created == 0 and matured == 0 else "SUCCESS"
    # If all still pending, still SUCCESS of evaluation pass with pending state
    if all((b.get("status") == "PENDING") for b in batch_summaries) and created == 0:
        status = "NO_CHANGES"

    return OutcomeEvalResult(
        status=status,
        summary={
            "evaluated_new": created,
            "prediction_count": len(preds),
            "batches": batch_summaries,
            "evaluator_version": EVALUATOR_VERSION,
            "horizon_observations": HORIZON,
        },
    )


def get_batch_evaluation_payload(session: Session, batch_id: int) -> dict[str, Any]:
    batch = session.get(ForwardPredictionBatch, batch_id)
    if batch is None:
        return {"error": "not_found", "batch_id": batch_id}
    evaluation = repo.get_batch_evaluation(session, batch_id)
    obs = cohort_future_observation_count(session, batch.as_of_date)
    return {
        "batch_id": batch_id,
        "as_of_date": batch.as_of_date.isoformat(),
        "future_trading_observations": obs,
        "required_observations": HORIZON,
        "matured": obs >= HORIZON,
        "evaluation": repo.serialize_batch_evaluation(evaluation),
    }
