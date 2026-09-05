"""Realized-outcome scoring for paired A/B batches.

Realized 20-observation returns are a property of the market, not of a model, so the
V0 outcome evaluator produces them once and both sides are scored against the same values.
Candidate V1 emits a RANKING_SCORE, so it is only ever measured with rank statistics —
no MAE, no RMSE, no directional accuracy on the score itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.model_edge.application.experiment import require_experiment
from app.modules.model_edge.config import (
    DIAGNOSTICS_OVERLAP_TOP_N,
    SEMANTIC_EXPECTED_RETURN,
    SEMANTIC_RANKING_SCORE,
)
from app.modules.model_edge.infrastructure.models import ProspectiveModelComparisonBatch
from app.modules.prediction.application.forward_outcome import evaluate_forward_outcomes
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction
from app.modules.prediction.infrastructure.forward_outcome_models import (
    ForwardPredictionOutcome,
)


@dataclass
class PairedOutcomeResult:
    status: str
    evaluated_batches: int
    summary: dict[str, Any] = field(default_factory=dict)
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evaluated_batches": self.evaluated_batches,
            "details": self.details,
            **self.summary,
        }


def _realized_by_instrument(session: Session, as_of: date) -> dict[int, float]:
    """Mature realized 20-observation returns for one as_of, model-independent."""
    rows = session.scalars(
        select(ForwardPredictionOutcome).where(
            ForwardPredictionOutcome.as_of_date == as_of,
            ForwardPredictionOutcome.status == "EVALUATED",
        )
    ).all()
    return {
        int(r.instrument_id): float(r.realized_return_20d)
        for r in rows
        if r.realized_return_20d is not None
    }


def _scores(session: Session, batch_id: int | None) -> dict[int, float]:
    if batch_id is None:
        return {}
    rows = session.scalars(
        select(ForwardPrediction).where(ForwardPrediction.batch_id == batch_id)
    ).all()
    return {int(r.instrument_id): float(r.predicted_return_20d) for r in rows}


def _rank_metrics(
    scores: dict[int, float],
    realized: dict[int, float],
    *,
    semantic: str,
    top_n: int,
) -> dict[str, Any]:
    common = sorted(set(scores) & set(realized))
    out: dict[str, Any] = {
        "prediction_semantic": semantic,
        "scored_instruments": len(scores),
        "matured_instruments": len(common),
        "rank_ic": None,
        "top_realized_mean": None,
        "bottom_realized_mean": None,
        "top_minus_bottom": None,
        "selected_top": [],
    }
    if len(common) < 2:
        return out

    score_values = [scores[i] for i in common]
    realized_values = [realized[i] for i in common]
    rank_s = _average_ranks(score_values)
    rank_r = _average_ranks(realized_values)
    rs = rank_s - rank_s.mean()
    rr = rank_r - rank_r.mean()
    denom = float(np.sqrt((rs * rs).sum() * (rr * rr).sum()))
    out["rank_ic"] = float((rs * rr).sum() / denom) if denom > 0 else None

    ordered = sorted(common, key=lambda i: (-scores[i], i))
    k = max(1, min(top_n, len(ordered) // 2))
    top = ordered[:k]
    bottom = ordered[-k:]
    out["top_realized_mean"] = float(np.mean([realized[i] for i in top]))
    out["bottom_realized_mean"] = float(np.mean([realized[i] for i in bottom]))
    out["top_minus_bottom"] = out["top_realized_mean"] - out["bottom_realized_mean"]
    out["selected_top"] = top
    out["top_n"] = k
    return out


def _average_ranks(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="stable")
    ranks = np.empty(len(arr), dtype=float)
    i = 0
    while i < len(arr):
        j = i
        while j + 1 < len(arr) and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        avg = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def evaluate_paired_outcomes(
    session: Session,
    *,
    as_of: date | None = None,
    top_n: int = DIAGNOSTICS_OVERLAP_TOP_N,
) -> PairedOutcomeResult:
    """Attach realized rank statistics to matured paired comparison batches."""
    experiment = require_experiment(session)

    # Realized returns come from the EXPECTED_RETURN evaluator only.
    evaluate_forward_outcomes(session, prediction_semantic=SEMANTIC_EXPECTED_RETURN)

    q = select(ProspectiveModelComparisonBatch).where(
        ProspectiveModelComparisonBatch.experiment_id == experiment.id
    )
    if as_of is not None:
        q = q.where(ProspectiveModelComparisonBatch.as_of_date == as_of)
    batches = list(session.scalars(q.order_by(ProspectiveModelComparisonBatch.as_of_date)))

    details: list[dict[str, Any]] = []
    evaluated = 0
    for batch in batches:
        realized = _realized_by_instrument(session, batch.as_of_date)
        scores_a = _scores(session, batch.candidate_a_batch_id)
        scores_b = _scores(session, batch.candidate_b_batch_id)
        metrics_a = _rank_metrics(
            scores_a, realized, semantic=SEMANTIC_EXPECTED_RETURN, top_n=top_n
        )
        metrics_b = _rank_metrics(
            scores_b, realized, semantic=SEMANTIC_RANKING_SCORE, top_n=top_n
        )
        matured = bool(realized) and (
            metrics_a["matured_instruments"] > 0 or metrics_b["matured_instruments"] > 0
        )

        only_a = sorted(set(metrics_a["selected_top"]) - set(metrics_b["selected_top"]))
        only_b = sorted(set(metrics_b["selected_top"]) - set(metrics_a["selected_top"]))
        attribution = {
            "v0_only_selected": only_a,
            "v1_only_selected": only_b,
            "v0_only_realized_mean": (
                float(np.mean([realized[i] for i in only_a])) if only_a else None
            ),
            "v1_only_realized_mean": (
                float(np.mean([realized[i] for i in only_b])) if only_b else None
            ),
        }

        summary = dict(batch.summary or {})
        summary["outcome"] = {
            "matured": matured,
            "realized_instruments": len(realized),
            "candidate_a": {k: v for k, v in metrics_a.items() if k != "selected_top"},
            "candidate_b": {k: v for k, v in metrics_b.items() if k != "selected_top"},
            "decision_attribution": attribution,
            "note": (
                "Candidate V1 is scored on ranks only; its RANKING_SCORE has no "
                "return units and no error metric."
            ),
        }
        batch.summary = summary
        if matured:
            evaluated += 1
        details.append(
            {
                "as_of_date": batch.as_of_date.isoformat(),
                "comparison_batch_id": batch.id,
                "matured": matured,
                **summary["outcome"],
            }
        )
    session.flush()

    return PairedOutcomeResult(
        status="SUCCESS" if evaluated else "NO_CHANGES",
        evaluated_batches=evaluated,
        summary={"comparison_batches": len(batches)},
        details=details,
    )
