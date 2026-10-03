"""Long-only research economics simulator contract tests (synthetic)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.research_evidence.economics import (
    ASSUMED_ALL_IN_COST_BPS_PER_SIDE,
    MODEL_VARIANTS,
    SKIPPED_BY_BOUNDARY,
    EconomicsProvenanceError,
    rebalance_decision_dates,
    required_market_date_to,
    run_all_model_variants,
    run_research_economics,
    run_research_economics_cost_grid,
    validate_oos_prediction_frame,
)
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
    open_px: float = 100.0,
    close_px: float = 101.0,
    opens: dict[tuple[int, date], float] | None = None,
    closes: dict[tuple[int, date], float] | None = None,
    actions: dict[int, list[MechanicalAction]] | None = None,
    imoex_id: int | None = None,
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
    tickers = {iid: f"T{iid}" for iid in ids}
    if imoex_id is not None:
        tickers[imoex_id] = "IMOEX"
    return MarketView(
        bars=bars,
        actions=actions or {},
        tickers=tickers,
        trading_days=days,
        imoex_id=imoex_id,
    )


def _pred_rows(
    days: list[date],
    ids: list[int],
    *,
    variant: str = "BASE",
    score_fn=None,
    extra: dict | None = None,
) -> list[dict]:
    cutoff = days[0] - timedelta(days=1)
    rows: list[dict] = []
    for d in days:
        for iid in ids:
            score = float(iid) if score_fn is None else float(score_fn(d, iid))
            row = {
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
            }
            if extra:
                row.update(extra)
            rows.append(row)
    return rows


def test_eod_cannot_execute_same_day_and_next_open_used() -> None:
    days = _weekdays(date(2024, 1, 2), 8)
    ids = list(range(1, 11))
    opens = {(iid, d): 100.0 for iid in ids for d in days}
    closes = {(iid, d): 50.0 for iid in ids for d in days}
    opens[(10, days[1])] = 123.0
    market = _market(days, ids, opens=opens, closes=closes)
    frame = pd.DataFrame(_pred_rows(days, ids, score_fn=lambda _d, iid: float(iid)))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
        initial_capital=1_000_000.0,
    )
    fills = result["ledger"].fills
    assert fills
    assert all(f.execution_date > f.decision_date for f in fills)
    first = min(fills, key=lambda f: (f.execution_date, f.instrument_id))
    assert first.decision_date == days[0]
    assert first.execution_date == days[1]
    top_fills = [f for f in fills if f.execution_date == days[1] and f.instrument_id == 10]
    assert top_fills
    assert top_fills[0].raw_open == pytest.approx(123.0)
    assert top_fills[0].fill_price == pytest.approx(123.0)
    assert all(abs(f.fill_price - 50.0) > 1.0 for f in fills)


def test_missing_open_never_uses_close() -> None:
    days = _weekdays(date(2024, 1, 2), 6)
    ids = list(range(1, 11))
    opens = {(iid, d): 100.0 for iid in ids for d in days}
    closes = {(iid, d): 80.0 for iid in ids for d in days}
    opens[(10, days[1])] = 0.0
    opens[(9, days[1])] = 0.0
    market = _market(days, ids, opens=opens, closes=closes)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    assert result["metrics"]["unavailable_executions"] >= 1
    assert any(
        e["status"] == "EXECUTION_PRICE_UNAVAILABLE"
        for e in result["unavailable_execution_events"]
    )
    for fill in result["ledger"].fills:
        if fill.execution_date == days[1] and fill.instrument_id in {9, 10}:
            raise AssertionError("filled using close (or any price) when OPEN missing")
        assert fill.raw_open != 80.0
        assert fill.fill_price != 80.0


def test_cadence_deterministic_every_20_sessions() -> None:
    days = _weekdays(date(2024, 1, 2), 45)
    expected = [days[0], days[20], days[40]]
    assert rebalance_decision_dates(days) == expected
    ids = list(range(1, 11))
    market = _market(days, ids)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    assert result["rebalance_dates"] == [d.isoformat() for d in expected]
    assert result["metrics"]["n_rebalances"] == 3
    decision_dates = {o.decision_date for o in result["ledger"].orders}
    assert decision_dates <= set(expected)


def test_oos_provenance_required_and_rejects() -> None:
    days = _weekdays(date(2024, 1, 2), 5)
    ids = list(range(1, 11))
    market = _market(days, ids)
    base = _pred_rows(days, ids)

    missing = pd.DataFrame([{k: v for k, v in base[0].items() if k != "fold_id"}])
    with pytest.raises(EconomicsProvenanceError, match="fold_id"):
        validate_oos_prediction_frame(missing, model_variant="BASE")

    insample = pd.DataFrame(base)
    insample.loc[0, "is_oos"] = False
    with pytest.raises(EconomicsProvenanceError, match="in-sample"):
        validate_oos_prediction_frame(insample, model_variant="BASE")

    prod = pd.DataFrame(base)
    prod["is_production_candidate"] = False
    prod.loc[0, "is_production_candidate"] = True
    with pytest.raises(EconomicsProvenanceError, match="production Candidate"):
        validate_oos_prediction_frame(prod, model_variant="BASE")

    hashed = pd.DataFrame(base)
    with pytest.raises(EconomicsProvenanceError, match="dataset_values_hash"):
        validate_oos_prediction_frame(
            hashed, model_variant="BASE", expected_dataset_values_hash="other-hash"
        )
    hashed.loc[1, "dataset_values_hash"] = "other-hash"
    with pytest.raises(EconomicsProvenanceError, match="mismatched dataset hashes"):
        validate_oos_prediction_frame(hashed, model_variant="BASE")

    same_day = pd.DataFrame(base)
    same_day["execution_date"] = same_day["decision_date"]
    with pytest.raises(EconomicsProvenanceError, match="same-close"):
        validate_oos_prediction_frame(same_day, model_variant="BASE", trading_days=days)

    future = pd.DataFrame(base)
    future["execution_date"] = days[3]
    with pytest.raises(EconomicsProvenanceError, match="future-open"):
        validate_oos_prediction_frame(future, model_variant="BASE", trading_days=days)

    uni = pd.DataFrame(base)
    uni["universe_policy"] = "current_active"
    with pytest.raises(EconomicsProvenanceError, match="historical_equity_universe_v2"):
        validate_oos_prediction_frame(uni, model_variant="BASE")

    with pytest.raises(EconomicsProvenanceError):
        run_research_economics(
            predictions=insample,
            market=market,
            model_variant="BASE",
        )


def test_split_no_phantom_pnl() -> None:
    days = _weekdays(date(2024, 3, 4), 6)
    ids = list(range(1, 11))
    split_day = days[2]
    opens: dict[tuple[int, date], float] = {}
    closes: dict[tuple[int, date], float] = {}
    for iid in ids:
        for d in days:
            px = 10.0 if (iid == 10 and d >= split_day) else 100.0
            opens[(iid, d)] = px
            closes[(iid, d)] = px
    actions = {10: [MechanicalAction(10, split_day, "SPLIT", Decimal("10"))]}
    market = _market(days, ids, opens=opens, closes=closes, actions=actions)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
        initial_capital=1_000_000.0,
    )
    snaps = {s.as_of: s for s in result["ledger"].snapshots}
    before = snaps[days[1]]
    after = snaps[split_day]
    pos_before = before.positions.get(10)
    pos_after = after.positions.get(10)
    assert pos_before is not None and pos_after is not None
    assert pos_after["quantity"] == pytest.approx(pos_before["quantity"] * 10.0)
    assert pos_after["market_value"] == pytest.approx(pos_before["market_value"], rel=1e-9)
    assert after.nav == pytest.approx(before.nav, rel=1e-6)
    assert after.nav > 0.5 * before.nav


def test_cost_drag_monotonic_net() -> None:
    days = _weekdays(date(2024, 1, 2), 25)
    ids = list(range(1, 11))
    market = _market(days, ids, open_px=100.0, close_px=101.0)
    frame = pd.DataFrame(_pred_rows(days, ids))
    grid = run_research_economics_cost_grid(
        predictions=frame,
        market=market,
        model_variant="BASE",
        initial_capital=1_000_000.0,
    )
    nets = [
        grid["net_by_cost_bps"][bps]["cumulative_price_return"]
        for bps in ASSUMED_ALL_IN_COST_BPS_PER_SIDE
    ]
    assert nets[0] >= nets[1] - 1e-9
    assert nets[1] >= nets[2] - 1e-9
    assert nets[2] >= nets[3] - 1e-9
    assert grid["gross"]["cumulative_price_return"] == pytest.approx(nets[0])
    assert grid["cost_drag_vs_0bps"][10] >= -1e-12
    assert "sharpe_rf0" not in grid["gross"]
    assert "V4 makes money" not in grid["wording"]
    assert grid["wording"].startswith("Historical OOS research simulation under assumptions")
    assert grid["limitations"]
    assert grid["primary_benchmark"]["type"] == "eligible_universe_equal_weight"
    assert grid["primary_benchmark"]["same_rebalance_dates"] is True


def test_no_dividend_cash() -> None:
    days = _weekdays(date(2024, 1, 2), 8)
    ids = list(range(1, 11))
    actions = {
        10: [MechanicalAction(10, days[2], "DIVIDEND", Decimal("1"))],
    }
    market = _market(days, ids, open_px=100.0, close_px=100.0, actions=actions)
    frame = pd.DataFrame(_pred_rows(days, ids))
    zero = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
        initial_capital=1_000_000.0,
    )
    assert all(ev["event_type"] != "DIVIDEND" for ev in zero["ca_events"])
    market2 = _market(days, ids, open_px=100.0, close_px=100.0, actions={})
    baseline = run_research_economics(
        predictions=frame,
        market=market2,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
        initial_capital=1_000_000.0,
    )
    assert zero["final_cash"] == pytest.approx(baseline["final_cash"])
    assert zero["final_nav"] == pytest.approx(baseline["final_nav"])


def test_cash_preserved_no_leverage_thin_cross_section_stays_cash() -> None:
    days = _weekdays(date(2024, 1, 2), 8)
    ids = [1, 2, 3]
    market = _market(days, ids, open_px=100.0, close_px=120.0)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
        initial_capital=1_000_000.0,
    )
    assert result["ledger"].fills == []
    assert result["final_cash"] == pytest.approx(1_000_000.0)
    assert result["final_nav"] == pytest.approx(1_000_000.0)
    assert result["metrics"]["avg_cash_weight"] == pytest.approx(1.0)
    for snap in result["ledger"].snapshots:
        assert snap.cash >= -1e-9
        assert snap.gross_exposure <= 1.0 + 1e-9
        assert snap.cash_weight <= 1.0 + 1e-9


def test_no_leverage_when_invested() -> None:
    days = _weekdays(date(2024, 1, 2), 12)
    ids = list(range(1, 11))
    market = _market(days, ids)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=30,
        initial_capital=1_000_000.0,
    )
    assert result["ledger"].fills
    for snap in result["ledger"].snapshots:
        assert snap.cash >= -1e-6
        assert snap.gross_exposure <= 1.0 + 1e-6
    assert result["metrics"]["avg_gross_exposure"] <= 1.0 + 1e-6


def test_same_contract_all_variants_does_not_retune() -> None:
    days = _weekdays(date(2024, 1, 2), 22)
    ids = list(range(1, 11))
    market = _market(days, ids)
    rows: list[dict] = []
    for variant in MODEL_VARIANTS:
        rows.extend(_pred_rows(days, ids, variant=variant))
    frame = pd.DataFrame(rows)
    blob = run_all_model_variants(
        predictions=frame,
        market=market,
        initial_capital=1_000_000.0,
    )
    settings = blob["economic_settings"]
    assert settings["rebalance_every_n_sessions"] == 20
    assert settings["top_quantile"] == 0.20
    assert settings["costs_bps"] == list(ASSUMED_ALL_IN_COST_BPS_PER_SIDE)
    reb = None
    for variant in MODEL_VARIANTS:
        run = blob["variants"][variant]
        assert run["assumptions"]["rebalance_every_n_sessions"] == 20
        assert run["assumptions"]["top_quantile"] == 0.20
        if reb is None:
            reb = run["rebalance_dates"]
        else:
            assert run["rebalance_dates"] == reb
        assert run["wording"].startswith("Historical OOS research simulation under assumptions")
        assert "makes money" not in run["wording"].lower()


def test_imoex_skipped_if_not_aligned() -> None:
    days = _weekdays(date(2024, 1, 2), 8)
    ids = list(range(1, 11))
    market = _market(days, ids, imoex_id=999)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
    )
    assert result["imoex"]["included"] is False
    assert result["imoex"]["skipped_reason"]


def test_unresolved_exit_when_no_valid_open() -> None:
    days = _weekdays(date(2024, 1, 2), 25)
    ids = list(range(1, 11))
    opens = {(iid, d): 100.0 for iid in ids for d in days}
    closes = {(iid, d): 100.0 for iid in ids for d in days}
    exec2 = days[21]
    for d in days:
        if d >= exec2:
            opens[(10, d)] = 0.0
            opens[(9, d)] = 0.0
    market = _market(days, ids, opens=opens, closes=closes)
    rows = _pred_rows(days, ids)
    # Second rebalance (day 20): drop former holdings from the eligible set.
    rows = [
        r
        for r in rows
        if not (r["decision_date"] == days[20] and r["instrument_id"] in {9, 10})
    ]
    result = run_research_economics(
        predictions=pd.DataFrame(rows),
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    assert result["status"] == "PARTIAL"
    assert result["metrics"]["unresolved_exits"] >= 1
    assert any(e["status"] == "UNRESOLVED_EXIT" for e in result["unresolved_exit_events"])


def test_metrics_keys_short_horizon_not_annualized() -> None:
    days = _weekdays(date(2024, 1, 2), 3)
    ids = list(range(1, 11))
    market = _market(days, ids, open_px=100.0, close_px=100.0)
    frame = pd.DataFrame(_pred_rows(days[:1], ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    metrics = result["metrics"]
    for key in (
        "start_nav",
        "end_nav",
        "cumulative_price_return",
        "annualized_return",
        "annualized_vol",
        "max_drawdown",
        "turnover",
        "n_rebalances",
        "n_trades",
        "avg_holdings",
        "avg_cash_weight",
        "unavailable_executions",
        "unresolved_exits",
    ):
        assert key in metrics
    assert metrics["annualized_return"] is None
    assert metrics["annualized_return_reason"]
    assert metrics["return_semantic"] == "PRICE_RETURN"


def test_required_market_date_to_is_plus_one_session() -> None:
    days = _weekdays(date(2024, 1, 2), 5)
    assert required_market_date_to([days[0], days[2]], days) == days[3]
    assert required_market_date_to([days[-1]], days) == days[-1]


def test_terminal_rebalance_skipped_by_boundary_not_counted() -> None:
    days = _weekdays(date(2024, 1, 2), 21)
    ids = list(range(1, 11))
    market = _market(days, ids)
    frame = pd.DataFrame(_pred_rows(days, ids))
    result = run_research_economics(
        predictions=frame,
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    assert result["terminal_next_open_policy"] == "OPTION_B_SKIPPED_BY_BOUNDARY"
    assert result["terminal_rebalance_without_execution_session"] == SKIPPED_BY_BOUNDARY
    assert result["skipped_rebalance_dates"] == [days[20].isoformat()]
    assert result["rebalance_dates"] == [days[0].isoformat()]
    assert result["metrics"]["n_rebalances"] == 1
    assert all(f.execution_date > f.decision_date for f in result["ledger"].fills)
    assert all(o.execution_date > o.decision_date for o in result["ledger"].orders)
    assert days[20].isoformat() not in result["rebalance_dates"]


def test_forced_exit_keeps_original_decision_date_on_later_open() -> None:
    days = _weekdays(date(2024, 1, 2), 25)
    ids = list(range(1, 11))
    decision = days[20]
    miss_open = days[21]
    fill_open = days[22]
    opens = {(iid, d): 100.0 for iid in ids for d in days}
    closes = {(iid, d): 100.0 for iid in ids for d in days}
    opens[(10, miss_open)] = 0.0
    opens[(9, miss_open)] = 0.0
    market = _market(days, ids, opens=opens, closes=closes)
    rows = [
        r
        for r in _pred_rows(days, ids)
        if not (r["decision_date"] == decision and r["instrument_id"] in {9, 10})
    ]
    result = run_research_economics(
        predictions=pd.DataFrame(rows),
        market=market,
        model_variant="BASE",
        all_in_cost_bps_per_side=0,
    )
    forced = [
        f
        for f in result["ledger"].fills
        if f.instrument_id in {9, 10} and f.side == "SELL"
    ]
    assert forced
    for fill in forced:
        assert fill.decision_date == decision
        assert fill.execution_date == fill_open
        assert fill.execution_date > fill.decision_date
        assert fill.raw_open == pytest.approx(100.0)
        assert fill.fill_price != 0.0
    assert all(f.execution_date > f.decision_date for f in result["ledger"].fills)
    assert all(o.execution_date > o.decision_date for o in result["ledger"].orders)
