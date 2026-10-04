"""Economic robustness campaign: frozen primary, predeclared matrix, honesty flags."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.modules.research_evidence.campaign_economics import (
    COST_BPS_GRID,
    PRIMARY_CELL,
    PRIMARY_COST_BPS,
    PRIMARY_MODEL_VARIANT,
    PRIMARY_REBALANCE_EVERY_N,
    PRIMARY_TOP_QUANTILE,
    REBALANCE_GRID,
    TOP_QUANTILE_GRID,
    RobustnessCell,
    enumerate_robustness_cells,
    primary_settings,
    run_economic_robustness_campaign,
    run_predeclared_cell,
)
from app.modules.research_evidence.economics import SKIPPED_BY_BOUNDARY
from app.modules.research_evidence.oos import SEMANTIC_RANKING
from app.modules.simulator.application.market_view import DayBar, MarketView


def _weekdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _market(
    days: list[date],
    ids: list[int],
    *,
    opens: dict[tuple[int, date], float] | None = None,
    closes: dict[tuple[int, date], float] | None = None,
    open_px: float = 100.0,
    close_px: float = 101.0,
) -> MarketView:
    bars: dict[int, dict[date, DayBar]] = {}
    for iid in ids:
        bars[iid] = {}
        for i, d in enumerate(days):
            o = open_px + i * 0.5
            c = close_px + i * 0.5
            if opens and (iid, d) in opens:
                o = opens[(iid, d)]
            if closes and (iid, d) in closes:
                c = closes[(iid, d)]
            bars[iid][d] = DayBar(open=o, close=c)
    return MarketView(
        bars=bars,
        actions={},
        tickers={iid: f"T{iid}" for iid in ids},
        trading_days=days,
        imoex_id=None,
    )


def _pred_rows(
    days: list[date],
    ids: list[int],
    *,
    variants: tuple[str, ...] = ("V4_FULL",),
    score_fn=None,
) -> list[dict]:
    cutoff = days[0] - timedelta(days=1)
    rows: list[dict] = []
    for variant in variants:
        for d in days:
            for iid in ids:
                score = float(iid) if score_fn is None else float(score_fn(d, iid))
                rows.append(
                    {
                        "decision_date": d,
                        "instrument_id": iid,
                        "ticker": f"T{iid}",
                        "y_pred": score,
                        "model_variant": variant,
                        "fold_id": "fold_0",
                        "train_cutoff": cutoff,
                        "is_oos": True,
                        "universe_policy": "historical_equity_universe_v2",
                        "dataset_values_hash": "ds-v4-test",
                        "experiment_fingerprint": "exp-test",
                        "prediction_semantic": SEMANTIC_RANKING,
                    }
                )
    return rows


def test_primary_settings_frozen() -> None:
    settings = primary_settings()
    assert settings["prediction_semantic"] == SEMANTIC_RANKING
    assert settings["model_variant"] == "V4_FULL"
    assert settings["long_only"] is True
    assert settings["top_quantile"] == 0.20
    assert settings["rebalance_every_n_sessions"] == 20
    assert settings["execution_timing"] == "next_open"
    assert settings["fill"].startswith("next eligible")
    assert settings["cash_first_class"] is True
    assert settings["leverage"] is False
    assert settings["shorts"] is False
    assert settings["dividends"] == "excluded"
    assert settings["return_semantic"] == "PRICE_RETURN"
    assert settings["assumed_all_in_cost_bps_per_side"] == 30
    assert "Sber" in settings["cost_note"]
    assert settings["benchmark"] == "eligible_universe_equal_weight"
    assert settings["benchmark_same_rebalance_dates"] is True
    assert settings["benchmark_same_next_open"] is True
    assert settings["benchmark_same_assumed_cost"] is True
    assert settings["position_sizing"] == "FRACTIONAL_RESEARCH_WEIGHTS"
    assert settings["primary_is_best_matrix_cell"] is False
    assert PRIMARY_CELL.cost_bps == PRIMARY_COST_BPS == 30
    assert PRIMARY_CELL.rebalance_every_n_sessions == PRIMARY_REBALANCE_EVERY_N == 20
    assert PRIMARY_CELL.top_quantile == PRIMARY_TOP_QUANTILE == 0.20
    assert PRIMARY_MODEL_VARIANT == "V4_FULL"


def test_matrix_cells_enumerated_before_metrics() -> None:
    cells_before = enumerate_robustness_cells()
    assert len(cells_before) == (
        len(COST_BPS_GRID) * len(REBALANCE_GRID) * len(TOP_QUANTILE_GRID)
    )
    assert cells_before[0].cost_bps == 0
    assert cells_before[0].rebalance_every_n_sessions == 10
    assert cells_before[0].top_quantile == 0.10
    assert PRIMARY_CELL in cells_before
    assert [c.cost_bps for c in cells_before] == [
        cost for cost in COST_BPS_GRID for _r in REBALANCE_GRID for _q in TOP_QUANTILE_GRID
    ]

    days = _weekdays(date(2024, 1, 2), 8)
    ids = list(range(1, 11))
    market = _market(days, ids)
    frame = pd.DataFrame(
        _pred_rows(days, ids, variants=("BASE", "FUNDAMENTALS", "EVENTS", "V4_FULL"))
    )
    stages: list[str] = []

    def observer(stage: str, _payload) -> None:
        stages.append(stage)

    result = run_economic_robustness_campaign(
        predictions=frame,
        market=market,
        observer=observer,
        initial_capital=1_000_000.0,
    )
    assert stages[0] == "cells_enumerated"
    assert "cell_metrics_started" in stages
    assert stages.index("cells_enumerated") < stages.index("cell_metrics_started")
    assert result["cells_enumerated_before_metrics"] is True
    assert result["predeclared_cells"] == [c.as_dict() for c in cells_before]
    assert result["primary_chosen_as_best_cell"] is False
    assert len(result["matrix"]) == len(cells_before)
    primary = result["primary"]
    assert primary["cell"]["cost_bps"] == 30
    assert primary["cell"]["rebalance_every_n_sessions"] == 20
    assert primary["cell"]["top_quantile"] == 0.20
    assert set(result["variants_under_primary_settings"]) == {
        "BASE",
        "FUNDAMENTALS",
        "EVENTS",
        "V4_FULL",
    }
    for variant, blob in result["variants_under_primary_settings"].items():
        assert blob["cell"]["cost_bps"] == 30
        assert blob["cell"]["rebalance_every_n_sessions"] == 20
        assert blob["cell"]["top_quantile"] == 0.20
        assert blob["strategy"]["model_variant"] == variant
    best_idx = result["best_matrix_index_by_cumulative_price_return"]
    primary_idx = result["primary_index_in_predeclared_matrix"]
    if best_idx is not None and best_idx != primary_idx:
        assert result["primary"]["cell"]["cell_id"] == PRIMARY_CELL.cell_id


def test_primary_not_selected_as_best_cell() -> None:
    days = _weekdays(date(2024, 1, 2), 12)
    ids = list(range(1, 11))
    opens: dict[tuple[int, date], float] = {}
    closes: dict[tuple[int, date], float] = {}
    for iid in ids:
        for i, d in enumerate(days):
            px = 100.0 + (50.0 * i if iid == 10 else 0.0)
            opens[(iid, d)] = px
            closes[(iid, d)] = px
    market = _market(days, ids, opens=opens, closes=closes)
    frame = pd.DataFrame(
        _pred_rows(days, ids, variants=("BASE", "FUNDAMENTALS", "EVENTS", "V4_FULL"))
    )
    result = run_economic_robustness_campaign(predictions=frame, market=market)
    by_id = {row["cell"]["cell_id"]: row for row in result["matrix"]}
    concentrated = by_id["cost30_reb20_top_10"]["strategy"]["metrics"]["cumulative_price_return"]
    primary_ret = by_id["cost30_reb20_top_20"]["strategy"]["metrics"]["cumulative_price_return"]
    assert concentrated > primary_ret
    assert result["primary"]["cell"]["cell_id"] == "cost30_reb20_top_20"
    assert result["primary_chosen_as_best_cell"] is False
    assert result["best_matrix_index_by_cumulative_price_return"] != result[
        "primary_index_in_predeclared_matrix"
    ]


def test_skip_terminal_no_open() -> None:
    days = _weekdays(date(2024, 1, 2), 21)
    ids = list(range(1, 11))
    market = _market(days, ids)
    frame = pd.DataFrame(_pred_rows(days, ids))
    row = run_predeclared_cell(
        predictions=frame,
        market=market,
        cell=PRIMARY_CELL,
        model_variant="V4_FULL",
    )
    strategy = row["strategy"]
    assert strategy["terminal_next_open_policy"] == "OPTION_B_SKIPPED_BY_BOUNDARY"
    assert strategy["terminal_rebalance_without_execution_session"] == SKIPPED_BY_BOUNDARY
    assert strategy["skipped_rebalance_dates"] == [days[20].isoformat()]
    assert days[20].isoformat() not in strategy["rebalance_dates"]
    assert all(f["execution_date"] > f["decision_date"] for f in strategy["fills"])


def test_no_same_day_fill() -> None:
    days = _weekdays(date(2024, 1, 2), 8)
    ids = list(range(1, 11))
    opens = {(iid, d): 100.0 for iid in ids for d in days}
    closes = {(iid, d): 1.0 for iid in ids for d in days}
    opens[(10, days[1])] = 123.0
    market = _market(days, ids, opens=opens, closes=closes)
    frame = pd.DataFrame(_pred_rows(days, ids))
    row = run_predeclared_cell(
        predictions=frame,
        market=market,
        cell=PRIMARY_CELL,
        model_variant="V4_FULL",
    )
    fills = row["strategy"]["fills"]
    assert fills
    assert all(f["execution_date"] > f["decision_date"] for f in fills)
    first_exec = min(f["execution_date"] for f in fills)
    assert first_exec == days[1].isoformat()
    top = [f for f in fills if f["execution_date"] == days[1].isoformat() and f["instrument_id"] == 10]
    assert top
    assert top[0]["raw_open"] == pytest.approx(123.0)
    assert top[0]["fill_price"] == pytest.approx(123.0)
    assert all(abs(f["fill_price"] - 1.0) > 0.5 for f in fills)
    bench_fills = row["benchmark"]["fills"]
    assert all(f["execution_date"] > f["decision_date"] for f in bench_fills)
    assert row["benchmark"]["rebalance_dates"] == row["strategy"]["rebalance_dates"]


def test_cost_monotonic_on_tiny_synthetic() -> None:
    days = _weekdays(date(2024, 1, 2), 12)
    ids = list(range(1, 11))
    market = _market(days, ids, open_px=100.0, close_px=101.0)
    frame = pd.DataFrame(_pred_rows(days, ids))
    nets: list[float] = []
    for bps in COST_BPS_GRID:
        cell = RobustnessCell(
            cost_bps=bps,
            rebalance_every_n_sessions=PRIMARY_REBALANCE_EVERY_N,
            top_quantile=PRIMARY_TOP_QUANTILE,
        )
        row = run_predeclared_cell(
            predictions=frame,
            market=market,
            cell=cell,
            model_variant="V4_FULL",
            initial_capital=1_000_000.0,
        )
        metrics = row["strategy"]["metrics"]
        assert "sharpe_rf0" not in metrics
        assert "sharpe" not in metrics
        nets.append(metrics["cumulative_price_return"])
    assert nets[0] >= nets[1] - 1e-9
    assert nets[1] >= nets[2] - 1e-9
    assert nets[2] >= nets[3] - 1e-9
