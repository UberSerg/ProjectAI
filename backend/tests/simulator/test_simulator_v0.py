"""Historical Simulator V0 unit + synthetic accounting tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.domain.ports.execution import OrderIntent
from app.domain.ports.portfolio import PortfolioPolicyInput, PredictionSignal
from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.simulator.application.calendar import next_trading_day, weekly_rebalance_dates
from app.modules.simulator.application.engine import run_simulation, simulation_values_hash
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter
from app.modules.simulator.application.market_view import DayBar, MarketView, quantity_after_ca
from app.modules.simulator.application.policy import RankLongOnlyV0Policy, select_top_k
from app.modules.simulator.application.predictions import PredictionBundle
from app.modules.simulator.application.risk import RiskGuardrailsV0
from app.modules.simulator.config import SimulationSpecV0


def _bars_constant(instrument_ids: list[int], days: list[date], open_px: float, close_px: float):
    bars: dict[int, dict[date, DayBar]] = {}
    for iid in instrument_ids:
        bars[iid] = {d: DayBar(open=open_px, close=close_px) for d in days}
    return bars


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


def test_select_top_k_ceil_and_min_one() -> None:
    assert select_top_k(0) == 0
    assert select_top_k(1) == 1
    assert select_top_k(4) == 1
    assert select_top_k(5) == 1
    assert select_top_k(10) == 2
    assert select_top_k(11) == 3


def test_policy_top20_equal_weight_and_tiebreak() -> None:
    policy = RankLongOnlyV0Policy()
    day = date(2024, 1, 2)
    signals = [
        PredictionSignal(1, "A", day, 0.1),
        PredictionSignal(2, "B", day, 0.2),
        PredictionSignal(3, "C", day, 0.2),  # tie with B → lower id first after sort by (-pred, id)
        PredictionSignal(4, "D", day, 0.05),
        PredictionSignal(5, "E", day, -0.1),
    ]
    # N=5 → K=ceil(1)=1 → only top: C and B both 0.2, tie-break instrument_id → B(2) before C(3)? 
    # sort key (-pred, id): B(-0.2,2) vs C(-0.2,3) → B first. K=1 → only B.
    out = policy.decide(PortfolioPolicyInput(prediction_signals=tuple(signals)))
    assert out.metadata["selected_k"] == 1
    assert out.decisions[0].ticker == "B"
    assert abs(out.decisions[0].target_weight - 1.0) < 1e-12

    # N=10 → K=2
    more = [
        PredictionSignal(i, f"T{i}", day, float(i))
        for i in range(1, 11)
    ]
    out2 = policy.decide(PortfolioPolicyInput(prediction_signals=tuple(more)))
    assert out2.metadata["selected_k"] == 2
    tickers = [d.ticker for d in out2.decisions]
    assert tickers == ["T10", "T9"]
    assert all(abs(d.target_weight - 0.5) < 1e-12 for d in out2.decisions)


def test_risk_clamps_max_single_weight_and_no_leverage() -> None:
    risk = RiskGuardrailsV0()
    from app.domain.ports.portfolio import PortfolioDecision

    decisions = (
        PortfolioDecision("A", 0.5, "x", {"instrument_id": 1}),
        PortfolioDecision("B", 0.5, "x", {"instrument_id": 2}),
    )
    out = risk.apply(decisions, constraints={"max_single_weight": 0.2, "max_gross_exposure": 1.0})
    assert all(d.target_weight <= 0.2 + 1e-12 for d in out.decisions)
    assert out.metadata["gross_exposure"] <= 1.0 + 1e-12
    assert out.metadata["cash_weight"] >= 0.6 - 1e-9


def test_weekly_rebalance_first_session_of_week() -> None:
    # Tue-Fri week without Monday
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 9)]
    reb = weekly_rebalance_dates(days)
    assert reb[0] == date(2024, 1, 2)
    assert date(2024, 1, 9) in reb
    assert next_trading_day(days, date(2024, 1, 5)) == date(2024, 1, 9)


def test_fill_slippage_and_commission_directions() -> None:
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
        reason="test",
    )
    buy = adapter.fill(intent, raw_open=100.0, commission_bps=10, slippage_bps=20)
    assert buy is not None
    assert buy.fill_price == pytest.approx(100.0 * 1.002)
    assert buy.commission == pytest.approx(buy.notional * 0.001)
    sell_intent = OrderIntent(
        decision_date=intent.decision_date,
        execution_date=intent.execution_date,
        instrument_id=intent.instrument_id,
        ticker=intent.ticker,
        side="SELL",
        target_weight=intent.target_weight,
        target_notional=intent.target_notional,
        quantity=intent.quantity,
        reason=intent.reason,
    )
    sell = adapter.fill(sell_intent, raw_open=100.0, commission_bps=10, slippage_bps=20)
    assert sell is not None
    assert sell.fill_price == pytest.approx(100.0 * 0.998)


def test_quantity_after_split_and_reverse() -> None:
    assert quantity_after_ca(100.0, Decimal("10")) == pytest.approx(1000.0)
    assert quantity_after_ca(5000.0, Decimal("0.0002")) == pytest.approx(1.0)


def test_next_open_execution_and_no_same_close_lookahead() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    # Instrument 1 predicted high on day1; open jumps only on day3
    bars = {
        1: {
            date(2024, 1, 2): DayBar(100, 100),
            date(2024, 1, 3): DayBar(100, 100),
            date(2024, 1, 4): DayBar(110, 110),
            date(2024, 1, 5): DayBar(110, 110),
        },
        2: {d: DayBar(50, 50) for d in days},
        3: {d: DayBar(50, 50) for d in days},
        4: {d: DayBar(50, 50) for d in days},
        5: {d: DayBar(50, 50) for d in days},
    }
    market = MarketView(
        bars=bars,
        actions={},
        tickers={i: f"T{i}" for i in range(1, 6)},
        trading_days=days,
        imoex_id=None,
    )
    rows = []
    for d in days[:2]:
        for i in range(1, 6):
            rows.append(
                {
                    "sample_id": i + d.toordinal(),
                    "instrument_id": i,
                    "as_of_date": d,
                    "y_pred": 1.0 if i == 1 else 0.0,
                    "fold_id": "f1",
                }
            )
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        initial_capital=1_000_000,
    )
    result = run_simulation(spec=spec, bundle=bundle, market=market)
    # First rebalance on first trading day of week = 2024-01-02; fill on 2024-01-03 open=100
    fills = result.ledger.fills
    assert fills
    assert all(f.execution_date > f.decision_date for f in fills if f.decision_date)
    assert fills[0].execution_date == date(2024, 1, 3)
    assert fills[0].raw_open == 100.0
    # Decision on Jan 2 must not use Jan 4 open
    jan2_orders = [o for o in result.ledger.orders if o.decision_date == date(2024, 1, 2)]
    assert jan2_orders
    assert all(o.execution_date == date(2024, 1, 3) for o in jan2_orders)


def test_plzl_split_value_continuity() -> None:
    days = [date(2025, 3, 26), date(2025, 3, 27), date(2025, 3, 28)]
    bars = {
        583: {
            date(2025, 3, 26): DayBar(19000, 19000),
            date(2025, 3, 27): DayBar(1900, 1900),
            date(2025, 3, 28): DayBar(1910, 1910),
        }
    }
    actions = {
        583: [
            MechanicalAction(583, date(2025, 3, 27), "SPLIT", Decimal("10")),
        ]
    }
    market = MarketView(
        bars=bars,
        actions=actions,
        tickers={583: "PLZL"},
        trading_days=days,
        imoex_id=None,
    )
    # Force hold via predictions selecting only PLZL every day
    rows = [
        {
            "sample_id": 1,
            "instrument_id": 583,
            "as_of_date": date(2025, 3, 26),
            "y_pred": 1.0,
            "fold_id": "f",
        }
    ]
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
        initial_capital=1_000_000,
        top_quantile=1.0,  # take all (1)
    )
    # Manual path: buy before split then roll through CA day
    from app.modules.simulator.application.engine import _apply_corporate_actions
    from app.modules.simulator.application.ledger import PortfolioLedger

    ledger = PortfolioLedger(cash=0.0)
    ledger.set_position(583, "PLZL", 100.0)
    before_value = 100 * 19000
    _apply_corporate_actions(ledger, market, date(2025, 3, 27))
    after_qty = ledger.position_qty(583)
    after_value = after_qty * 1900
    assert after_qty == pytest.approx(1000.0)
    assert after_value == pytest.approx(before_value)
    # unused result to keep import of run_simulation path available
    assert bundle.segment == "DEVELOPMENT_OOS"
    assert spec.dividend_cash is False


def test_vtbr_reverse_split_continuity() -> None:
    from app.modules.simulator.application.engine import _apply_corporate_actions
    from app.modules.simulator.application.ledger import PortfolioLedger

    day = date(2024, 7, 15)
    market = MarketView(
        bars={900: {day: DayBar(100, 100)}},
        actions={900: [MechanicalAction(900, day, "REVERSE_SPLIT", Decimal("0.0002"))]},
        tickers={900: "VTBR"},
        trading_days=[day],
        imoex_id=None,
    )
    ledger = PortfolioLedger(cash=0.0)
    ledger.set_position(900, "VTBR", 5000.0)
    before = 5000 * 0.02  # conceptual pre-price; we check qty factor
    _apply_corporate_actions(ledger, market, day)
    assert ledger.position_qty(900) == pytest.approx(1.0)
    assert before == pytest.approx(100.0)  # sanity for 5000*0.02


def test_nav_identity_and_no_dividend_cash() -> None:
    days = [date(2024, 6, 3) + timedelta(days=i) for i in range(14)]
    days = [d for d in days if d.weekday() < 5]
    ids = list(range(1, 6))
    bars = _bars_constant(ids, days, 100.0, 100.0)
    # SBER-like control: instrument 1 price moves without CA
    for d in days:
        bars[1][d] = DayBar(100.0, 100.0 + (d - days[0]).days)
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
                    "sample_id": i + d.toordinal() * 10,
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
        initial_capital=1_000_000,
        commission_bps=0,
        slippage_bps=0,
    )
    result = run_simulation(spec=spec, bundle=bundle, market=market)
    for snap in result.ledger.snapshots:
        mv = sum(
            (p["market_value"] or 0.0) for p in snap.positions.values() if p.get("market_value") is not None
        )
        assert snap.nav == pytest.approx(snap.cash + mv, rel=0, abs=1e-4)
        assert snap.cash >= -1e-6
        assert snap.gross_exposure <= 1.0 + 1e-6
    assert result.spec.dividend_cash is False
    assert result.metrics["return_type"] == "price_return"


def test_future_open_does_not_change_past_decision() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    ids = [1, 2, 3, 4, 5]
    bars1 = _bars_constant(ids, days, 100.0, 100.0)
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
                    "y_pred": float(10 - i),
                    "fold_id": "f",
                }
            )
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
    )
    r1 = run_simulation(spec=spec, bundle=bundle, market=market1)
    bars2 = _bars_constant(ids, days, 100.0, 100.0)
    bars2[1][date(2024, 1, 4)] = DayBar(999.0, 999.0)  # future open mutation
    market2 = MarketView(
        bars=bars2,
        actions={},
        tickers={i: f"T{i}" for i in ids},
        trading_days=days,
        imoex_id=None,
    )
    r2 = run_simulation(spec=spec, bundle=bundle, market=market2)
    day0 = date(2024, 1, 2)
    orders1 = [
        (o.decision_date, o.instrument_id, o.side, o.quantity)
        for o in r1.ledger.orders
        if o.decision_date == day0
    ]
    orders2 = [
        (o.decision_date, o.instrument_id, o.side, o.quantity)
        for o in r2.ledger.orders
        if o.decision_date == day0
    ]
    assert orders1 == orders2
    nav1 = next(s.nav for s in r1.ledger.snapshots if s.as_of == date(2024, 1, 2))
    nav2 = next(s.nav for s in r2.ledger.snapshots if s.as_of == date(2024, 1, 2))
    assert nav1 == pytest.approx(nav2)


def test_repeat_deterministic_hash() -> None:
    days = [date(2024, 2, 5) + timedelta(days=i) for i in range(20)]
    days = [d for d in days if d.weekday() < 5]
    ids = [1, 2, 3, 4, 5]
    bars = _bars_constant(ids, days, 10.0, 10.0)
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
                    "y_pred": float(i) * 0.01,
                    "fold_id": "f",
                }
            )
    bundle = _bundle_from_rows(rows)
    spec = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="cfg",
        dataset_values_hash="ds",
        prediction_hash="pred",
    )
    a = run_simulation(spec=spec, bundle=bundle, market=market)
    b = run_simulation(spec=spec, bundle=bundle, market=market)
    assert simulation_values_hash(a.ledger) == simulation_values_hash(b.ledger)
    assert a.metrics["final_nav"] == pytest.approx(b.metrics["final_nav"])


def test_segments_remain_separate_in_spec() -> None:
    a = SimulationSpecV0(
        segment="DEVELOPMENT_OOS",
        candidate_config_hash="c",
        dataset_values_hash="d",
        prediction_hash="p1",
    )
    b = SimulationSpecV0(
        segment="FINAL_HOLDOUT",
        candidate_config_hash="c",
        dataset_values_hash="d",
        prediction_hash="p2",
    )
    assert a.config_hash() != b.config_hash()
    assert a.segment != b.segment


def test_fractional_shares_allowed() -> None:
    adapter = HistoricalNextOpenAdapter()
    intent = OrderIntent(
        decision_date=date(2024, 1, 2),
        execution_date=date(2024, 1, 3),
        instrument_id=1,
        ticker="X",
        side="BUY",
        target_weight=0.1,
        target_notional=150,
        quantity=1.5,
        reason="frac",
    )
    fill = adapter.fill(intent, raw_open=100.0, commission_bps=0, slippage_bps=0)
    assert fill is not None
    assert fill.quantity == pytest.approx(1.5)
