"""RANK_HYSTERESIS_LONG_ONLY_V1 — entry top-q / exit wider band."""

from __future__ import annotations

from typing import Any

from app.domain.ports.portfolio import (
    PortfolioDecision,
    PortfolioPolicy,
    PortfolioPolicyInput,
    PortfolioPolicyOutput,
    PredictionSignal,
)
from app.modules.simulator.application.policy import select_top_k
from app.modules.simulator.config import (
    POLICY_HYSTERESIS_V1,
    V1_ENTRY_QUANTILE,
    V1_EXIT_QUANTILE,
)


class RankHysteresisLongOnlyV1Policy(PortfolioPolicy):
    """Long-only equal-weight with ranking hysteresis.

    ENTER: rank within top entry_quantile (ceil(N * entry)).
    HOLD: previously held name may remain while rank within exit_quantile band.
    Priority: retained holdings inside exit band, then fill desired entry capacity
    with highest-ranked new names in the entry band.
    Max holdings: ceil(N * exit_quantile).
    Tie-break: predicted_return_20d descending, then instrument_id ascending.
    """

    def decide(self, policy_input: PortfolioPolicyInput) -> PortfolioPolicyOutput:
        constraints: dict[str, Any] = dict(policy_input.constraints or {})
        entry_q = float(constraints.get("entry_quantile", V1_ENTRY_QUANTILE))
        exit_q = float(constraints.get("exit_quantile", V1_EXIT_QUANTILE))
        held_raw = constraints.get("held_instrument_ids") or ()
        held_ids = {int(x) for x in held_raw}

        signals = list(policy_input.prediction_signals)
        if not signals:
            return PortfolioPolicyOutput(
                decisions=(),
                metadata={
                    "policy": POLICY_HYSTERESIS_V1,
                    "reason": "no_eligible_predictions",
                    "eligible_n": 0,
                    "selected_k": 0,
                },
            )

        ranked = sorted(
            signals,
            key=lambda s: (-float(s.predicted_return_20d), int(s.instrument_id)),
        )
        n = len(ranked)
        k_entry = select_top_k(n, entry_q)
        k_max = select_top_k(n, exit_q)
        # rank position 1..N
        rank_by_id = {int(s.instrument_id): i for i, s in enumerate(ranked, start=1)}
        signal_by_id = {int(s.instrument_id): s for s in ranked}

        # Retain held names still inside exit band (rank <= k_max)
        retained: list[PredictionSignal] = []
        for iid in sorted(held_ids):
            sig = signal_by_id.get(iid)
            if sig is None:
                continue
            if rank_by_id[iid] <= k_max:
                retained.append(sig)

        selected: list[tuple[PredictionSignal, str]] = [
            (sig, "HOLD_WITHIN_EXIT_BAND") for sig in retained
        ]
        selected_ids = {int(s.instrument_id) for s, _ in selected}

        # Fill remaining desired capacity from entry band (rank <= k_entry)
        need = max(0, k_entry - len(selected))
        if need > 0:
            for sig in ranked:
                if need <= 0:
                    break
                iid = int(sig.instrument_id)
                if iid in selected_ids:
                    continue
                if rank_by_id[iid] > k_entry:
                    break  # ranked ascending quality; rest are worse
                selected.append((sig, "ENTER_TOP20"))
                selected_ids.add(iid)
                need -= 1

        # Cap at k_max (should already hold); if somehow over, drop worst new first
        if len(selected) > k_max:
            selected = selected[:k_max]

        k = len(selected)
        if k == 0:
            return PortfolioPolicyOutput(
                decisions=(),
                metadata={
                    "policy": POLICY_HYSTERESIS_V1,
                    "reason": "empty_selection",
                    "eligible_n": n,
                    "selected_k": 0,
                    "k_entry": k_entry,
                    "k_max": k_max,
                },
            )

        weight = 1.0 / k
        decisions: list[PortfolioDecision] = []
        for sig, action in selected:
            iid = int(sig.instrument_id)
            rank_idx = rank_by_id[iid]
            decisions.append(
                PortfolioDecision(
                    ticker=sig.ticker,
                    target_weight=weight,
                    rationale=(
                        f"{POLICY_HYSTERESIS_V1}: {action} rank {rank_idx}/{n} "
                        f"entry_k={k_entry} exit_k={k_max}"
                    ),
                    metadata={
                        "instrument_id": iid,
                        "predicted_return_20d": sig.predicted_return_20d,
                        "prediction_date": sig.as_of_date.isoformat(),
                        "rank": rank_idx,
                        "fold_id": sig.fold_id,
                        "sample_id": sig.sample_id,
                        "policy": POLICY_HYSTERESIS_V1,
                        "action": action,
                    },
                )
            )

        return PortfolioPolicyOutput(
            decisions=tuple(decisions),
            metadata={
                "policy": POLICY_HYSTERESIS_V1,
                "eligible_n": n,
                "selected_k": k,
                "k_entry": k_entry,
                "k_max": k_max,
                "entry_quantile": entry_q,
                "exit_quantile": exit_q,
                "equal_weight": weight,
                "retained": len(retained),
            },
        )
