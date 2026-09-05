"""Shadow Portfolio V0 — initialize and advance forward experiments."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ports.execution import OrderIntent
from app.domain.ports.portfolio import PortfolioPolicyInput, PredictionSignal
from app.infrastructure.market.models import Candle
from app.modules.market.application.mechanical_adjustment import load_mechanical_actions
from app.modules.prediction.infrastructure.forward_models import (
    ForwardPrediction,
    ForwardPredictionBatch,
)
from app.modules.shadow.application.execution_eligibility import (
    ensure_aware_utc,
    is_execution_date_eligible,
    iso_week_key,
    min_execution_market_date,
)
from app.modules.shadow.config import (
    EXPERIMENT_GROUP,
    SHADOW_KIND,
    ShadowSpecConfig,
    operational_shadow_configs,
)
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowFill,
    ShadowNavDaily,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
    ShadowRiskEvent,
)
from app.modules.simulator.application.drawdown_guard import (
    DrawdownGuardState,
    apply_exposure_cap,
    update_drawdown_guard,
)
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter
from app.modules.simulator.application.market_view import quantity_after_ca
from app.modules.simulator.application.policy_hysteresis import RankHysteresisLongOnlyV1Policy
from app.modules.simulator.application.risk import RiskGuardrailsV0
from app.modules.simulator.config import RISK_DD_GUARD_V1

Clock = Callable[[], datetime]

LATE_INPUT_CODE = "HISTORICAL_INPUT_CHANGED_AFTER_SHADOW_PROCESSING"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AdvanceResult:
    portfolio_id: int
    name: str
    status: str
    summary: dict[str, Any]


def append_shadow_warning(portfolio: ShadowPortfolio, code: str, detail: str) -> None:
    """Append a diagnostic warning without rewriting historical rows."""
    warnings = list(portfolio.warnings or [])
    if any(isinstance(w, dict) and w.get("code") == code and w.get("detail") == detail for w in warnings):
        return
    warnings.append({"code": code, "detail": detail})
    portfolio.warnings = warnings


def open_changed_after_fill(*, recorded_raw_open: float, current_raw_open: float | None) -> bool:
    if current_raw_open is None:
        return False
    return abs(float(current_raw_open) - float(recorded_raw_open)) > 1e-9


def _positions_dict(portfolio: ShadowPortfolio) -> dict[str, dict[str, Any]]:
    raw = portfolio.positions or {}
    return {str(k): dict(v) for k, v in raw.items()}


def _set_position(portfolio: ShadowPortfolio, instrument_id: int, ticker: str, qty: float) -> None:
    pos = _positions_dict(portfolio)
    key = str(instrument_id)
    if abs(qty) < 1e-12:
        pos.pop(key, None)
    else:
        pos[key] = {"instrument_id": instrument_id, "ticker": ticker, "quantity": float(qty)}
    portfolio.positions = pos


def _position_qty(portfolio: ShadowPortfolio, instrument_id: int) -> float:
    row = _positions_dict(portfolio).get(str(instrument_id))
    return float(row["quantity"]) if row else 0.0


def _held_ids(portfolio: ShadowPortfolio) -> set[int]:
    return {int(k) for k, v in _positions_dict(portfolio).items() if abs(float(v.get("quantity") or 0)) > 1e-12}


def upsert_spec(session: Session, cfg: ShadowSpecConfig) -> ShadowPortfolioSpec:
    existing = session.scalar(select(ShadowPortfolioSpec).where(ShadowPortfolioSpec.name == cfg.name))
    if existing is not None:
        return existing
    row = ShadowPortfolioSpec(
        experiment_group=cfg.experiment_group,
        name=cfg.name,
        version=cfg.version,
        config_hash=cfg.config_hash(),
        candidate_name=cfg.candidate_name,
        candidate_version=cfg.candidate_version,
        candidate_config_hash=cfg.candidate_config_hash,
        dataset_values_hash=cfg.dataset_values_hash,
        policy_name=cfg.policy_name,
        risk_name=cfg.risk_name,
        entry_quantile=cfg.entry_quantile,
        exit_quantile=cfg.exit_quantile,
        min_trade_weight_delta=cfg.min_trade_weight_delta,
        max_single_weight=cfg.max_single_weight,
        dd_trigger=cfg.dd_trigger,
        dd_recovery=cfg.dd_recovery,
        dd_risk_off_gross=cfg.dd_risk_off_gross,
        dd_normal_gross=cfg.dd_normal_gross,
        initial_capital=cfg.initial_capital,
        commission_bps=cfg.commission_bps,
        slippage_bps=cfg.slippage_bps,
        fractional_shares=cfg.fractional_shares,
        dividend_cash=cfg.dividend_cash,
        payload={"kind": SHADOW_KIND, **cfg.to_dict()},
    )
    session.add(row)
    session.flush()
    return row


def _latest_success_batch(
    session: Session, *, candidate_config_hash: str | None = None
) -> ForwardPredictionBatch | None:
    """Latest SUCCESS Forward batch, optionally restricted to one Prediction Candidate.

    Restricting by candidate is what keeps parallel candidates from cross-feeding each
    other's Shadow portfolios.
    """
    q = select(ForwardPredictionBatch).where(ForwardPredictionBatch.status == "SUCCESS")
    if candidate_config_hash is not None:
        q = q.where(ForwardPredictionBatch.candidate_config_hash == candidate_config_hash)
    return session.scalar(
        q.order_by(
            ForwardPredictionBatch.as_of_date.desc(), ForwardPredictionBatch.id.desc()
        ).limit(1)
    )


def _batch_predictions(session: Session, batch_id: int) -> list[ForwardPrediction]:
    return list(
        session.scalars(
            select(ForwardPrediction)
            .where(ForwardPrediction.batch_id == batch_id)
            .order_by(ForwardPrediction.rank.nulls_last(), ForwardPrediction.instrument_id)
        )
    )


def _candle_open_close(session: Session, instrument_id: int, day: date) -> tuple[float | None, float | None]:
    row = session.scalar(
        select(Candle).where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == "1d",
            func.date(Candle.timestamp) == day,
        )
    )
    if row is None:
        return None, None
    return float(row.open), float(row.close)


def _trading_days_after(session: Session, after: date | None) -> list[date]:
    q = select(func.date(Candle.timestamp)).where(Candle.timeframe == "1d").distinct()
    if after is not None:
        q = q.where(func.date(Candle.timestamp) > after)
    days = sorted({d if isinstance(d, date) else date.fromisoformat(str(d)) for d in session.scalars(q)})
    return days


def _apply_ca_for_day(session: Session, portfolio: ShadowPortfolio, day: date) -> None:
    for _key, pos in list(_positions_dict(portfolio).items()):
        iid = int(pos["instrument_id"])
        qty = float(pos["quantity"])
        ticker = str(pos["ticker"])
        for action in load_mechanical_actions(session, iid):
            if action.event_date != day:
                continue
            if action.event_type not in ("SPLIT", "REVERSE_SPLIT"):
                continue
            qty = quantity_after_ca(qty, action.factor)
        _set_position(portfolio, iid, ticker, qty)


def _mark_nav(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    day: date,
    *,
    now: datetime,
) -> dict[str, Any]:
    mv = 0.0
    pos_count = 0
    for pos in _positions_dict(portfolio).values():
        iid = int(pos["instrument_id"])
        qty = float(pos["quantity"])
        _o, close = _candle_open_close(session, iid, day)
        if close is None:
            continue
        mv += qty * close
        pos_count += 1
    nav = float(portfolio.cash) + mv
    if portfolio.peak_nav <= 0:
        portfolio.peak_nav = nav
    portfolio.peak_nav = max(float(portfolio.peak_nav), nav)
    dd = (nav / portfolio.peak_nav) - 1.0 if portfolio.peak_nav > 0 else 0.0
    gross = (mv / nav) if nav > 0 else 0.0

    # DD guard update for portfolio B only (uses own NAV history)
    if spec.risk_name == RISK_DD_GUARD_V1:
        state = DrawdownGuardState(mode=portfolio.risk_mode, exposure_cap=float(portfolio.exposure_cap), events=[])
        new_state = update_drawdown_guard(
            state,
            as_of=day,
            nav=nav,
            peak_nav=float(portfolio.peak_nav),
            drawdown=dd,
            trigger=float(spec.dd_trigger or -0.20),
            recovery=float(spec.dd_recovery or -0.10),
            risk_off_gross=float(spec.dd_risk_off_gross or 0.50),
            normal_gross=float(spec.dd_normal_gross or 1.0),
        )
        if new_state.events:
            for ev in new_state.events:
                session.add(
                    ShadowRiskEvent(
                        portfolio_id=portfolio.id,
                        as_of_date=day,
                        nav=float(ev["nav"]),
                        running_peak=float(ev["running_peak"]),
                        drawdown=float(ev["drawdown"]),
                        previous_mode=str(ev["previous_mode"]),
                        new_mode=str(ev["new_mode"]),
                        previous_exposure_cap=float(ev["previous_exposure_cap"]),
                        new_exposure_cap=float(ev["new_exposure_cap"]),
                        reason=str(ev["reason"]),
                    )
                )
            portfolio.risk_mode = new_state.mode
            portfolio.exposure_cap = float(new_state.exposure_cap)

    existing = session.scalar(
        select(ShadowNavDaily).where(
            ShadowNavDaily.portfolio_id == portfolio.id,
            ShadowNavDaily.as_of_date == day,
        )
    )
    if existing is None:
        session.add(
            ShadowNavDaily(
                portfolio_id=portfolio.id,
                as_of_date=day,
                cash=float(portfolio.cash),
                market_value=mv,
                nav=nav,
                gross_exposure=gross,
                drawdown=dd,
                peak_nav=float(portfolio.peak_nav),
                position_count=pos_count,
            )
        )
    portfolio.last_processed_market_date = day
    portfolio.updated_at = now
    return {"nav": nav, "cash": portfolio.cash, "market_value": mv, "drawdown": dd, "gross": gross}


def _build_decision_and_orders(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    batch: ForwardPredictionBatch,
    preds: list[ForwardPrediction],
    *,
    decision_at: datetime,
) -> ShadowDecision | None:
    week = iso_week_key(batch.as_of_date)
    existing = session.scalar(
        select(ShadowDecision).where(
            ShadowDecision.portfolio_id == portfolio.id,
            ShadowDecision.iso_week == week,
        )
    )
    if existing is not None:
        return None  # one rebalance per ISO week

    signals = [
        PredictionSignal(
            instrument_id=int(p.instrument_id),
            ticker=p.ticker,
            as_of_date=p.as_of_date,
            predicted_return_20d=float(p.predicted_return_20d),
        )
        for p in preds
        if p.quality_status == "OK"
    ]
    policy = RankHysteresisLongOnlyV1Policy()
    policy_out = policy.decide(
        PortfolioPolicyInput(
            as_of=decision_at,
            account_id=f"shadow-{portfolio.id}",
            prediction_signals=tuple(signals),
            constraints={
                "entry_quantile": float(spec.entry_quantile),
                "exit_quantile": float(spec.exit_quantile),
                "held_instrument_ids": tuple(sorted(_held_ids(portfolio))),
            },
        )
    )
    risk = RiskGuardrailsV0()
    risk_out = risk.apply(
        policy_out.decisions,
        constraints={
            "max_single_weight": float(spec.max_single_weight),
            "max_gross_exposure": 1.0,
            "long_only": True,
        },
    )
    exposure_cap = float(portfolio.exposure_cap)
    if spec.risk_name == RISK_DD_GUARD_V1 and exposure_cap < 1.0 - 1e-12:
        risk_out = apply_exposure_cap(
            risk_out.decisions,
            exposure_cap=exposure_cap,
            max_single_weight=float(spec.max_single_weight),
        )

    # Size against current NAV estimate using latest known closes if any; else cash-only
    closes: dict[int, float] = {}
    for pos in _positions_dict(portfolio).values():
        iid = int(pos["instrument_id"])
        # prefer latest processed close; fallback none
        if portfolio.last_processed_market_date is not None:
            _o, c = _candle_open_close(session, iid, portfolio.last_processed_market_date)
            if c is not None:
                closes[iid] = c
    mv = sum(_position_qty(portfolio, iid) * px for iid, px in closes.items())
    nav = float(portfolio.cash) + mv
    if nav <= 0:
        nav = float(spec.initial_capital)

    targets: list[dict[str, Any]] = []
    for d in risk_out.decisions:
        if d.blocked or d.target_weight <= 0:
            continue
        meta = dict(d.metadata or {})
        iid = int(meta.get("instrument_id"))
        targets.append(
            {
                "instrument_id": iid,
                "ticker": d.ticker,
                "target_weight": float(d.target_weight),
                "action": meta.get("action"),
                "rank": meta.get("rank"),
                "predicted_return_20d": meta.get("predicted_return_20d"),
                "policy": meta.get("policy") or spec.policy_name,
            }
        )

    decision = ShadowDecision(
        portfolio_id=portfolio.id,
        forward_batch_id=batch.id,
        signal_as_of_date=batch.as_of_date,
        signal_generated_at=ensure_aware_utc(batch.generated_at or decision_at),
        decision_at=decision_at,
        iso_week=week,
        policy_name=spec.policy_name,
        risk_name=spec.risk_name,
        risk_mode=portfolio.risk_mode,
        exposure_cap=exposure_cap,
        targets=targets,
        metadata_={
            "eligible_n": policy_out.metadata.get("eligible_n"),
            "selected_k": policy_out.metadata.get("selected_k"),
            "k_entry": policy_out.metadata.get("k_entry"),
            "k_max": policy_out.metadata.get("k_max"),
            "prediction_hash": batch.prediction_hash,
            "kind": SHADOW_KIND,
        },
    )
    session.add(decision)
    session.flush()

    # Build orders for target set + exits of held non-targets
    target_by_id = {int(t["instrument_id"]): t for t in targets}
    all_ids = set(target_by_id) | _held_ids(portfolio)
    min_delta = float(spec.min_trade_weight_delta)
    min_exec = min_execution_market_date(decision_at)
    eligible_count = int(policy_out.metadata.get("eligible_n") or len(signals))

    for iid in sorted(all_ids):
        ticker = (
            target_by_id[iid]["ticker"]
            if iid in target_by_id
            else str(_positions_dict(portfolio).get(str(iid), {}).get("ticker") or iid)
        )
        target_w = float(target_by_id[iid]["target_weight"]) if iid in target_by_id else 0.0
        # Prefer mark using signal as_of close for sizing (known at decision); if missing, use cash NAV only
        px = None
        o, c = _candle_open_close(session, iid, batch.as_of_date)
        px = c or o
        current_qty = _position_qty(portfolio, iid)
        current_value = current_qty * px if px and px > 0 else 0.0
        current_w = (current_value / nav) if nav > 0 else 0.0
        target_value = nav * target_w
        delta_value = target_value - current_value
        if abs(delta_value) < 1.0:
            continue
        if min_delta > 0 and abs(target_w - current_w) < min_delta - 1e-15:
            # suppress tiny rebalance
            continue
        if px is None or px <= 0:
            # cannot size; if exit needed, leave for later when price arrives? For V0 skip
            if target_w <= 0 and current_qty > 0:
                qty = current_qty
                side = "SELL"
            else:
                continue
        else:
            qty = abs(delta_value) / px
            if not spec.fractional_shares:
                qty = float(int(qty))
                if qty <= 0:
                    continue
            side = "BUY" if delta_value > 0 else "SELL"
            if side == "SELL":
                qty = min(qty, current_qty)
                if qty <= 0:
                    continue

        action = (target_by_id.get(iid) or {}).get("action")
        if target_w <= 0:
            reason = "EXIT_BELOW_TOP35"
        elif current_qty <= 1e-12:
            reason = str(action or "ENTER_TOP20")
        elif abs(target_w - current_w) >= min_delta:
            reason = "REBALANCE_WEIGHT_DELTA" if action == "HOLD_WITHIN_EXIT_BAND" else str(action or "ENTER_TOP20")
        else:
            reason = "BELOW_MIN_WEIGHT_DELTA"

        if reason == "BELOW_MIN_WEIGHT_DELTA":
            continue

        session.add(
            ShadowOrder(
                portfolio_id=portfolio.id,
                decision_id=decision.id,
                instrument_id=iid,
                ticker=ticker,
                side=side,
                target_weight=target_w,
                target_notional=abs(delta_value),
                quantity=float(qty),
                reason=reason,
                status="PENDING",
                predicted_return_20d=(target_by_id.get(iid) or {}).get("predicted_return_20d"),
                rank=(target_by_id.get(iid) or {}).get("rank"),
                eligible_count=eligible_count,
                decision_at=decision_at,
                min_execution_date=min_exec,
                metadata_={
                    "forward_batch_id": batch.id,
                    "signal_as_of": batch.as_of_date.isoformat(),
                    "signal_generated_at": ensure_aware_utc(batch.generated_at or decision_at).isoformat(),
                    "policy": spec.policy_name,
                    "risk_mode": portfolio.risk_mode,
                    "kind": SHADOW_KIND,
                },
            )
        )

    session.flush()
    portfolio.last_decision_iso_week = week
    portfolio.last_decision_id = decision.id
    portfolio.last_processed_prediction_batch_id = batch.id
    return decision


def _scan_late_input_corrections(session: Session, portfolio: ShadowPortfolio) -> int:
    """Warn if RAW OPEN for an already-filled order later diverges; never rewrite fills."""
    fills = list(
        session.scalars(select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id))
    )
    n = 0
    for fill in fills:
        current_open, _ = _candle_open_close(session, int(fill.instrument_id), fill.execution_date)
        if open_changed_after_fill(recorded_raw_open=float(fill.raw_open), current_raw_open=current_open):
            append_shadow_warning(
                portfolio,
                LATE_INPUT_CODE,
                f"fill_id={fill.id} instrument_id={fill.instrument_id} "
                f"execution_date={fill.execution_date.isoformat()} "
                f"recorded_open={fill.raw_open} current_open={current_open}",
            )
            n += 1
    return n


def _fill_pending_orders(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    market_date: date,
    *,
    now: datetime,
) -> int:
    pending = list(
        session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio.id,
                ShadowOrder.status == "PENDING",
            )
        )
    )
    adapter = HistoricalNextOpenAdapter()
    filled = 0
    # Sells first
    ordered = sorted(pending, key=lambda o: 0 if o.side == "SELL" else 1)
    for order in ordered:
        if not is_execution_date_eligible(decision_at=order.decision_at, market_date=market_date):
            continue
        if market_date < order.min_execution_date:
            continue
        raw_open, _close = _candle_open_close(session, int(order.instrument_id), market_date)
        if raw_open is None or raw_open <= 0:
            continue
        intent = OrderIntent(
            decision_date=order.decision_at.date(),
            execution_date=market_date,
            instrument_id=int(order.instrument_id),
            ticker=order.ticker,
            side=order.side,  # type: ignore[arg-type]
            target_weight=float(order.target_weight),
            target_notional=float(order.target_notional),
            quantity=float(order.quantity),
            reason=order.reason,
        )
        fill = adapter.fill(
            intent,
            raw_open=raw_open,
            commission_bps=float(spec.commission_bps),
            slippage_bps=float(spec.slippage_bps),
        )
        if fill is None:
            continue
        # Apply cash / positions
        if order.side == "BUY":
            cost = fill.notional + fill.commission
            if cost > float(portfolio.cash) + 1e-6:
                # insufficient cash — skip fill, leave pending
                continue
            portfolio.cash = float(portfolio.cash) - cost
            new_qty = _position_qty(portfolio, int(order.instrument_id)) + fill.quantity
            _set_position(portfolio, int(order.instrument_id), order.ticker, new_qty)
        else:
            sell_qty = min(fill.quantity, _position_qty(portfolio, int(order.instrument_id)))
            if sell_qty <= 0:
                order.status = "CANCELLED"
                order.updated_at = now
                continue
            proceeds = sell_qty * fill.fill_price - fill.commission
            portfolio.cash = float(portfolio.cash) + proceeds
            new_qty = _position_qty(portfolio, int(order.instrument_id)) - sell_qty
            _set_position(portfolio, int(order.instrument_id), order.ticker, new_qty)
            fill = fill.__class__(
                **{
                    **fill.__dict__,
                    "quantity": sell_qty,
                    "notional": sell_qty * fill.fill_price,
                }
            )

        # Immutable fill row
        existing_fill = session.scalar(select(ShadowFill).where(ShadowFill.order_id == order.id))
        if existing_fill is not None:
            continue
        session.add(
            ShadowFill(
                portfolio_id=portfolio.id,
                order_id=order.id,
                instrument_id=int(order.instrument_id),
                ticker=order.ticker,
                side=order.side,
                quantity=float(fill.quantity),
                raw_open=float(fill.raw_open),
                fill_price=float(fill.fill_price),
                notional=float(fill.notional),
                commission=float(fill.commission),
                slippage_cost=float(fill.slippage_cost),
                execution_date=market_date,
                decision_at=order.decision_at,
                filled_at=now,
                metadata_={"kind": SHADOW_KIND, "raw_open_source": "market.candles"},
            )
        )
        order.status = "FILLED"
        order.execution_date = market_date
        order.updated_at = now
        filled += 1
    return filled


def initialize_empty_shadow_portfolios(
    session: Session,
    *,
    configs: Sequence[ShadowSpecConfig],
    clock: Clock | None = None,
) -> list[AdvanceResult]:
    """Create cash-only Shadow portfolios with no orders/fills/decisions.

    Used for prospective Model A/B activation: portfolios must start at initial capital
    with empty history. Decisions appear only after a genuinely new post-activation
    Forward batch for that candidate.
    """
    now = (clock or _utcnow)()
    results: list[AdvanceResult] = []
    for cfg in configs:
        spec = upsert_spec(session, cfg)
        portfolio = session.scalar(
            select(ShadowPortfolio).where(ShadowPortfolio.spec_id == spec.id)
        )
        if portfolio is None:
            portfolio = ShadowPortfolio(
                spec_id=spec.id,
                status="WAITING_FOR_NEW_MARKET",
                activated_at=now,
                first_forward_batch_id=None,
                first_forward_as_of_date=None,
                cash=float(spec.initial_capital),
                peak_nav=float(spec.initial_capital),
                exposure_cap=float(spec.dd_normal_gross or 1.0),
                risk_mode="normal",
                positions={},
                provenance={
                    "kind": SHADOW_KIND,
                    "experiment_group": cfg.experiment_group,
                    "candidate_config_hash": cfg.candidate_config_hash,
                    "not_historical_simulator": True,
                    "empty_activation": True,
                    "historical_backfill": False,
                },
                warnings=[],
            )
            session.add(portfolio)
            session.flush()
        results.append(
            AdvanceResult(
                portfolio_id=portfolio.id,
                name=spec.name,
                status=portfolio.status,
                summary={
                    "cash": float(portfolio.cash),
                    "positions": 0,
                    "orders": 0,
                    "fills": 0,
                    "empty_activation": True,
                },
            )
        )
    return results


def initialize_shadow_portfolios(
    session: Session,
    *,
    clock: Clock | None = None,
    first_batch_id: int | None = None,
    configs: Sequence[ShadowSpecConfig] | None = None,
) -> list[AdvanceResult]:
    """Create the given Shadow portfolios and first decisions when a Forward batch exists.

    Defaults to the operational SHADOW_FORWARD_V0 pair. Each spec consumes only Forward
    batches produced by its own bound Prediction Candidate.
    """
    now = (clock or _utcnow)()
    specs = list(configs) if configs is not None else list(operational_shadow_configs())

    results: list[AdvanceResult] = []
    for cfg in specs:
        batch = None
        if first_batch_id is not None:
            batch = session.get(ForwardPredictionBatch, first_batch_id)
            if batch is not None and batch.candidate_config_hash != cfg.candidate_config_hash:
                batch = None
        if batch is None:
            batch = _latest_success_batch(
                session, candidate_config_hash=cfg.candidate_config_hash
            )
        if batch is None or batch.status != "SUCCESS" or batch.generated_at is None:
            raise ValueError(
                f"no SUCCESS forward batch for candidate {cfg.candidate_name}/"
                f"{cfg.candidate_version} — cannot activate {cfg.name}"
            )

        spec = upsert_spec(session, cfg)
        portfolio = session.scalar(select(ShadowPortfolio).where(ShadowPortfolio.spec_id == spec.id))
        if portfolio is None:
            portfolio = ShadowPortfolio(
                spec_id=spec.id,
                status="INITIALIZED",
                activated_at=now,
                first_forward_batch_id=batch.id,
                first_forward_as_of_date=batch.as_of_date,
                cash=float(spec.initial_capital),
                peak_nav=float(spec.initial_capital),
                exposure_cap=float(spec.dd_normal_gross or 1.0),
                risk_mode="normal",
                positions={},
                provenance={
                    "kind": SHADOW_KIND,
                    "experiment_group": cfg.experiment_group,
                    "candidate_config_hash": cfg.candidate_config_hash,
                    "not_historical_simulator": True,
                },
                warnings=[],
            )
            session.add(portfolio)
            session.flush()

        # Decision only if batch already generated by decision time
        gen = ensure_aware_utc(batch.generated_at)
        if gen <= now:
            preds = _batch_predictions(session, batch.id)
            decision = _build_decision_and_orders(
                session, portfolio, spec, batch, preds, decision_at=now
            )
            pending = session.scalars(
                select(func.count()).select_from(ShadowOrder).where(
                    ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
                )
            ).one()
            portfolio.status = "WAITING_FOR_FUTURE_MARKET_OPEN" if pending else "DECISION_READY"
            results.append(
                AdvanceResult(
                    portfolio_id=portfolio.id,
                    name=spec.name,
                    status=portfolio.status,
                    summary={
                        "activated_at": now.isoformat(),
                        "first_forward_batch_id": batch.id,
                        "signal_as_of": batch.as_of_date.isoformat(),
                        "signal_generated_at": gen.isoformat(),
                        "prediction_hash": batch.prediction_hash,
                        "decision_id": decision.id if decision else portfolio.last_decision_id,
                        "iso_week": portfolio.last_decision_iso_week,
                        "pending_orders": int(pending or 0),
                        "fills": 0,
                        "nav": float(portfolio.cash),
                        "cash": float(portfolio.cash),
                        "min_execution_date": (
                            min_execution_market_date(now).isoformat() if decision else None
                        ),
                        "targets": (decision.targets if decision else None),
                    },
                )
            )
        else:
            portfolio.status = "WAITING_FOR_SIGNAL"
            results.append(
                AdvanceResult(
                    portfolio_id=portfolio.id,
                    name=spec.name,
                    status=portfolio.status,
                    summary={"error": "batch_not_yet_available"},
                )
            )
    return results


def advance_shadow_portfolio(
    session: Session,
    portfolio_id: int,
    *,
    clock: Clock | None = None,
) -> AdvanceResult:
    """Advance one Shadow portfolio: decisions → fills → CA → MTM. Idempotent."""
    now = (clock or _utcnow)()
    portfolio = session.get(ShadowPortfolio, portfolio_id)
    if portfolio is None:
        raise ValueError(f"shadow portfolio not found: {portfolio_id}")
    spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
    if spec is None:
        raise ValueError("shadow spec missing")

    late_warnings = _scan_late_input_corrections(session, portfolio)

    # 1) New forward batches eligible for weekly decision.
    # Bound to the spec's own Prediction Candidate so parallel candidates stay isolated.
    batches = list(
        session.scalars(
            select(ForwardPredictionBatch)
            .where(
                ForwardPredictionBatch.status == "SUCCESS",
                ForwardPredictionBatch.candidate_config_hash == spec.candidate_config_hash,
                ForwardPredictionBatch.generated_at.is_not(None),
                ForwardPredictionBatch.generated_at <= now,
            )
            .order_by(ForwardPredictionBatch.as_of_date, ForwardPredictionBatch.id)
        )
    )
    decisions_made = 0
    for batch in batches:
        gen = ensure_aware_utc(batch.generated_at)  # type: ignore[arg-type]
        if gen > now:
            continue
        week = iso_week_key(batch.as_of_date)
        if portfolio.last_decision_iso_week == week:
            continue
        existing = session.scalar(
            select(ShadowDecision).where(
                ShadowDecision.portfolio_id == portfolio.id,
                ShadowDecision.iso_week == week,
            )
        )
        if existing is not None:
            portfolio.last_decision_iso_week = week
            continue
        preds = _batch_predictions(session, batch.id)
        d = _build_decision_and_orders(session, portfolio, spec, batch, preds, decision_at=now)
        if d is not None:
            decisions_made += 1

    # 2) Process newly available market dates after watermark (and after activation)
    activation_date = ensure_aware_utc(portfolio.activated_at).date()
    start_after = portfolio.last_processed_market_date
    # Never process market dates on/before activation calendar day for MTM bootstrap from history
    # Fills still gated by min_execution_date separately.
    days = _trading_days_after(session, start_after)
    fills_total = 0
    processed_days: list[str] = []
    for day in days:
        # Do not fabricate pre-activation NAV / fills from already-known calendar days.
        # Safe forward rule: process only market dates strictly after activation calendar date.
        # Watermark may still advance through older days without creating history.
        if day <= activation_date:
            portfolio.last_processed_market_date = day
            continue
        _apply_ca_for_day(session, portfolio, day)
        fills_total += _fill_pending_orders(session, portfolio, spec, day, now=now)
        _mark_nav(session, portfolio, spec, day, now=now)
        processed_days.append(day.isoformat())

    pending = int(
        session.scalar(
            select(func.count()).select_from(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
            )
        )
        or 0
    )
    filled = int(
        session.scalar(
            select(func.count()).select_from(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
        )
        or 0
    )
    if pending > 0:
        portfolio.status = "WAITING_FOR_FUTURE_MARKET_OPEN"
    elif filled > 0:
        portfolio.status = "ACTIVE"
    elif portfolio.last_decision_id:
        portfolio.status = "DECISION_READY"
    portfolio.updated_at = now

    return AdvanceResult(
        portfolio_id=portfolio.id,
        name=spec.name,
        status=portfolio.status,
        summary={
            "decisions_made": decisions_made,
            "fills_this_advance": fills_total,
            "pending_orders": pending,
            "filled_orders": filled,
            "last_processed_market_date": (
                portfolio.last_processed_market_date.isoformat()
                if portfolio.last_processed_market_date
                else None
            ),
            "processed_days": processed_days,
            "late_input_warnings": late_warnings,
            "cash": float(portfolio.cash),
            "positions": len(_positions_dict(portfolio)),
            "risk_mode": portfolio.risk_mode,
            "exposure_cap": float(portfolio.exposure_cap),
            "kind": SHADOW_KIND,
        },
    )


def advance_all_shadow_portfolios(
    session: Session,
    *,
    clock: Clock | None = None,
    experiment_groups: Sequence[str] | None = None,
) -> list[AdvanceResult]:
    """Advance Shadow portfolios of the given experiment groups.

    Defaults to the operational SHADOW_FORWARD_V0 group only, so research experiments
    added later can never make the operational daily Shadow stage fail.
    """
    groups = list(experiment_groups) if experiment_groups is not None else [EXPERIMENT_GROUP]
    rows = list(
        session.scalars(
            select(ShadowPortfolio)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_(groups))
            .order_by(ShadowPortfolio.id)
        )
    )
    return [advance_shadow_portfolio(session, p.id, clock=clock) for p in rows]
