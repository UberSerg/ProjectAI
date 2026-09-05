"""RANK_LONG_ONLY_V0 — deterministic cross-sectional ranking policy."""

from __future__ import annotations

import math
from typing import Any

from app.domain.ports.portfolio import (
    PortfolioDecision,
    PortfolioPolicy,
    PortfolioPolicyInput,
    PortfolioPolicyOutput,
)
from app.modules.simulator.config import CANONICAL_TOP_QUANTILE, POLICY_NAME


def select_top_k(n: int, top_quantile: float = CANONICAL_TOP_QUANTILE) -> int:
    """K = max(1, ceil(N * top_quantile))."""
    if n <= 0:
        return 0
    return max(1, int(math.ceil(n * top_quantile)))


class RankLongOnlyV0Policy(PortfolioPolicy):
    """Long-only equal-weight top quantile; remaining capital stays cash.

    Tie-break: score descending, then instrument_id ascending.
    """

    def decide(self, policy_input: PortfolioPolicyInput) -> PortfolioPolicyOutput:
        constraints: dict[str, Any] = dict(policy_input.constraints or {})
        top_quantile = float(constraints.get("top_quantile", CANONICAL_TOP_QUANTILE))
        signals = list(policy_input.prediction_signals)
        if not signals:
            return PortfolioPolicyOutput(
                decisions=(),
                metadata={
                    "policy": POLICY_NAME,
                    "reason": "no_eligible_predictions",
                    "eligible_n": 0,
                    "selected_k": 0,
                },
            )

        ranked = sorted(
            signals,
            key=lambda s: (-float(s.score), int(s.instrument_id)),
        )
        k = select_top_k(len(ranked), top_quantile)
        selected = ranked[:k]
        weight = 1.0 / k
        decisions: list[PortfolioDecision] = []
        for rank_idx, signal in enumerate(selected, start=1):
            meta: dict[str, Any] = {
                "instrument_id": signal.instrument_id,
                "prediction_date": signal.as_of_date.isoformat(),
                "rank": rank_idx,
                "eligible_count": len(ranked),
                "fold_id": signal.fold_id,
                "sample_id": signal.sample_id,
                "policy": POLICY_NAME,
                "prediction_semantic": signal.prediction_semantic,
                "prediction_score": signal.score,
            }
            if signal.prediction_semantic == "EXPECTED_RETURN":
                meta["predicted_return_20d"] = signal.predicted_return_20d
            decisions.append(
                PortfolioDecision(
                    ticker=signal.ticker,
                    target_weight=weight,
                    rationale=(
                        f"{POLICY_NAME}: rank {rank_idx}/{k} of {len(ranked)} "
                        f"by score on {signal.as_of_date.isoformat()}"
                    ),
                    metadata=meta,
                )
            )
        return PortfolioPolicyOutput(
            decisions=tuple(decisions),
            metadata={
                "policy": POLICY_NAME,
                "eligible_n": len(ranked),
                "selected_k": k,
                "top_quantile": top_quantile,
                "equal_weight": weight,
                "cash_weight": 0.0,  # before risk clamp; unallocated only if risk shrinks
            },
        )
