"""Historical Simulator V0 daily event loop."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.domain.ports.execution import OrderIntent
from app.domain.ports.portfolio import PortfolioPolicy, PortfolioPolicyInput
from app.domain.ports.risk import RiskManager
from app.modules.investment.domain.hurdle import benchmark_metrics, piecewise_calendar_accrual
from app.modules.simulator.application.benchmark import imoex_price_return, imoex_price_series
from app.modules.simulator.application.calendar import next_trading_day, weekly_rebalance_dates
from app.modules.simulator.application.drawdown_guard import (
    DrawdownGuardState,
    apply_exposure_cap,
    update_drawdown_guard,
)
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter
from app.modules.simulator.application.ledger import PortfolioLedger
from app.modules.simulator.application.market_view import MarketView, quantity_after_ca
from app.modules.simulator.application.metrics import annual_nav_slices, compute_metrics
from app.modules.simulator.application.policy import RankLongOnlyV0Policy
from app.modules.simulator.application.policy_hysteresis import RankHysteresisLongOnlyV1Policy
from app.modules.simulator.application.predictions import (
    PredictionBundle,
    signals_for_date,
)
from app.modules.simulator.application.risk import RiskGuardrailsV0
from app.modules.simulator.config import (
    POLICY_HYSTERESIS_V1,
    POLICY_NAME,
    RISK_DD_GUARD_V1,
    SimulationSpecV0,
)


def resolve_portfolio_policy(spec: SimulationSpecV0) -> PortfolioPolicy:
    if spec.policy_name == POLICY_NAME:
        return RankLongOnlyV0Policy()
    if spec.policy_name == POLICY_HYSTERESIS_V1:
        return RankHysteresisLongOnlyV1Policy()
    raise ValueError(f"unsupported policy_name: {spec.policy_name}")


def resolve_risk_manager(spec: SimulationSpecV0) -> RiskManager:
    # Structural guardrails always apply; DD overlay is applied after in the engine.
    return RiskGuardrailsV0()


@dataclass(frozen=True, slots=True)
class SimulationResult:
    spec: SimulationSpecV0
    config_hash: str
    values_hash: str
    ledger: PortfolioLedger
    metrics: dict[str, Any]
    benchmark: dict[str, Any]
    benchmark_series: list[dict[str, Any]]
    provenance: dict[str, Any]


def _closes_for_day(market: MarketView, day: date, instrument_ids: set[int]) -> dict[int, float | None]:
    return {iid: market.close_price(iid, day) for iid in instrument_ids}


def _apply_corporate_actions(ledger: PortfolioLedger, market: MarketView, day: date) -> None:
    """Apply effective-date mechanical CA to held quantities before open fills.

    MOEX open on effective_date is already post-split; adjusting qty at day start
    keeps position value continuous into the open.
    """
    for iid, pos in list(ledger.positions.items()):
        for action in market.ca_on(iid, day):
            before_qty = pos.quantity
            after_qty = quantity_after_ca(before_qty, action.factor)
            ledger.set_position(iid, pos.ticker, after_qty)
            ledger.ca_events.append(
                {
                    "date": day.isoformat(),
                    "instrument_id": iid,
                    "ticker": pos.ticker,
                    "event_type": action.event_type,
                    "factor": str(action.factor),
                    "quantity_before": before_qty,
                    "quantity_after": after_qty,
                }
            )


def _execute_pending(
    ledger: PortfolioLedger,
    market: MarketView,
    day: date,
    *,
    commission_bps: float,
    slippage_bps: float,
    adapter: HistoricalNextOpenAdapter,
) -> None:
    due = [o for o in ledger.pending_intents if o.execution_date == day]
    if not due:
        return
    remaining = [o for o in ledger.pending_intents if o.execution_date != day]
    ledger.pending_intents = remaining

    sells = [o for o in due if o.side == "SELL"]
    buys = [o for o in due if o.side == "BUY"]

    def _apply_fill(intent: OrderIntent) -> None:
        raw_open = market.open_price(intent.instrument_id, day)
        working = intent
        fill = adapter.fill(
            working,
            raw_open=raw_open,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
        if fill is None:
            return
        if fill.side == "BUY":
            cost = fill.notional + fill.commission
            if cost > ledger.cash + 1e-6:
                if fill.fill_price <= 0 or ledger.cash <= 0:
                    return
                affordable_qty = ledger.cash / (
                    fill.fill_price * (1.0 + commission_bps / 10_000.0)
                )
                if affordable_qty <= 1e-12:
                    return
                working = OrderIntent(
                    decision_date=intent.decision_date,
                    execution_date=intent.execution_date,
                    instrument_id=intent.instrument_id,
                    ticker=intent.ticker,
                    side=intent.side,
                    target_weight=intent.target_weight,
                    target_notional=affordable_qty * fill.fill_price,
                    quantity=affordable_qty,
                    reason=intent.reason + "|cash_scaled",
                    prediction_date=intent.prediction_date,
                    predicted_return_20d=intent.predicted_return_20d,
                    rank=intent.rank,
                    policy_name=intent.policy_name,
                    fold_id=intent.fold_id,
                    metadata=dict(intent.metadata or {}),
                )
                fill = adapter.fill(
                    working,
                    raw_open=raw_open,
                    commission_bps=commission_bps,
                    slippage_bps=slippage_bps,
                )
                if fill is None:
                    return
                cost = fill.notional + fill.commission
            ledger.cash -= cost
            new_qty = ledger.position_qty(fill.instrument_id) + fill.quantity
            ledger.set_position(fill.instrument_id, fill.ticker, new_qty)
        else:
            ledger.cash += fill.notional - fill.commission
            new_qty = ledger.position_qty(fill.instrument_id) - fill.quantity
            ledger.set_position(fill.instrument_id, fill.ticker, new_qty)
        ledger.fills.append(fill)

    for intent in sells:
        _apply_fill(intent)
    for intent in buys:
        _apply_fill(intent)

    if abs(ledger.cash) < 1e-8:
        ledger.cash = 0.0
    if ledger.cash < -1e-6:
        raise RuntimeError(f"negative cash after execution on {day}: {ledger.cash}")


def _order_reason(
    *,
    spec: SimulationSpecV0,
    target_w: float,
    current_w: float,
    meta: dict[str, Any],
) -> str:
    """V0 keeps legacy policy-name reason; V1 uses explicit action labels."""
    if spec.policy_name == POLICY_NAME:
        return str(meta.get("policy") or spec.policy_name)
    if target_w <= 0:
        return "EXIT_BELOW_TOP35"
    action = str(meta.get("action") or "")
    if current_w <= 1e-12:
        return action or "ENTER_TOP20"
    if abs(target_w - current_w) >= float(spec.min_trade_weight_delta) - 1e-15:
        # Material weight change while staying selected
        if action == "HOLD_WITHIN_EXIT_BAND":
            return "REBALANCE_WEIGHT_DELTA"
        if action == "ENTER_TOP20":
            return "ENTER_TOP20"
    return action or "REBALANCE_WEIGHT_DELTA"


def _build_rebalance_intents(
    *,
    ledger: PortfolioLedger,
    market: MarketView,
    decision_date: date,
    execution_date: date,
    bundle: PredictionBundle,
    spec: SimulationSpecV0,
    policy: PortfolioPolicy,
    risk: RiskManager,
    exposure_cap: float = 1.0,
) -> list[OrderIntent]:
    signals = signals_for_date(bundle, decision_date, ticker_by_id=market.tickers)
    if not signals:
        return []

    constraints: dict[str, Any] = {
        "top_quantile": spec.top_quantile,
        "entry_quantile": spec.entry_quantile,
        "exit_quantile": spec.exit_quantile,
        "held_instrument_ids": tuple(sorted(ledger.positions.keys())),
    }
    policy_out = policy.decide(
        PortfolioPolicyInput(
            as_of=datetime.combine(decision_date, datetime.min.time()),
            account_id="simulator-v0",
            prediction_signals=tuple(signals),
            constraints=constraints,
        )
    )
    risk_out = risk.apply(
        policy_out.decisions,
        constraints={
            "max_single_weight": spec.max_single_weight,
            "max_gross_exposure": spec.max_gross_exposure,
            "long_only": spec.long_only,
        },
    )
    if spec.risk_name == RISK_DD_GUARD_V1 and exposure_cap < 1.0 - 1e-12:
        risk_out = apply_exposure_cap(
            risk_out.decisions,
            exposure_cap=exposure_cap,
            max_single_weight=spec.max_single_weight,
        )

    closes = {
        iid: market.close_price(iid, decision_date)
        for iid in set(market.tickers) | set(ledger.positions)
    }
    nav = ledger.nav(closes)
    if nav <= 0:
        return []

    targets: dict[int, tuple[str, float, dict[str, Any]]] = {}
    for d in risk_out.decisions:
        if d.blocked or d.target_weight <= 0:
            continue
        iid = int((d.metadata or {}).get("instrument_id"))
        ticker = d.ticker
        # Skip names without valid close today (cannot size) or without next open later
        if market.close_price(iid, decision_date) is None:
            continue
        if market.open_price(iid, execution_date) is None:
            continue
        targets[iid] = (ticker, float(d.target_weight), dict(d.metadata or {}))

    # Flat all non-target holdings to zero
    current_ids = set(ledger.positions.keys()) | set(targets.keys())
    intents: list[OrderIntent] = []
    min_w_delta = float(spec.min_trade_weight_delta or 0.0)
    for iid in sorted(current_ids):
        ticker = market.tickers.get(iid) or (
            ledger.positions[iid].ticker if iid in ledger.positions else str(iid)
        )
        target_w, meta = 0.0, {}
        if iid in targets:
            ticker, target_w, meta = targets[iid]
        px_close = market.close_price(iid, decision_date)
        if px_close is None or px_close <= 0:
            # Cannot size; if we hold, attempt exit using execution open only via qty
            current_qty = ledger.position_qty(iid)
            if current_qty > 0 and iid not in targets:
                intents.append(
                    OrderIntent(
                        decision_date=decision_date,
                        execution_date=execution_date,
                        instrument_id=iid,
                        ticker=ticker,
                        side="SELL",
                        target_weight=0.0,
                        target_notional=0.0,
                        quantity=current_qty,
                        reason="exit_missing_mark",
                        policy_name=spec.policy_name,
                        metadata={"instrument_id": iid},
                    )
                )
            continue

        target_value = nav * target_w
        current_qty = ledger.position_qty(iid)
        current_value = current_qty * px_close
        current_w = (current_value / nav) if nav > 0 else 0.0
        delta_value = target_value - current_value
        # Skip economically tiny deltas (< 1 RUB)
        if abs(delta_value) < 1.0:
            continue
        # V1 anti-churn: skip tiny target-weight rebalances (2pp default)
        if min_w_delta > 0 and abs(target_w - current_w) < min_w_delta - 1e-15:
            continue
        exec_open = market.open_price(iid, execution_date)
        if exec_open is None or exec_open <= 0:
            continue
        # Size quantity using decision close for targeting; fill uses next open
        qty = abs(delta_value) / px_close
        if not spec.fractional_shares:
            qty = float(int(qty))
            if qty <= 0:
                continue
        side = "BUY" if delta_value > 0 else "SELL"
        if side == "SELL":
            qty = min(qty, current_qty)
            if qty <= 0:
                continue
        reason = _order_reason(
            spec=spec, target_w=target_w, current_w=current_w, meta=meta
        )
        if spec.risk_name == RISK_DD_GUARD_V1 and meta.get("dd_guard_scaled"):
            meta = {**meta, "risk_reason": "DD_GUARD_REDUCE"}
        intents.append(
            OrderIntent(
                decision_date=decision_date,
                execution_date=execution_date,
                instrument_id=iid,
                ticker=ticker,
                side=side,
                target_weight=target_w,
                target_notional=abs(delta_value),
                quantity=qty,
                reason=reason,
                prediction_date=date.fromisoformat(meta["prediction_date"])
                if meta.get("prediction_date")
                else decision_date,
                predicted_return_20d=float(meta["predicted_return_20d"])
                if meta.get("predicted_return_20d") is not None
                else None,
                rank=int(meta["rank"]) if meta.get("rank") is not None else None,
                policy_name=spec.policy_name,
                fold_id=str(meta["fold_id"]) if meta.get("fold_id") is not None else None,
                metadata=meta,
            )
        )
    return intents


def simulation_values_hash(ledger: PortfolioLedger) -> str:
    rows = []
    for snap in ledger.snapshots:
        rows.append(
            f"{snap.as_of.isoformat()},{snap.nav:.10f},{snap.cash:.10f},{snap.gross_exposure:.10f}"
        )
    for fill in ledger.fills:
        rows.append(
            f"F,{fill.execution_date.isoformat()},{fill.instrument_id},{fill.side},"
            f"{fill.quantity:.10f},{fill.fill_price:.10f},{fill.commission:.10f}"
        )
    payload = "\n".join(rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_simulation(
    *,
    spec: SimulationSpecV0,
    bundle: PredictionBundle,
    market: MarketView,
    date_from: date | None = None,
    date_to: date | None = None,
) -> SimulationResult:
    """Run deterministic chronological simulation on OOS predictions only."""
    if bundle.segment != spec.segment:
        raise ValueError("spec.segment must match prediction bundle segment")

    pred_dates = sorted(set(bundle.frame["as_of_date"].tolist()))
    if not pred_dates:
        raise ValueError("no prediction dates")

    # Simulation window: from first prediction date through last trading day needed
    # for next-open execution after last prediction.
    first_pred = date_from or pred_dates[0]
    last_pred = date_to or pred_dates[-1]
    trading_days = [d for d in market.trading_days if first_pred <= d]
    # Extend one session beyond last prediction for final fills/marks when possible
    after_last = next_trading_day(market.trading_days, last_pred)
    end = last_pred
    if after_last is not None:
        end = after_last
    if date_to is not None:
        end = min(end, date_to)
    trading_days = [d for d in trading_days if d <= end]
    if not trading_days:
        raise ValueError("no trading days in simulation window")

    rebalance_set = set(weekly_rebalance_dates(trading_days))
    # Only rebalance when we have predictions for that exact day
    pred_set = set(pred_dates)

    policy = resolve_portfolio_policy(spec)
    risk = resolve_risk_manager(spec)
    adapter = HistoricalNextOpenAdapter()
    ledger = PortfolioLedger(cash=float(spec.initial_capital), peak_nav=float(spec.initial_capital))
    dd_guard = DrawdownGuardState(
        mode="normal",
        exposure_cap=float(spec.dd_normal_gross if spec.risk_name == RISK_DD_GUARD_V1 else 1.0),
    )

    for day in trading_days:
        _apply_corporate_actions(ledger, market, day)
        _execute_pending(
            ledger,
            market,
            day,
            commission_bps=spec.commission_bps,
            slippage_bps=spec.slippage_bps,
            adapter=adapter,
        )
        held_ids = set(ledger.positions.keys())
        # Also mark instruments we may trade later — closes for held only
        closes = _closes_for_day(market, day, held_ids)
        snap = ledger.record_snapshot(day, closes)

        if spec.risk_name == RISK_DD_GUARD_V1:
            prev_events = len(dd_guard.events or [])
            dd_guard = update_drawdown_guard(
                dd_guard,
                as_of=day,
                nav=snap.nav,
                peak_nav=snap.peak_nav,
                drawdown=snap.drawdown,
                trigger=spec.dd_trigger,
                recovery=spec.dd_recovery,
                risk_off_gross=spec.dd_risk_off_gross,
                normal_gross=spec.dd_normal_gross,
            )
            ledger.risk_mode = dd_guard.mode
            ledger.exposure_cap = dd_guard.exposure_cap
            if dd_guard.events and len(dd_guard.events) > prev_events:
                ledger.risk_events.extend(dd_guard.events[prev_events:])

        if day in rebalance_set and day in pred_set and day <= last_pred:
            exec_day = next_trading_day(trading_days, day)
            if exec_day is None:
                continue
            intents = _build_rebalance_intents(
                ledger=ledger,
                market=market,
                decision_date=day,
                execution_date=exec_day,
                bundle=bundle,
                spec=spec,
                policy=policy,
                risk=risk,
                exposure_cap=ledger.exposure_cap
                if spec.risk_name == RISK_DD_GUARD_V1
                else 1.0,
            )
            if intents:
                ledger.rebalance_count += 1
                ledger.orders.extend(intents)
                ledger.pending_intents.extend(intents)

    metrics = compute_metrics(ledger, initial_capital=spec.initial_capital)
    metrics["annual_slices"] = annual_nav_slices(ledger)
    start_snap = ledger.snapshots[0].as_of if ledger.snapshots else first_pred
    end_snap = ledger.snapshots[-1].as_of if ledger.snapshots else end
    bench_series = imoex_price_series(market, start=start_snap, end=end_snap)
    benchmark = imoex_price_return(bench_series)
    if (
        metrics.get("total_price_return") is not None
        and benchmark.get("total_price_return") is not None
    ):
        metrics["excess_vs_imoex"] = float(metrics["total_price_return"]) - float(
            benchmark["total_price_return"]
        )
    if start_snap and end_snap and market.cbr_hurdle_quotes:
        cbr_return = piecewise_calendar_accrual(
            start_snap, end_snap, market.cbr_hurdle_quotes
        )
        cbr_metrics = benchmark_metrics(
            strategy_return=float(metrics.get("total_price_return") or 0),
            hurdle_return=cbr_return,
            periods=max(1, len(ledger.snapshots)),
            costs=float(metrics.get("total_costs") or 0) / spec.initial_capital,
        )
        metrics["hurdle_return"] = cbr_metrics.hurdle_return
        metrics["excess_vs_cbr"] = cbr_metrics.excess_return
        metrics["cbr_hurdle_verdict"] = cbr_metrics.verdict.value

    values_hash = simulation_values_hash(ledger)
    metrics["simulation_values_hash"] = values_hash
    provenance = {
        "segment": spec.segment,
        "candidate_config_hash": bundle.candidate_config_hash,
        "dataset_values_hash": bundle.dataset_values_hash,
        "prediction_hash": bundle.prediction_hash,
        "artifact_dir": str(bundle.artifact_dir),
        "survivorship_disclaimer": spec.survivorship_disclaimer,
        "dividends": "excluded_unavailable",
        "execution_timing": spec.execution_timing,
        "policy_name": spec.policy_name,
        "risk_name": spec.risk_name,
        "rebalance_rule": (
            "first available trading observation of each ISO calendar week; "
            "decision after information at date t; fill at next trading day OPEN"
        ),
        "oos_only": True,
        "fold_aware": bundle.fold_aware,
    }
    if spec.policy_name == POLICY_HYSTERESIS_V1:
        provenance["policy_v1"] = {
            "entry_quantile": spec.entry_quantile,
            "exit_quantile": spec.exit_quantile,
            "min_trade_weight_delta": spec.min_trade_weight_delta,
            "weighting": "equal",
        }
    if spec.risk_name == RISK_DD_GUARD_V1:
        provenance["risk_v1"] = {
            "trigger": spec.dd_trigger,
            "recovery": spec.dd_recovery,
            "risk_off_gross": spec.dd_risk_off_gross,
            "normal_gross": spec.dd_normal_gross,
        }
    return SimulationResult(
        spec=spec,
        config_hash=spec.config_hash(),
        values_hash=values_hash,
        ledger=ledger,
        metrics=metrics,
        benchmark=benchmark,
        benchmark_series=bench_series,
        provenance=provenance,
    )


def result_summary(result: SimulationResult) -> dict[str, Any]:
    snaps = result.ledger.snapshots
    return {
        "config_hash": result.config_hash,
        "values_hash": result.values_hash,
        "spec": result.spec.to_dict(),
        "provenance": result.provenance,
        "metrics": result.metrics,
        "benchmark": result.benchmark,
        "period": {
            "start": snaps[0].as_of.isoformat() if snaps else None,
            "end": snaps[-1].as_of.isoformat() if snaps else None,
            "trading_days": len(snaps),
            "rebalances": result.ledger.rebalance_count,
            "trades": len(result.ledger.fills),
            "orders": len(result.ledger.orders),
        },
        "nav_head": [
            {"date": s.as_of.isoformat(), "nav": s.nav, "cash": s.cash, "drawdown": s.drawdown}
            for s in snaps[:3]
        ],
        "nav_tail": [
            {"date": s.as_of.isoformat(), "nav": s.nav, "cash": s.cash, "drawdown": s.drawdown}
            for s in snaps[-3:]
        ],
    }


def dump_result_json(result: SimulationResult) -> str:
    return json.dumps(result_summary(result), ensure_ascii=False, indent=2, default=str)
