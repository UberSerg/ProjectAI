"""Predeclared economic robustness campaign for RANKING / V4_FULL research.

Reuses ``research_evidence.economics``. Primary settings are frozen before any
cell is scored. The robustness matrix is enumerated in full before metrics.
The best matrix cell is never promoted to primary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.modules.research_evidence import economics as economics_mod
from app.modules.research_evidence.economics import (
    INITIAL_CAPITAL,
    MIN_ELIGIBLE_NAMES,
    MODEL_VARIANTS,
    POSITION_SIZING,
    RETURN_SEMANTIC,
    SKIPPED_BY_BOUNDARY,
    UNIVERSE_POLICY,
    EconomicsContractError,
    rebalance_decision_dates,
    run_research_economics,
    select_equal_weight_targets,
    validate_oos_prediction_frame,
)
from app.modules.research_evidence.oos import SEMANTIC_RANKING
from app.modules.simulator.application.market_view import MarketView

CAMPAIGN_ID = "economic_robustness_research_v1"
PREDICTION_SEMANTIC = SEMANTIC_RANKING
PRIMARY_MODEL_VARIANT = "V4_FULL"
PRIMARY_COST_BPS = 30
PRIMARY_REBALANCE_EVERY_N = 20
PRIMARY_TOP_QUANTILE = 0.20
COST_BPS_GRID: tuple[int, ...] = (0, 10, 30, 50)
REBALANCE_GRID: tuple[int, ...] = (10, 20, 40)
TOP_QUANTILE_GRID: tuple[float, ...] = (0.10, 0.20, 0.30)
BENCHMARK_MODE = "eligible_universe_equal_weight"

Observer = Callable[[str, Any], None]


@dataclass(frozen=True, slots=True)
class RobustnessCell:
    """One predeclared (cost, cadence, selection) combination."""

    cost_bps: int
    rebalance_every_n_sessions: int
    top_quantile: float

    @property
    def selection_label(self) -> str:
        return f"top_{int(round(self.top_quantile * 100))}"

    @property
    def cell_id(self) -> str:
        return (
            f"cost{self.cost_bps}_reb{self.rebalance_every_n_sessions}_"
            f"{self.selection_label}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "cost_bps": self.cost_bps,
            "rebalance_every_n_sessions": self.rebalance_every_n_sessions,
            "top_quantile": self.top_quantile,
            "selection_label": self.selection_label,
        }


PRIMARY_CELL = RobustnessCell(
    cost_bps=PRIMARY_COST_BPS,
    rebalance_every_n_sessions=PRIMARY_REBALANCE_EVERY_N,
    top_quantile=PRIMARY_TOP_QUANTILE,
)


def primary_settings() -> dict[str, Any]:
    """Frozen primary economic contract. Not selected from the matrix after the fact."""
    return {
        "campaign_id": CAMPAIGN_ID,
        "prediction_semantic": PREDICTION_SEMANTIC,
        "model_variant": PRIMARY_MODEL_VARIANT,
        "long_only": True,
        "top_quantile": PRIMARY_TOP_QUANTILE,
        "selection": "long_only_top_20pct_equal_weight",
        "position_sizing": POSITION_SIZING,
        "rebalance_every_n_sessions": PRIMARY_REBALANCE_EVERY_N,
        "execution_timing": "next_open",
        "decision": "EOD at session T",
        "fill": "next eligible trading session official OPEN",
        "cash_first_class": True,
        "leverage": False,
        "shorts": False,
        "dividends": "excluded",
        "return_semantic": RETURN_SEMANTIC,
        "assumed_all_in_cost_bps_per_side": PRIMARY_COST_BPS,
        "cost_note": "ASSUMED research scenario, not actual Sber/broker fees",
        "universe_policy": UNIVERSE_POLICY,
        "min_eligible_names": MIN_ELIGIBLE_NAMES,
        "benchmark": BENCHMARK_MODE,
        "benchmark_same_rebalance_dates": True,
        "benchmark_same_next_open": True,
        "benchmark_same_assumed_cost": True,
        "terminal_next_open_policy": "OPTION_B_SKIPPED_BY_BOUNDARY",
        "primary_is_predeclared": True,
        "primary_is_best_matrix_cell": False,
    }


def enumerate_robustness_cells() -> tuple[RobustnessCell, ...]:
    """Declare every matrix cell before any NAV / return metric is computed."""
    cells: list[RobustnessCell] = []
    for cost_bps in COST_BPS_GRID:
        for rebalance_n in REBALANCE_GRID:
            for top_q in TOP_QUANTILE_GRID:
                cells.append(
                    RobustnessCell(
                        cost_bps=cost_bps,
                        rebalance_every_n_sessions=rebalance_n,
                        top_quantile=top_q,
                    )
                )
    expected = len(COST_BPS_GRID) * len(REBALANCE_GRID) * len(TOP_QUANTILE_GRID)
    if len(cells) != expected:
        raise EconomicsContractError("robustness matrix size drifted from predeclared grids")
    if PRIMARY_CELL not in cells:
        raise EconomicsContractError("primary cell is missing from the predeclared matrix")
    return tuple(cells)


def _reject_unlabeled_sharpe(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = str(key)
            if "sharpe" in name.lower():
                allowed = name == "SHARPE_RF0_RESEARCH" or name.startswith(
                    "SHARPE_RF0_RESEARCH"
                )
                if not allowed:
                    raise EconomicsContractError(
                        f"unlabeled Sharpe is forbidden ({name}); "
                        "only SHARPE_RF0_RESEARCH may be emitted"
                    )
            _reject_unlabeled_sharpe(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_unlabeled_sharpe(item)


@contextmanager
def _cell_economics(*, rebalance_every_n: int, top_quantile: float) -> Iterator[None]:
    """Apply cadence/quantile without retuning economics.py defaults after seeing results."""

    def rebal(trading_days, *, every_n: int = rebalance_every_n):
        return rebalance_decision_dates(trading_days, every_n=every_n)

    def select(
        day_frame,
        *,
        mode,
        top_quantile: float = top_quantile,
        min_eligible_names: int = MIN_ELIGIBLE_NAMES,
    ):
        return select_equal_weight_targets(
            day_frame,
            mode=mode,
            top_quantile=top_quantile,
            min_eligible_names=min_eligible_names,
        )

    def assumptions(*, all_in_bps: int) -> dict[str, Any]:
        blob = orig_assumptions(all_in_bps=all_in_bps)
        blob["rebalance_every_n_sessions"] = rebalance_every_n
        blob["top_quantile"] = top_quantile
        blob["prediction_semantic"] = PREDICTION_SEMANTIC
        blob["cost_note"] = "research assumption, not actual Sber fee"
        return blob

    orig_rebal = economics_mod.rebalance_decision_dates
    orig_select = economics_mod.select_equal_weight_targets
    orig_assumptions = economics_mod._assumptions_blob
    economics_mod.rebalance_decision_dates = rebal
    economics_mod.select_equal_weight_targets = select
    economics_mod._assumptions_blob = assumptions
    try:
        yield
    finally:
        economics_mod.rebalance_decision_dates = orig_rebal
        economics_mod.select_equal_weight_targets = orig_select
        economics_mod._assumptions_blob = orig_assumptions


def _stamp_run(run: dict[str, Any], *, cell: RobustnessCell, model_variant: str) -> dict[str, Any]:
    stamped = dict(run)
    assumptions = dict(stamped.get("assumptions") or {})
    assumptions["rebalance_every_n_sessions"] = cell.rebalance_every_n_sessions
    assumptions["top_quantile"] = cell.top_quantile
    assumptions["assumed_all_in_cost_bps_per_side"] = cell.cost_bps
    assumptions["prediction_semantic"] = PREDICTION_SEMANTIC
    assumptions["cost_note"] = "research assumption, not actual Sber fee"
    stamped["assumptions"] = assumptions
    stamped["model_variant"] = model_variant
    stamped["cell"] = cell.as_dict()
    _reject_unlabeled_sharpe(stamped.get("metrics"))
    return stamped


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    """Drop the live ledger object; keep fill-level honesty flags."""
    fills = []
    ledger = run.get("ledger")
    if ledger is not None:
        fills = [
            {
                "decision_date": f.decision_date.isoformat(),
                "execution_date": f.execution_date.isoformat(),
                "instrument_id": f.instrument_id,
                "side": f.side,
                "raw_open": f.raw_open,
                "fill_price": f.fill_price,
            }
            for f in ledger.fills
        ]
        for fill in ledger.fills:
            if fill.execution_date <= fill.decision_date:
                raise EconomicsContractError(
                    "same-session fill is forbidden "
                    f"(decision={fill.decision_date}, execution={fill.execution_date})"
                )
        for order in ledger.orders:
            if order.execution_date <= order.decision_date:
                raise EconomicsContractError(
                    "same-session order is forbidden "
                    f"(decision={order.decision_date}, execution={order.execution_date})"
                )
    return {
        "status": run["status"],
        "wording": run["wording"],
        "model_variant": run["model_variant"],
        "selection_mode": run["selection_mode"],
        "assumptions": run["assumptions"],
        "limitations": run["limitations"],
        "metrics": run["metrics"],
        "imoex": run["imoex"],
        "unavailable_execution_events": run["unavailable_execution_events"],
        "unresolved_exit_events": run["unresolved_exit_events"],
        "n_fills": run["n_fills"],
        "final_cash": run["final_cash"],
        "final_nav": run["final_nav"],
        "rebalance_dates": run["rebalance_dates"],
        "skipped_rebalance_dates": run["skipped_rebalance_dates"],
        "terminal_rebalance_without_execution_session": run[
            "terminal_rebalance_without_execution_session"
        ],
        "terminal_next_open_policy": run["terminal_next_open_policy"],
        "fills": fills,
        "cell": run.get("cell"),
    }


def run_predeclared_cell(
    *,
    predictions: pd.DataFrame,
    market: MarketView,
    cell: RobustnessCell,
    model_variant: str,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    include_sharpe_rf0_research: bool = False,
) -> dict[str, Any]:
    """One matrix cell: strategy + same-date/open/cost eligible-universe EW benchmark."""
    common = dict(
        predictions=predictions,
        market=market,
        model_variant=model_variant,
        all_in_cost_bps_per_side=cell.cost_bps,
        expected_dataset_values_hash=expected_dataset_values_hash,
        expected_experiment_fingerprint=expected_experiment_fingerprint,
        initial_capital=initial_capital,
        include_sharpe_rf0_research=include_sharpe_rf0_research,
    )
    with _cell_economics(
        rebalance_every_n=cell.rebalance_every_n_sessions,
        top_quantile=cell.top_quantile,
    ):
        strategy = run_research_economics(**common, selection_mode="strategy_top_quantile")
        benchmark = run_research_economics(**common, selection_mode=BENCHMARK_MODE)
    strategy = _stamp_run(strategy, cell=cell, model_variant=model_variant)
    benchmark = _stamp_run(benchmark, cell=cell, model_variant=model_variant)
    if strategy["rebalance_dates"] != benchmark["rebalance_dates"]:
        raise EconomicsContractError("benchmark rebalance dates drifted from strategy")
    if (
        strategy["terminal_rebalance_without_execution_session"]
        != benchmark["terminal_rebalance_without_execution_session"]
    ):
        raise EconomicsContractError("benchmark terminal skip policy drifted from strategy")
    return {
        "cell": cell.as_dict(),
        "is_primary_cell": cell == PRIMARY_CELL and model_variant == PRIMARY_MODEL_VARIANT,
        "strategy": _public_run(strategy),
        "benchmark": {
            "type": BENCHMARK_MODE,
            "same_rebalance_dates": True,
            "same_next_open": True,
            "same_assumed_cost": True,
            **_public_run(benchmark),
        },
    }


def _lookup_primary(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Identity lookup on predeclared settings — never argmax of returns."""
    matches = [
        row
        for row in matrix
        if row["cell"]["cost_bps"] == PRIMARY_COST_BPS
        and row["cell"]["rebalance_every_n_sessions"] == PRIMARY_REBALANCE_EVERY_N
        and row["cell"]["top_quantile"] == PRIMARY_TOP_QUANTILE
    ]
    if len(matches) != 1:
        raise EconomicsContractError("primary cell must appear exactly once in the matrix")
    return matches[0]


