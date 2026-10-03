"""Prospective Evidence Bridge V1 — read-only Personal Decision Memory + Forward Predictions.

Never mutates captures, outcomes, operation links, or forward prediction/outcome/evaluation rows.
No combined master score / kraken_score / overall_accuracy.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.memory.application.decision_memory_service import SAMPLE_WARNING_MIN
from app.modules.memory.domain.decision_memory import (
    ALIGNED,
    DIRECTIONAL_ACTIONS,
    HORIZONS,
    LINK_SOURCE_USER_CONFIRMED,
    NOT_ALIGNED,
    OUTCOME_BASELINE_UNAVAILABLE,
    OUTCOME_DATA_UNAVAILABLE,
    OUTCOME_PENDING,
    OUTCOME_READY,
    RETURN_TYPE_PRICE,
)
from app.modules.memory.infrastructure.models import (
    PersonalDecisionAction,
    PersonalDecisionOperationLink,
    PersonalDecisionOutcome,
    PersonalDecisionRecord,
)
from app.modules.prediction.application.forward_outcome import _batch_metrics
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction, ForwardPredictionBatch
from app.modules.prediction.infrastructure.forward_outcome_models import (
    ForwardBatchEvaluation,
    ForwardPredictionOutcome,
)
from app.modules.prediction.infrastructure.forward_outcome_repository import serialize_batch_evaluation

PROSPECTIVE_EVIDENCE_VERSION = "ProspectiveEvidenceV1"
MIN_SAMPLE = 5
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
STATUS_OBSERVED = "OBSERVED"
SEMANTIC_EXPECTED_RETURN = "EXPECTED_RETURN"
SEMANTIC_RANKING_SCORE = "RANKING_SCORE"

LINK_NOT_CAUSALITY_NOTE = (
    "A confirmed PersonalOperation link is metadata only: it records that a journal trade was "
    "associated with a captured recommendation. The linked trade does not mean the recommendation "
    "caused the trade."
)

LIMITATIONS: tuple[str, ...] = (
    "NO_COMBINED_MASTER_SCORE",
    "NOT_KRAKEN_ACCURACY",
    "NOT_CAUSAL_EVIDENCE",
    "CONFIRMED_OPERATION_LINK_IS_METADATA_ONLY",
    "LINKED_TRADE_DOES_NOT_MEAN_RECOMMENDATION_CAUSED_TRADE",
    "PRICE_RETURN_UNADJUSTED_FOR_DIVIDENDS_AND_SPLITS",
    "NOT_PORTFOLIO_PERFORMANCE",
    "SMALL_SAMPLE_NOT_STATISTICAL_EVIDENCE",
    "PENDING_FORWARD_OUTCOMES_ARE_NOT_FABRICATED",
    "RANKING_SCORE_IS_NOT_EXPECTED_RETURN",
    "RANKER_METRICS_EXCLUDE_RMSE_MAE",
    "DIRECTION_ALIGNMENT_ONLY_WHERE_SEMANTIC_APPLIES",
)

_UNAVAILABLE_STATUSES = frozenset({OUTCOME_DATA_UNAVAILABLE, OUTCOME_BASELINE_UNAVAILABLE})
_RANKER_FORBIDDEN_METRICS = frozenset({"rmse", "mae", "RMSE", "MAE"})


def _dec(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:  # noqa: BLE001 — malformed stored numeric is skipped, not evidence
        return None
    return out if out.is_finite() else None


def _fmt_decimal(value: Decimal | None, quant: str = "0.00000001") -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(quant)), "f")


def _sample_status(n: int) -> str:
    return STATUS_INSUFFICIENT_SAMPLE if n < MIN_SAMPLE else STATUS_OBSERVED


def _return_stats(values: list[Decimal]) -> dict[str, Any]:
    n = len(values)
    status = _sample_status(n)
    if n < MIN_SAMPLE:
        return {
            "n": n,
            "status": status,
            "mean_price_return": None,
            "median_price_return": None,
            "sample_warning": True,
        }
    mean_v = sum(values, Decimal("0")) / Decimal(n)
    median_v = Decimal(str(median(values)))
    return {
        "n": n,
        "status": status,
        "mean_price_return": _fmt_decimal(mean_v),
        "median_price_return": _fmt_decimal(median_v),
        "sample_warning": n < SAMPLE_WARNING_MIN,
    }


def _alignment_stats(labels: list[str]) -> dict[str, Any]:
    n = len(labels)
    aligned = sum(1 for label in labels if label == ALIGNED)
    not_aligned = sum(1 for label in labels if label == NOT_ALIGNED)
    status = _sample_status(n)
    rate = None
    if n >= MIN_SAMPLE:
        rate = format((Decimal(aligned) / Decimal(n)).quantize(Decimal("0.0001")), "f")
    return {
        "n": n,
        "aligned_count": aligned,
        "not_aligned_count": not_aligned,
        "alignment_rate": rate,
        "status": status,
        "applies_to": sorted(DIRECTIONAL_ACTIONS),
        "sample_warning": n < SAMPLE_WARNING_MIN,
        "note": "Direction alignment is descriptive co-occurrence, not causality and not a system accuracy score.",
    }


def _select_all(session: Session, stmt: Any) -> list[Any]:
    return list(session.scalars(stmt).all())


def _load_pdm(
    memory_session: Session,
    *,
    portfolio_id: int | None,
) -> tuple[
    list[PersonalDecisionRecord],
    list[PersonalDecisionAction],
    list[PersonalDecisionOutcome],
    list[PersonalDecisionOperationLink],
]:
    rec_stmt = select(PersonalDecisionRecord)
    if portfolio_id is not None:
        rec_stmt = rec_stmt.where(PersonalDecisionRecord.portfolio_id == portfolio_id)
    records = _select_all(memory_session, rec_stmt)
    record_ids = [int(row.id) for row in records]
    if not record_ids:
        return records, [], [], []

    actions = _select_all(
        memory_session,
        select(PersonalDecisionAction).where(PersonalDecisionAction.decision_record_id.in_(record_ids)),
    )
    action_ids = [int(row.id) for row in actions]
    if not action_ids:
        return records, actions, [], []

    outcomes = _select_all(
        memory_session,
        select(PersonalDecisionOutcome).where(PersonalDecisionOutcome.decision_action_id.in_(action_ids)),
    )
    link_stmt = select(PersonalDecisionOperationLink).where(
        PersonalDecisionOperationLink.decision_action_id.in_(action_ids),
        PersonalDecisionOperationLink.active.is_(True),
    )
    if portfolio_id is not None:
        link_stmt = link_stmt.where(PersonalDecisionOperationLink.portfolio_id == portfolio_id)
    links = _select_all(memory_session, link_stmt)
    return records, actions, outcomes, links


def summarize_personal_decision_memory(
    records: list[PersonalDecisionRecord],
    actions: list[PersonalDecisionAction],
    outcomes: list[PersonalDecisionOutcome],
    links: list[PersonalDecisionOperationLink],
) -> dict[str, Any]:
    action_by_id = {int(a.id): a for a in actions}
    action_counts: dict[str, int] = defaultdict(int)
    for action in actions:
        action_counts[str(action.action)] += 1

    by_horizon: dict[int, list[PersonalDecisionOutcome]] = {h: [] for h in HORIZONS}
    for outcome in outcomes:
        by_horizon.setdefault(int(outcome.horizon_sessions), []).append(outcome)

    horizons: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        subset = by_horizon.get(horizon, [])
        ready = [o for o in subset if o.status == OUTCOME_READY]
        pending = [o for o in subset if o.status == OUTCOME_PENDING]
        unavailable = [o for o in subset if o.status in _UNAVAILABLE_STATUSES]
        returns = [_dec(o.forward_return) for o in ready if o.return_type == RETURN_TYPE_PRICE]
        returns_ok = [v for v in returns if v is not None]
        directional = [
            str(o.directional_alignment)
            for o in ready
            if o.directional_alignment is not None
            and action_by_id.get(int(o.decision_action_id)) is not None
            and action_by_id[int(o.decision_action_id)].action in DIRECTIONAL_ACTIONS
        ]
        horizons.append(
            {
                "horizon_sessions": horizon,
                "matured_count": len(ready),
                "pending_count": len(pending),
                "unavailable_count": len(unavailable),
                "unavailable_breakdown": {
                    OUTCOME_DATA_UNAVAILABLE: sum(1 for o in unavailable if o.status == OUTCOME_DATA_UNAVAILABLE),
                    OUTCOME_BASELINE_UNAVAILABLE: sum(
                        1 for o in unavailable if o.status == OUTCOME_BASELINE_UNAVAILABLE
                    ),
                },
                "price_return": _return_stats(returns_ok),
                "direction_alignment": _alignment_stats(directional),
            }
        )

    strata_action: dict[str, list[Decimal]] = defaultdict(list)
    strata_instrument: dict[str, list[Decimal]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.status != OUTCOME_READY or outcome.return_type != RETURN_TYPE_PRICE:
            continue
        value = _dec(outcome.forward_return)
        if value is None:
            continue
        action = action_by_id.get(int(outcome.decision_action_id))
        if action is None:
            continue
        strata_action[str(action.action)].append(value)
        if action.instrument_id is not None:
            instrument_key = str(action.instrument_id)
        else:
            instrument_key = action.symbol or "UNRESOLVED"
        strata_instrument[instrument_key].append(value)

    confirmed = [
        link
        for link in links
        if bool(link.active) and str(link.link_source or LINK_SOURCE_USER_CONFIRMED) == LINK_SOURCE_USER_CONFIRMED
    ]
    return {
        "captures_total": len(records),
        "actions_total": len(actions),
        "action_counts": dict(sorted(action_counts.items())),
        "return_type": RETURN_TYPE_PRICE,
        "horizons": horizons,
        "stratification": {
            "by_action_type": {
                name: _return_stats(vals)
                for name, vals in sorted(strata_action.items())
                if len(vals) >= MIN_SAMPLE
            },
            "by_instrument": {
                name: _return_stats(vals)
                for name, vals in sorted(strata_instrument.items())
                if len(vals) >= MIN_SAMPLE
            },
            "omitted_small_strata_rule": (
                f"n < {MIN_SAMPLE} -> {STATUS_INSUFFICIENT_SAMPLE}, aggregates not shown as evidence"
            ),
        },
        "confirmed_operation_links": {
            "count": len(confirmed),
            "role": "METADATA_ONLY",
            "causality_claim": False,
            "linked_trade_means_recommendation_caused_trade": False,
            "note": LINK_NOT_CAUSALITY_NOTE,
        },
    }


def _strip_ranker_error_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    out = {
        "prediction_semantic": SEMANTIC_RANKING_SCORE,
        "status": metrics.get("status"),
        "eligible_count": metrics.get("eligible_count"),
        "evaluated_count": metrics.get("evaluated_count"),
        "invalid_count": metrics.get("invalid_count"),
        "pending_count": metrics.get("pending_count"),
        "spearman_rank_ic": metrics.get("spearman_rank_ic"),
        "top20_realized_mean": metrics.get("top20_realized_mean"),
        "bottom20_realized_mean": metrics.get("bottom20_realized_mean"),
        "top_minus_bottom_spread": metrics.get("top_minus_bottom_spread"),
        "mean_ranking_score": metrics.get("mean_predicted"),
        "mean_realized": metrics.get("mean_realized"),
        "metrics": metrics.get("metrics") or {},
        "evaluated_at": metrics.get("evaluated_at"),
    }
    for key in list(out):
        if str(key).lower() in {"rmse", "mae"}:
            out.pop(key, None)
    return out


def _expected_return_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "prediction_semantic": SEMANTIC_EXPECTED_RETURN,
        "status": metrics.get("status"),
        "eligible_count": metrics.get("eligible_count"),
        "evaluated_count": metrics.get("evaluated_count"),
        "invalid_count": metrics.get("invalid_count"),
        "pending_count": metrics.get("pending_count"),
        "mean_predicted": metrics.get("mean_predicted"),
        "mean_realized": metrics.get("mean_realized"),
        "mae": metrics.get("mae"),
        "rmse": metrics.get("rmse"),
        "directional_accuracy": metrics.get("directional_accuracy"),
        "spearman_rank_ic": metrics.get("spearman_rank_ic"),
        "top20_realized_mean": metrics.get("top20_realized_mean"),
        "bottom20_realized_mean": metrics.get("bottom20_realized_mean"),
        "top_minus_bottom_spread": metrics.get("top_minus_bottom_spread"),
        "metrics": metrics.get("metrics") or {},
        "evaluated_at": metrics.get("evaluated_at"),
    }


def _batch_sort_key(batch: ForwardPredictionBatch) -> tuple[Any, int]:
    generated = getattr(batch, "generated_at", None) or getattr(batch, "completed_at", None)
    return (generated is not None, generated, int(batch.id))


def _evaluation_sort_key(row: ForwardBatchEvaluation) -> tuple[Any, int]:
    evaluated_at = getattr(row, "evaluated_at", None)
    return (evaluated_at is not None, evaluated_at, int(row.id))


def _metrics_from_stored_or_live(
    evaluation: ForwardBatchEvaluation | None,
    outcomes: list[ForwardPredictionOutcome],
) -> dict[str, Any]:
    if evaluation is not None:
        payload = serialize_batch_evaluation(evaluation) or {}
        if outcomes and not payload.get("pending_count") and any(
            getattr(o, "status", None) == "PENDING_OUTCOME" for o in outcomes
        ):
            live = _batch_metrics(outcomes)
            payload["pending_count"] = live.get("pending_count")
            payload["status"] = live.get("status") or payload.get("status")
        return payload
    if outcomes:
        return _batch_metrics(outcomes)
    return {
        "status": "PENDING",
        "eligible_count": 0,
        "evaluated_count": 0,
        "invalid_count": 0,
        "pending_count": 0,
        "metrics": {},
    }


def summarize_forward_predictions(
    batches: list[ForwardPredictionBatch],
    evaluations: list[ForwardBatchEvaluation],
    predictions: list[ForwardPrediction],
    outcomes: list[ForwardPredictionOutcome],
) -> dict[str, Any]:
    eval_by_batch = {int(row.batch_id): row for row in evaluations}
    outcomes_by_batch: dict[int, list[ForwardPredictionOutcome]] = defaultdict(list)
    for row in outcomes:
        outcomes_by_batch[int(row.batch_id)].append(row)
    preds_by_batch: dict[int, list[ForwardPrediction]] = defaultdict(list)
    for row in predictions:
        preds_by_batch[int(row.batch_id)].append(row)

    latest_batch = max(batches, key=_batch_sort_key) if batches else None
    evaluated_rows = [
        row
        for row in evaluations
        if str(row.status) in {"EVALUATED", "PARTIALLY_MATURED"} and int(row.evaluated_count or 0) > 0
    ]
    latest_evaluated = max(evaluated_rows, key=_evaluation_sort_key) if evaluated_rows else None

    def _section_for(batch: ForwardPredictionBatch | None) -> dict[str, Any] | None:
        if batch is None:
            return None
        bid = int(batch.id)
        semantic = str(getattr(batch, "prediction_semantic", None) or SEMANTIC_EXPECTED_RETURN)
        batch_outcomes = outcomes_by_batch.get(bid, [])
        batch_preds = preds_by_batch.get(bid, [])
        stored = eval_by_batch.get(bid)
        metrics = _metrics_from_stored_or_live(stored, batch_outcomes)
        pending_without_row = [
            p
            for p in batch_preds
            if str(getattr(p, "outcome_status", "PENDING_OUTCOME")) == "PENDING_OUTCOME"
            and not any(int(o.forward_prediction_id) == int(p.id) for o in batch_outcomes)
        ]
        pending_count = int(metrics.get("pending_count") or 0) + len(pending_without_row)
        if pending_count and metrics.get("status") in {None, "EVALUATED"} and not metrics.get("evaluated_count"):
            metrics["status"] = "PENDING"
        metrics["pending_count"] = pending_count
        if not batch_outcomes and batch_preds:
            metrics["status"] = "PENDING"
            metrics["eligible_count"] = len(batch_preds)
            metrics["pending_count"] = len(batch_preds)
            metrics["evaluated_count"] = 0
        if semantic == SEMANTIC_RANKING_SCORE:
            body = _strip_ranker_error_metrics(metrics)
        else:
            body = _expected_return_metrics(metrics)
        body["batch_id"] = bid
        body["as_of_date"] = batch.as_of_date.isoformat() if getattr(batch, "as_of_date", None) else None
        body["candidate_name"] = getattr(batch, "candidate_name", None)
        body["candidate_version"] = getattr(batch, "candidate_version", None)
        return body

    by_semantic: dict[str, ForwardPredictionBatch | None] = {
        SEMANTIC_EXPECTED_RETURN: None,
        SEMANTIC_RANKING_SCORE: None,
    }
    for batch in sorted(batches, key=_batch_sort_key, reverse=True):
        semantic = str(getattr(batch, "prediction_semantic", None) or SEMANTIC_EXPECTED_RETURN)
        if semantic in by_semantic and by_semantic[semantic] is None:
            by_semantic[semantic] = batch

    matured_total = sum(1 for o in outcomes if str(o.status) == "EVALUATED")
    pending_total = sum(1 for o in outcomes if str(o.status) == "PENDING_OUTCOME")
    pending_preds = sum(
        1 for p in predictions if str(getattr(p, "outcome_status", "PENDING_OUTCOME")) == "PENDING_OUTCOME"
    )
    if pending_preds > pending_total:
        pending_total = pending_preds

    latest_eval_batch = None
    if latest_evaluated is not None:
        latest_eval_batch = next((b for b in batches if int(b.id) == int(latest_evaluated.batch_id)), None)

    expected_payload = _section_for(by_semantic[SEMANTIC_EXPECTED_RETURN])
    ranking_payload = _section_for(by_semantic[SEMANTIC_RANKING_SCORE])
    if ranking_payload is not None:
        for forbidden in _RANKER_FORBIDDEN_METRICS:
            ranking_payload.pop(forbidden, None)
            nested = ranking_payload.get("metrics")
            if isinstance(nested, dict):
                nested.pop(forbidden, None)
                nested.pop(forbidden.lower(), None)
                nested.pop(forbidden.upper(), None)

    return {
        "latest_batch": {
            "batch_id": int(latest_batch.id) if latest_batch is not None else None,
            "as_of_date": latest_batch.as_of_date.isoformat() if latest_batch is not None else None,
            "prediction_semantic": (
                str(getattr(latest_batch, "prediction_semantic", None) or SEMANTIC_EXPECTED_RETURN)
                if latest_batch is not None
                else None
            ),
        },
        "latest_evaluated_batch": {
            "batch_id": int(latest_evaluated.batch_id) if latest_evaluated is not None else None,
            "status": str(latest_evaluated.status) if latest_evaluated is not None else None,
            "evaluated_at": (
                latest_evaluated.evaluated_at.isoformat()
                if latest_evaluated is not None and latest_evaluated.evaluated_at is not None
                else None
            ),
            "prediction_semantic": (
                str(getattr(latest_eval_batch, "prediction_semantic", None) or SEMANTIC_EXPECTED_RETURN)
                if latest_eval_batch is not None
                else None
            ),
            "evaluated_count": int(latest_evaluated.evaluated_count) if latest_evaluated is not None else 0,
            "pending_count": int(latest_evaluated.pending_count) if latest_evaluated is not None else 0,
        },
        "freshness": {
            "matured_count": matured_total,
            "pending_count": pending_total,
            "pending_remains_pending": True,
            "fabricated_immature_outcomes": False,
        },
        "expected_return": expected_payload,
        "ranking_score": ranking_payload,
    }


def _load_forward(core_session: Session) -> tuple[
    list[ForwardPredictionBatch],
    list[ForwardBatchEvaluation],
    list[ForwardPrediction],
    list[ForwardPredictionOutcome],
]:
    batches = _select_all(core_session, select(ForwardPredictionBatch))
    evaluations = _select_all(core_session, select(ForwardBatchEvaluation))
    predictions = _select_all(core_session, select(ForwardPrediction))
    outcomes = _select_all(core_session, select(ForwardPredictionOutcome))
    return batches, evaluations, predictions, outcomes


def build_prospective_evidence_v1(
    *,
    memory_session: Session | None = None,
    core_session: Session | None = None,
    portfolio_id: int | None = None,
) -> dict[str, Any]:
    """Unified ProspectiveEvidenceV1 payload. SELECT-only over Memory and Core sessions."""
    if memory_session is not None:
        records, actions, outcomes, links = _load_pdm(memory_session, portfolio_id=portfolio_id)
        pdm = summarize_personal_decision_memory(records, actions, outcomes, links)
    else:
        pdm = summarize_personal_decision_memory([], [], [], [])

    if core_session is not None:
        batches, evaluations, predictions, fwd_outcomes = _load_forward(core_session)
        forward = summarize_forward_predictions(batches, evaluations, predictions, fwd_outcomes)
    else:
        forward = summarize_forward_predictions([], [], [], [])

    return {
        "schema": PROSPECTIVE_EVIDENCE_VERSION,
        "personal_decision_memory": pdm,
        "forward_predictions": forward,
        "limitations": list(LIMITATIONS),
    }
