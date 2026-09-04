"""Policy / Risk Research V1 unit tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.domain.ports.execution import OrderIntent
from app.domain.ports.portfolio import PortfolioDecision, PortfolioPolicyInput, PredictionSignal
from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.simulator.application.drawdown_guard import (
    DrawdownGuardState,
    apply_exposure_cap,
    update_drawdown_guard,
)
from app.modules.simulator.application.engine import run_simulation
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter
from app.modules.simulator.application.ledger import PortfolioLedger
from app.modules.simulator.application.market_view import DayBar, MarketView, quantity_after_ca
from app.modules.simulator.application.policy import RankLongOnlyV0Policy, select_top_k
from app.modules.simulator.application.policy_hysteresis import RankHysteresisLongOnlyV1Policy
from app.modules.simulator.application.predictions import PredictionBundle
from app.modules.simulator.application.risk import RiskGuardrailsV0
from app.modules.simulator.config import (
    POLICY_HYSTERESIS_V1,
    POLICY_NAME,
    RISK_DD_GUARD_V1,
    RISK_NAME,
    SimulationSpecV0,
    hysteresis_dd_v1_spec_kwargs,
    hysteresis_v1_spec_kwargs,
)


def _bundle_from_rows(rows: list[dict], segment: str = "DEVELOPMENT_OOS") -> PredictionBundle:
    frame = pd.DataFrame(rows)
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return PredictionBundle(
        segment=segment,  # type: ignore[arg-type]
        artifact_dir=Path("."),
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        frame=frame,
        fold_aware="fold_id" in frame.columns,
    )


def _bars_constant(instrument_ids: list[int], days: list[date], open_px: float, close_px: float):
    bars: dict[int, dict[date, DayBar]] = {}
    for iid in instrument_ids:
        bars[iid] = {d: DayBar(open=open_px, close=close_px) for d in days}
    return bars


def test_v0_policy_behavior_unchanged() -> None:
    """A: V0 policy selection identical to pre-V1 RankLongOnlyV0."""
    policy = RankLongOnlyV0Policy()
    day = date(2024, 1, 2)
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 11)]
    out = policy.decide(PortfolioPolicyInput(prediction_signals=tuple(signals)))
    assert out.metadata["selected_k"] == 2
    assert [d.ticker for d in out.decisions] == ["T10", "T9"]
    assert all(abs(d.target_weight - 0.5) < 1e-12 for d in out.decisions)


def test_hysteresis_entry_top20() -> None:
    """B: entry only within top 20%."""
    policy = RankHysteresisLongOnlyV1Policy()
    day = date(2024, 1, 2)
    # N=10 → k_entry=2, k_max=4
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 11)]
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={"held_instrument_ids": (), "entry_quantile": 0.20, "exit_quantile": 0.35},
        )
    )
    assert out.metadata["k_entry"] == 2
    assert out.metadata["selected_k"] == 2
    assert {d.metadata["action"] for d in out.decisions} == {"ENTER_TOP20"}
    assert [d.ticker for d in out.decisions] == ["T10", "T9"]


def test_hysteresis_exit_top35_and_no_churn_in_band() -> None:
    """C+D: hold inside exit band; exit below top35."""
    policy = RankHysteresisLongOnlyV1Policy()
    day = date(2024, 1, 2)
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 11)]
    # Hold T8 (rank 3) — outside entry (top2) but inside exit (top4)
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={
                "held_instrument_ids": (8,),
                "entry_quantile": 0.20,
                "exit_quantile": 0.35,
            },
        )
    )
    tickers = {d.ticker for d in out.decisions}
    assert "T8" in tickers
    actions = {d.ticker: d.metadata["action"] for d in out.decisions}
    assert actions["T8"] == "HOLD_WITHIN_EXIT_BAND"
    # Still fill to k_entry=2 with top names not already held
    assert out.metadata["selected_k"] >= 2
    assert out.metadata["selected_k"] <= out.metadata["k_max"]

    # Hold T5 (rank 6) — below exit band (k_max=4) → not retained
    out2 = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={
                "held_instrument_ids": (5,),
                "entry_quantile": 0.20,
                "exit_quantile": 0.35,
            },
        )
    )
    assert "T5" not in {d.ticker for d in out2.decisions}


def test_hysteresis_deterministic_tiebreak() -> None:
    """E: tie-break predicted_return desc, instrument_id asc."""
    policy = RankHysteresisLongOnlyV1Policy()
    day = date(2024, 1, 2)
    signals = [
        PredictionSignal(1, "A", day, 0.2),
        PredictionSignal(2, "B", day, 0.2),
        PredictionSignal(3, "C", day, 0.1),
        PredictionSignal(4, "D", day, 0.05),
        PredictionSignal(5, "E", day, 0.0),
    ]
    # N=5 → k_entry=1
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={"held_instrument_ids": ()},
        )
    )
    assert out.decisions[0].ticker == "A"  # same pred as B, lower id


def test_min_trade_delta_suppresses_tiny_rebalance() -> None:
    """F: 2pp min weight delta suppresses tiny rebalance."""
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 9), date(2024, 1, 10)]
    ids = list(range(1, 11))
    bars = _bars_constant(ids, days, 100.0, 100.0)
    market = MarketView(
        bars=bars,
        actions={},
        tickers={i: f"T{i}" for i in ids},
        trading_days=days,
        imoex_id=None,
    )
    rows = []
    for d in days:
        for i in ids:
            rows.append(
                {
                    "sample_id": i + d.toordinal(),
                    "instrument_id": i,
                    "as_of_date": d,
                    "y_pred": float(i),
                    "fold_id": "f",
                }
            )
    bundle = _bundle_from_rows(rows)
    # Flat prices + identical ranks → after first fill, second rebalance should skip tiny deltas
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        **hysteresis_v1_spec_kwargs(),
    )
    result = run_simulation(spec=spec, bundle=bundle, market=market)
    # Second week decision on 2024-01-09 should not emit REBALANCE_WEIGHT_DELTA for already-equal weights
    week2 = [o for o in result.ledger.orders if o.decision_date == date(2024, 1, 9)]
    assert all(o.reason != "REBALANCE_WEIGHT_DELTA" or abs(o.target_weight) < 1e-9 for o in week2)
    # With flat prices and same selection, week2 should preferably have zero or only EXIT/ENTER
    assert all(abs(o.target_notional) >= 1.0 for o in week2)


def test_equal_weight_and_no_leverage_hysteresis() -> None:
    """G+H: equal weights; no leverage after risk."""
    policy = RankHysteresisLongOnlyV1Policy()
    risk = RiskGuardrailsV0()
    day = date(2024, 1, 2)
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 11)]
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={"held_instrument_ids": ()},
        )
    )
    k = len(out.decisions)
    assert k > 0
    assert all(abs(d.target_weight - 1.0 / k) < 1e-12 for d in out.decisions)
    risk_out = risk.apply(
        out.decisions,
        constraints={"max_single_weight": 0.2, "max_gross_exposure": 1.0, "long_only": True},
    )
    assert risk_out.metadata["gross_exposure"] <= 1.0 + 1e-12
    assert all(d.target_weight <= 0.2 + 1e-12 for d in risk_out.decisions)


def test_dd_guard_historical_nav_only_and_trigger() -> None:
    """I+J+K: risk-off at -20%; gross capped 50%; uses historical NAV only."""
    state = DrawdownGuardState()
    state = update_drawdown_guard(
        state,
        as_of=date(2024, 1, 2),
        nav=100.0,
        peak_nav=100.0,
        drawdown=0.0,
    )
    assert state.mode == "normal"
    assert state.exposure_cap == pytest.approx(1.0)

    state = update_drawdown_guard(
        state,
        as_of=date(2024, 1, 3),
        nav=79.0,
        peak_nav=100.0,
        drawdown=-0.21,
    )
    assert state.mode == "risk_off"
    assert state.exposure_cap == pytest.approx(0.5)
    assert state.events[-1]["reason"] == "DD_GUARD_REDUCE"

    decisions = (
        PortfolioDecision("A", 0.2, "x", {"instrument_id": 1}),
        PortfolioDecision("B", 0.2, "x", {"instrument_id": 2}),
        PortfolioDecision("C", 0.2, "x", {"instrument_id": 3}),
        PortfolioDecision("D", 0.2, "x", {"instrument_id": 4}),
        PortfolioDecision("E", 0.2, "x", {"instrument_id": 5}),
    )
    capped = apply_exposure_cap(decisions, exposure_cap=0.5, max_single_weight=0.2)
    assert capped.metadata["gross_exposure"] <= 0.5 + 1e-12
    assert all(d.target_weight <= 0.2 + 1e-12 for d in capped.decisions)


def test_dd_guard_recovery_and_hysteresis() -> None:
    """L+M: recover at -10%; no flip-flop between -20 and -10."""
    state = DrawdownGuardState(mode="risk_off", exposure_cap=0.5)
    # Still between -20 and -10 → stay risk_off
    state = update_drawdown_guard(
        state,
        as_of=date(2024, 1, 4),
        nav=85.0,
        peak_nav=100.0,
        drawdown=-0.15,
    )
    assert state.mode == "risk_off"
    assert state.exposure_cap == pytest.approx(0.5)
    assert not state.events

    state = update_drawdown_guard(
        state,
        as_of=date(2024, 1, 5),
        nav=91.0,
        peak_nav=100.0,
        drawdown=-0.09,
    )
    assert state.mode == "normal"
    assert state.exposure_cap == pytest.approx(1.0)
    assert state.events[-1]["reason"] == "DD_GUARD_RECOVER"


def test_future_nav_mutation_does_not_change_past_risk_state() -> None:
    """N: future NAV mutation does not rewrite past risk transitions."""
    days = [date(2024, 1, 2) + timedelta(days=i) for i in range(40)]
    days = [d for d in days if d.weekday() < 5]
    ids = list(range(1, 6))
    bars1 = _bars_constant(ids, days, 100.0, 100.0)
    # Crash mid-window then recover
    crash_day = days[10]
    for d in days:
        if d >= crash_day:
            px = 70.0
            for iid in ids:
                bars1[iid][d] = DayBar(px, px)
    market1 = MarketView(
        bars=bars1,
        actions={},
        tickers={i: f"T{i}" for i in ids},
        trading_days=days,
        imoex_id=None,
    )
    rows = []
    for d in days:
        for i in ids:
            rows.append(
                {
                    "sample_id": i + d.toordinal(),
                    "instrument_id": i,
                    "as_of_date": d,
                    "y_pred": float(i),
                    "fold_id": "f",
                }
            )
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        **hysteresis_dd_v1_spec_kwargs(),
    )
    r1 = run_simulation(spec=spec, bundle=bundle, market=market1)
    events_before = [e for e in r1.ledger.risk_events if e["date"] <= days[12].isoformat()]

    bars2 = {iid: dict(day_map) for iid, day_map in bars1.items()}
    late = days[-1]
    for iid in ids:
        bars2[iid][late] = DayBar(500.0, 500.0)
    market2 = MarketView(
        bars=bars2,
        actions={},
        tickers={i: f"T{i}" for i in ids},
        trading_days=days,
        imoex_id=None,
    )
    r2 = run_simulation(spec=spec, bundle=bundle, market=market2)
    events_before2 = [e for e in r2.ledger.risk_events if e["date"] <= days[12].isoformat()]
    assert events_before == events_before2


def test_next_open_and_costs_unchanged_under_v1() -> None:
    """O+P: next-open fills; cost model same as V0 adapter path."""
    adapter = HistoricalNextOpenAdapter()
    intent = OrderIntent(
        decision_date=date(2024, 1, 2),
        execution_date=date(2024, 1, 3),
        instrument_id=1,
        ticker="SBER",
        side="BUY",
        target_weight=0.1,
        target_notional=1000,
        quantity=10,
        reason="ENTER_TOP20",
        policy_name=POLICY_HYSTERESIS_V1,
    )
    buy = adapter.fill(intent, raw_open=100.0, commission_bps=10, slippage_bps=20)
    assert buy is not None
    assert buy.fill_price == pytest.approx(100.0 * 1.002)
    assert buy.commission == pytest.approx(buy.notional * 0.001)


def test_split_accounting_unchanged() -> None:
    """Q: PLZL/VTBR mechanical CA unchanged."""
    from app.modules.simulator.application.engine import _apply_corporate_actions

    day = date(2025, 3, 27)
    market = MarketView(
        bars={583: {day: DayBar(1900, 1900)}},
        actions={583: [MechanicalAction(583, day, "SPLIT", Decimal("10"))]},
        tickers={583: "PLZL"},
        trading_days=[day],
        imoex_id=None,
    )
    ledger = PortfolioLedger(cash=0.0)
    ledger.set_position(583, "PLZL", 100.0)
    _apply_corporate_actions(ledger, market, day)
    assert ledger.position_qty(583) == pytest.approx(1000.0)
    assert quantity_after_ca(5000.0, Decimal("0.0002")) == pytest.approx(1.0)


def test_policy_and_risk_config_hash_deterministic() -> None:
    """R+S: config hashes deterministic and V0 identity preserved."""
    base = dict(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
    )
    v0_a = SimulationSpecV0(**base)
    v0_b = SimulationSpecV0(**base)
    assert v0_a.config_hash() == v0_b.config_hash()
    assert v0_a.policy_name == POLICY_NAME
    assert v0_a.risk_name == RISK_NAME

    hyst_a = SimulationSpecV0(**base, **hysteresis_v1_spec_kwargs())
    hyst_b = SimulationSpecV0(**base, **hysteresis_v1_spec_kwargs())
    assert hyst_a.config_hash() == hyst_b.config_hash()
    assert hyst_a.config_hash() != v0_a.config_hash()

    dd_a = SimulationSpecV0(**base, **hysteresis_dd_v1_spec_kwargs())
    dd_b = SimulationSpecV0(**base, **hysteresis_dd_v1_spec_kwargs())
    assert dd_a.config_hash() == dd_b.config_hash()
    assert dd_a.config_hash() != hyst_a.config_hash()
    assert dd_a.risk_name == RISK_DD_GUARD_V1


def test_trace_reasons_persisted_in_orders_and_risk_events() -> None:
    """T: order reasons and risk events persisted."""
    days = [date(2024, 1, 2) + timedelta(days=i) for i in range(30)]
    days = [d for d in days if d.weekday() < 5]
    ids = list(range(1, 11))
    bars = _bars_constant(ids, days, 100.0, 100.0)
    # Force portfolio DD past -20%: with ~40% gross (2×20% caps), need ~50%+ price drop
    for d in days[5:]:
        for iid in ids:
            bars[iid][d] = DayBar(40.0, 40.0)
    market = MarketView(
        bars=bars,
        actions={},
        tickers={i: f"T{i}" for i in ids},
        trading_days=days,
        imoex_id=None,
    )
    rows = []
    for d in days:
        for i in ids:
            # Flip ranks mid-window to force exits
            pred = float(i) if d < days[8] else float(11 - i)
            rows.append(
                {
                    "sample_id": i + d.toordinal(),
                    "instrument_id": i,
                    "as_of_date": d,
                    "y_pred": pred,
                    "fold_id": "f",
                }
            )
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        **hysteresis_dd_v1_spec_kwargs(),
    )
    result = run_simulation(spec=spec, bundle=bundle, market=market)
    reasons = {o.reason for o in result.ledger.orders}
    assert reasons & {"ENTER_TOP20", "EXIT_BELOW_TOP35", "HOLD_WITHIN_EXIT_BAND", "REBALANCE_WEIGHT_DELTA"}
    assert result.ledger.risk_events
    assert any(e["reason"] == "DD_GUARD_REDUCE" for e in result.ledger.risk_events)
    assert "risk_events" in result.metrics


def test_v0_vs_hysteresis_selection_differs_when_held_in_band() -> None:
    """Sanity: hysteresis retains in-band name that V0 would drop."""
    day = date(2024, 1, 2)
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 11)]
    v0 = RankLongOnlyV0Policy().decide(PortfolioPolicyInput(prediction_signals=tuple(signals)))
    hyst = RankHysteresisLongOnlyV1Policy().decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={"held_instrument_ids": (8,)},
        )
    )
    assert "T8" not in {d.ticker for d in v0.decisions}
    assert "T8" in {d.ticker for d in hyst.decisions}


def test_select_top_k_shared() -> None:
    assert select_top_k(40, 0.20) == 8
    assert select_top_k(40, 0.35) == 14