def run_economic_robustness_campaign(
    *,
    predictions: pd.DataFrame,
    market: MarketView,
    expected_dataset_values_hash: str | None = None,
    expected_experiment_fingerprint: str | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    include_sharpe_rf0_research: bool = False,
    observer: Observer | None = None,
) -> dict[str, Any]:
    """RANKING V4_FULL primary + full predeclared robustness matrix + primary-only variants."""
    validate_oos_prediction_frame(
        predictions,
        model_variant=PRIMARY_MODEL_VARIANT,
        expected_dataset_values_hash=expected_dataset_values_hash,
        expected_experiment_fingerprint=expected_experiment_fingerprint,
        trading_days=list(market.trading_days),
    )
    cells = enumerate_robustness_cells()
    if observer is not None:
        observer("cells_enumerated", cells)

    matrix: list[dict[str, Any]] = []
    for cell in cells:
        if observer is not None:
            observer("cell_metrics_started", cell)
        matrix.append(
            run_predeclared_cell(
                predictions=predictions,
                market=market,
                cell=cell,
                model_variant=PRIMARY_MODEL_VARIANT,
                expected_dataset_values_hash=expected_dataset_values_hash,
                expected_experiment_fingerprint=expected_experiment_fingerprint,
                initial_capital=initial_capital,
                include_sharpe_rf0_research=include_sharpe_rf0_research,
            )
        )

    primary_row = _lookup_primary(matrix)
    if observer is not None:
        observer("primary_variants_started", MODEL_VARIANTS)

    variants_under_primary: dict[str, Any] = {}
    for variant in MODEL_VARIANTS:
        variants_under_primary[variant] = run_predeclared_cell(
            predictions=predictions,
            market=market,
            cell=PRIMARY_CELL,
            model_variant=variant,
            expected_dataset_values_hash=expected_dataset_values_hash,
            expected_experiment_fingerprint=expected_experiment_fingerprint,
            initial_capital=initial_capital,
            include_sharpe_rf0_research=include_sharpe_rf0_research,
        )

    returns = [
        row["strategy"]["metrics"].get("cumulative_price_return")
        for row in matrix
    ]
    best_idx = None
    finite = [(i, r) for i, r in enumerate(returns) if r is not None]
    if finite:
        best_idx = max(finite, key=lambda item: item[1])[0]
    primary_idx = next(
        i for i, row in enumerate(matrix) if row["cell"]["cell_id"] == PRIMARY_CELL.cell_id
    )

    payload = {
        "campaign_id": CAMPAIGN_ID,
        "wording": (
            "Historical OOS RANKING research simulation under predeclared primary "
            "assumptions; robustness cells were enumerated before metrics and the "
            "best cell is not primary."
        ),
        "prediction_semantic": PREDICTION_SEMANTIC,
        "primary_settings": primary_settings(),
        "predeclared_cells": [c.as_dict() for c in cells],
        "cells_enumerated_before_metrics": True,
        "matrix": matrix,
        "primary": primary_row,
        "variants_under_primary_settings": variants_under_primary,
        "primary_index_in_predeclared_matrix": primary_idx,
        "best_matrix_index_by_cumulative_price_return": best_idx,
        "primary_chosen_as_best_cell": False,
        "skipped_by_boundary": SKIPPED_BY_BOUNDARY,
    }
    _reject_unlabeled_sharpe(payload)
    return payload
