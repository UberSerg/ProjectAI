"""Shadow Portfolio V0 — initialize and advance forward experiments."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.domain.ports.execution import OrderIntent
from app.domain.ports.portfolio import PortfolioPolicyInput, PredictionSignal
from app.infrastructure.market.models import Candle, Instrument
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.investment.domain.fixed_income import TransactionCostProfile
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
from app.modules.shadow.application.lot_aware import (
    EXECUTION_VERSION_LOT_AWARE_V2,
    apply_lot_aware_fill_to_portfolio,
    execution_version_for_spec,
    is_lot_aware_spec,
    is_sell_economics_v3_spec,
    set_fractional_position,
)
from app.modules.shadow.application.lot_aware import (
    position_qty as _lot_position_qty,
)
from app.modules.shadow.application.lot_aware import (
    positions_dict as _lot_positions_dict,
)
from app.modules.shadow.config import (
    FEE_PROFILE_CODE_SBER_INVESTMENT,
    FEE_PROFILE_VERSION_SBER_INVESTMENT,
    SHADOW_KIND,
    ShadowSpecConfig,
    operational_experiment_groups,
    operational_shadow_configs,
)
from app.modules.shadow.domain.fee_estimate import (
    FEE_RULE_UNAVAILABLE_AT_EXECUTION,
    estimate_shadow_fee,
    resolve_broker_fee_estimator,
)
from app.modules.shadow.domain.lot_plan import PlanInstrument, build_lot_order_plan
from app.modules.shadow.domain.sell_gate import (
    RISK_EXIT,
    HeldName,
    PolicyTarget,
    ReplacementCandidate,
    SellGateParams,
    SellPermission,
    apply_sell_gate,
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
    return _lot_positions_dict(portfolio)


def _set_position(portfolio: ShadowPortfolio, instrument_id: int, ticker: str, qty: float) -> None:
    set_fractional_position(portfolio, instrument_id, ticker, qty)


def _position_qty(portfolio: ShadowPortfolio, instrument_id: int) -> float:
    return _lot_position_qty(portfolio, instrument_id)


def _held_ids(portfolio: ShadowPortfolio) -> set[int]:
    return {int(k) for k, v in _positions_dict(portfolio).items() if abs(float(v.get("quantity") or 0)) > 1e-12}


def _order_lot_size(order: ShadowOrder) -> int | None:
    meta = getattr(order, "metadata_", None) or {}
    raw = meta.get("lot_size") if isinstance(meta, dict) else None
    if raw in (None, ""):
        return None
    try:
        lot = int(raw)
    except (TypeError, ValueError):
        return None
    return lot if lot > 0 else None


def _cancel_pending_orders(
    session: Session,
    *,
    portfolio_id: int,
    reason: str,
    decision_at: datetime,
    exclude_decision_id: int | None = None,
) -> int:
    """Cancel leftover PENDING orders. Does not mutate fills or historical filled rows."""
    q = select(ShadowOrder).where(
        ShadowOrder.portfolio_id == portfolio_id,
        ShadowOrder.status == "PENDING",
    )
    if exclude_decision_id is not None:
        q = q.where(ShadowOrder.decision_id != exclude_decision_id)
    rows = list(session.scalars(q))
    n = 0
    for order in rows:
        order.status = "CANCELLED"
        order.updated_at = decision_at
        meta = dict(order.metadata_ or {})
        meta["cancel_reason"] = reason
        meta["cancelled_at"] = decision_at.isoformat()
        order.metadata_ = meta
        n += 1
    return n


def repair_missing_position_lot_sizes(session: Session, portfolio: ShadowPortfolio) -> int:
    """Backfill lot_size onto lot-aware positions from MOEX LOTSIZE provenance.

    Repairs metadata only — does not change quantities, fills, or cash.
    """
    positions = dict(portfolio.positions or {})
    if not positions:
        return 0
    missing_ids: list[int] = []
    for key, row in positions.items():
        if not isinstance(row, dict):
            continue
        if abs(float(row.get("quantity") or 0)) < 1e-12:
            continue
        try:
            ls = int(row.get("lot_size") or 0)
        except (TypeError, ValueError):
            ls = 0
        if ls <= 0:
            missing_ids.append(int(row.get("instrument_id") or key))
    if not missing_ids:
        return 0
    instruments = list(
        session.scalars(select(Instrument).where(Instrument.id.in_(sorted(set(missing_ids)))))
    )
    resolved = resolve_equity_lot_sizes(session, instruments, fetch_missing=True)
    repaired = 0
    for key, row in list(positions.items()):
        if not isinstance(row, dict):
            continue
        iid = int(row.get("instrument_id") or key)
        try:
            ls = int(row.get("lot_size") or 0)
        except (TypeError, ValueError):
            ls = 0
        if ls > 0:
            continue
        hit = resolved.get(iid)
        if hit is None or hit.lot_size is None or hit.lot_size <= 0:
            continue
        new_row = dict(row)
        new_row["lot_size"] = int(hit.lot_size)
        qty = float(new_row.get("quantity") or 0)
        new_row["lots"] = int(qty) // int(hit.lot_size) if hit.lot_size else new_row.get("lots")
        new_row["lot_size_repaired"] = True
        new_row["lot_size_source"] = hit.source
        positions[str(key)] = new_row
        repaired += 1
    if repaired:
        portfolio.positions = positions
        flag_modified(portfolio, "positions")
    return repaired



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


def list_trading_sessions_after(session: Session, after: date | None) -> list[date]:
    """Observed MOEX trading sessions after watermark (from raw 1d candles)."""
    return _trading_days_after(session, after)


def session_has_eod_candles(session: Session, day: date) -> bool:
    """True when at least one raw 1d candle exists for the calendar day."""
    row = session.scalar(
        select(Candle.id).where(
            Candle.timeframe == "1d",
            func.date(Candle.timestamp) == day,
        ).limit(1)
    )
    return row is not None


def process_shadow_market_day(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    day: date,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Process exactly one completed market session for a Shadow portfolio.

    Same production path as ``advance_shadow_portfolio`` day loop:
    corporate actions → pending fills → NAV watermark.
    Idempotent under unique constraints on fills/NAV.
    """
    activation_date = ensure_aware_utc(portfolio.activated_at).date()
    if day <= activation_date:
        portfolio.last_processed_market_date = day
        portfolio.updated_at = now
        return {"day": day.isoformat(), "skipped": "pre_activation", "fills": 0}
    _apply_ca_for_day(session, portfolio, day)
    fills = _fill_pending_orders(session, portfolio, spec, day, now=now)
    _mark_nav(session, portfolio, spec, day, now=now)
    return {"day": day.isoformat(), "skipped": None, "fills": fills}


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
            prediction_semantic=str(
                getattr(p, "prediction_semantic", None)
                or getattr(batch, "prediction_semantic", None)
                or "EXPECTED_RETURN"
            ),
            prediction_score=float(p.predicted_return_20d),
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
    price_as_of = portfolio.last_processed_market_date or batch.as_of_date
    for pos in _positions_dict(portfolio).values():
        iid = int(pos["instrument_id"])
        if price_as_of is not None:
            _o, c = _candle_open_close(session, iid, price_as_of)
            if c is not None:
                closes[iid] = c
    # Also fetch closes for policy targets / candidates (needed by V3 economics).
    for d in risk_out.decisions:
        meta = dict(d.metadata or {})
        iid = int(meta.get("instrument_id") or 0)
        if iid and iid not in closes and price_as_of is not None:
            _o, c = _candle_open_close(session, iid, price_as_of)
            if c is not None:
                closes[iid] = c
    for sig in signals:
        iid = int(sig.instrument_id)
        if iid not in closes and price_as_of is not None:
            _o, c = _candle_open_close(session, iid, price_as_of)
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
                "prediction_semantic": meta.get("prediction_semantic") or "EXPECTED_RETURN",
                "policy": meta.get("policy") or spec.policy_name,
            }
        )

    decision_meta: dict[str, Any] = {
        "eligible_n": policy_out.metadata.get("eligible_n"),
        "selected_k": policy_out.metadata.get("selected_k"),
        "k_entry": policy_out.metadata.get("k_entry"),
        "k_max": policy_out.metadata.get("k_max"),
        "prediction_hash": batch.prediction_hash,
        "kind": SHADOW_KIND,
    }

    # V3 only: rank exit-band breach → review trigger; economic sell gate filters targets.
    if is_sell_economics_v3_spec(spec):
        targets, v3_meta = _apply_v3_sell_economics(
            session=session,
            portfolio=portfolio,
            spec=spec,
            batch=batch,
            signals=signals,
            policy_out=policy_out,
            policy_targets=targets,
            closes=closes,
            nav=nav,
            exposure_cap=exposure_cap,
            decision_at=decision_at,
        )
        decision_meta.update(v3_meta)
        exec_ver = execution_version_for_spec(spec)
        if exec_ver:
            decision_meta["execution_version"] = exec_ver

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
        metadata_=decision_meta,
    )
    session.add(decision)
    session.flush()

    # Supersede leftover PENDING from prior weeks so cash-starved buys cannot
    # block readiness forever after a new weekly plan is published.
    cancelled_n = _cancel_pending_orders(
        session,
        portfolio_id=int(portfolio.id),
        reason="SUPERSEDED_BY_NEW_DECISION",
        decision_at=decision_at,
        exclude_decision_id=int(decision.id),
    )
    if cancelled_n:
        meta = dict(decision.metadata_ or {})
        meta["cancelled_pending_orders"] = cancelled_n
        decision.metadata_ = meta

    # Build orders for target set + exits of held non-targets
    target_by_id = {int(t["instrument_id"]): t for t in targets}
    all_ids = set(target_by_id) | _held_ids(portfolio)
    min_delta = float(spec.min_trade_weight_delta)
    min_exec = min_execution_market_date(decision_at)
    eligible_count = int(policy_out.metadata.get("eligible_n") or len(signals))

    if is_lot_aware_spec(spec):
        _persist_lot_aware_orders(
            session,
            portfolio=portfolio,
            spec=spec,
            decision=decision,
            batch=batch,
            target_by_id=target_by_id,
            all_ids=all_ids,
            nav=nav,
            min_delta=min_delta,
            min_exec=min_exec,
            eligible_count=eligible_count,
            decision_at=decision_at,
        )
    else:
        _persist_fractional_orders(
            session,
            portfolio=portfolio,
            spec=spec,
            decision=decision,
            batch=batch,
            target_by_id=target_by_id,
            all_ids=all_ids,
            nav=nav,
            min_delta=min_delta,
            min_exec=min_exec,
            eligible_count=eligible_count,
            decision_at=decision_at,
        )

    session.flush()
    portfolio.last_decision_iso_week = week
    portfolio.last_decision_id = decision.id
    portfolio.last_processed_prediction_batch_id = batch.id
    return decision


def _apply_v3_sell_economics(
    *,
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    batch: ForwardPredictionBatch,
    signals: Sequence[PredictionSignal],
    policy_out: Any,
    policy_targets: list[dict[str, Any]],
    closes: dict[int, float],
    nav: float,
    exposure_cap: float,
    decision_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run pure sell gate; return filtered targets + metadata (candidate traces)."""
    payload = spec.payload or {}
    fee_profile_code = (
        getattr(spec, "fee_profile_code", None)
        or (payload.get("fee_profile_code") if isinstance(payload, dict) else None)
    )
    fee_profile_version = (
        getattr(spec, "fee_profile_version", None)
        if getattr(spec, "fee_profile_version", None) is not None
        else (payload.get("fee_profile_version") if isinstance(payload, dict) else None)
    )
    if fee_profile_code and fee_profile_version is None:
        fee_profile_version = FEE_PROFILE_VERSION_SBER_INVESTMENT
    # V3 always carries a frozen FeeProfile identity (default built-in Sber).
    if not fee_profile_code:
        fee_profile_code = FEE_PROFILE_CODE_SBER_INVESTMENT
        if fee_profile_version is None:
            fee_profile_version = FEE_PROFILE_VERSION_SBER_INVESTMENT
    min_edge = float(
        getattr(spec, "min_net_rotation_edge_bps", None)
        if getattr(spec, "min_net_rotation_edge_bps", None) is not None
        else (
            payload.get("min_net_rotation_edge_bps", 0.0)
            if isinstance(payload, dict)
            else 0.0
        )
    )
    slippage_bps = float(spec.slippage_bps or 0.0)
    # Fee date at decision = planned min execution market date (not signal as_of).
    fee_as_of = min_execution_market_date(decision_at)
    # Resolve persisted FeeProfile when session available; domain gate stays SQL-free.
    fee_estimator = resolve_broker_fee_estimator(
        fee_profile_code=str(fee_profile_code) if fee_profile_code else None,
        fee_profile_version=int(fee_profile_version) if fee_profile_version is not None else None,
        commission_bps=float(spec.commission_bps or 0.0),
        session=session,
        allow_legacy_bps_fallback=False,
    )

    signal_by_id = {int(s.instrument_id): s for s in signals}
    k_max = int(policy_out.metadata.get("k_max") or 0)
    k_entry = int(policy_out.metadata.get("k_entry") or len(policy_targets))
    decision_day = decision_at.date() if hasattr(decision_at, "date") else batch.as_of_date
    # Conservative stale rule: signal older than 14 calendar days vs decision day.
    stale_horizon_days = 14

    policy_ids = {int(t["instrument_id"]) for t in policy_targets}
    held: list[HeldName] = []
    risk_forced: dict[int, str] = {}
    risk_mode = str(portfolio.risk_mode or "normal").lower()

    for key, row in _positions_dict(portfolio).items():
        qty = float(row.get("quantity") or 0)
        if abs(qty) < 1e-12:
            continue
        iid = int(row.get("instrument_id") or key)
        sig = signal_by_id.get(iid)
        px = closes.get(iid)
        current_w = (qty * px / nav) if px and nav > 0 else float(row.get("weight") or 0.0)
        avg_entry = row.get("avg_entry")
        avg_f = float(avg_entry) if avg_entry is not None else None
        unreal = None
        if avg_f is not None and px is not None:
            unreal = (px - avg_f) * qty
        rank_val = None
        semantic = "EXPECTED_RETURN"
        expected = None
        signal_as_of = None
        signal_stale = False
        if sig is not None:
            semantic = str(sig.prediction_semantic or "EXPECTED_RETURN")
            expected = float(sig.predicted_return_20d) if semantic == "EXPECTED_RETURN" else None
            signal_as_of = sig.as_of_date
            if signal_as_of is not None and (decision_day - signal_as_of).days > stale_horizon_days:
                signal_stale = True
        # Rank from policy metadata if available
        for t in policy_targets:
            if int(t["instrument_id"]) == iid and t.get("rank") is not None:
                rank_val = int(t["rank"])
                break
        if rank_val is None and sig is not None:
            # Cross-sectional rank among OK signals (1 = best).
            ranked = sorted(signals, key=lambda s: (-float(s.score), int(s.instrument_id)))
            rank_val = next(
                (i for i, s in enumerate(ranked, start=1) if int(s.instrument_id) == iid),
                None,
            )
        in_exit = True if rank_val is None or k_max <= 0 else rank_val <= k_max
        review_trigger = iid not in policy_ids
        held.append(
            HeldName(
                instrument_id=iid,
                ticker=str(row.get("ticker") or (sig.ticker if sig else iid)),
                quantity=qty,
                current_weight=float(current_w),
                rank=rank_val,
                prediction_semantic=semantic,
                expected_return=expected,
                signal_as_of=signal_as_of,
                price=float(px) if px is not None else None,
                avg_entry=avg_f,
                unrealized_pnl=unreal,
                in_exit_band=in_exit,
                signal_stale=signal_stale,
                review_trigger=review_trigger,
            )
        )
        # Risk can force exit of reviewed names without a replacement.
        if review_trigger and risk_mode in {"risk_off", "off"} and exposure_cap < 1.0 - 1e-12:
            risk_forced[iid] = RISK_EXIT

    policy_target_models = [
        PolicyTarget(
            instrument_id=int(t["instrument_id"]),
            ticker=str(t["ticker"]),
            target_weight=float(t["target_weight"]),
            rank=int(t["rank"]) if t.get("rank") is not None else None,
            prediction_semantic=str(t.get("prediction_semantic") or "EXPECTED_RETURN"),
            expected_return=(
                float(t["predicted_return_20d"])
                if t.get("predicted_return_20d") is not None
                and str(t.get("prediction_semantic") or "EXPECTED_RETURN") == "EXPECTED_RETURN"
                else None
            ),
            action=str(t["action"]) if t.get("action") is not None else None,
            price=closes.get(int(t["instrument_id"])),
            signal_as_of=batch.as_of_date,
        )
        for t in policy_targets
    ]

    held_ids = {h.instrument_id for h in held}
    replacements: list[ReplacementCandidate] = []
    for sig in sorted(signals, key=lambda s: (-float(s.score), int(s.instrument_id))):
        iid = int(sig.instrument_id)
        if iid in held_ids:
            continue
        semantic = str(sig.prediction_semantic or "EXPECTED_RETURN")
        stale = bool(
            sig.as_of_date is not None
            and (decision_day - sig.as_of_date).days > stale_horizon_days
        )
        ranked = sorted(signals, key=lambda s: (-float(s.score), int(s.instrument_id)))
        rank_val = next(
            (i for i, s in enumerate(ranked, start=1) if int(s.instrument_id) == iid),
            None,
        )
        replacements.append(
            ReplacementCandidate(
                instrument_id=iid,
                ticker=sig.ticker,
                rank=rank_val,
                prediction_semantic=semantic,
                expected_return=(
                    float(sig.predicted_return_20d) if semantic == "EXPECTED_RETURN" else None
                ),
                price=closes.get(iid),
                signal_as_of=sig.as_of_date,
                signal_stale=stale,
            )
        )

    gate = apply_sell_gate(
        held=held,
        policy_targets=policy_target_models,
        replacement_candidates=replacements,
        params=SellGateParams(
            slippage_bps=slippage_bps,
            min_net_rotation_edge_bps=min_edge,
            fee_profile_code=str(fee_profile_code) if fee_profile_code else None,
            k_entry=k_entry,
            exposure_cap=float(exposure_cap),
            as_of=fee_as_of,
        ),
        fee_estimator=fee_estimator,
        risk_forced=risk_forced,
        eligible_count=int(policy_out.metadata.get("eligible_n") or len(signals)),
        policy_name=spec.policy_name,
    )

    perm_by_id = {int(p.instrument_id): p for p in gate.permissions}
    targets = [
        {
            "instrument_id": t.instrument_id,
            "ticker": t.ticker,
            "target_weight": float(t.target_weight),
            "action": t.action,
            "rank": t.rank,
            "predicted_return_20d": t.predicted_return_20d,
            "policy": t.policy or spec.policy_name,
            "gate_action": t.gate_action,
            "rotate_from": t.rotate_from,
            "rotate_to": t.rotate_to,
            "sell_allowed": (
                perm_by_id[int(t.instrument_id)].sell_allowed
                if int(t.instrument_id) in perm_by_id
                else True
            ),
            "sell_permission": (
                perm_by_id[int(t.instrument_id)].to_dict()
                if int(t.instrument_id) in perm_by_id
                else None
            ),
        }
        for t in gate.targets
    ]
    sell_permissions = {str(p.instrument_id): p.to_dict() for p in gate.permissions}
    meta = {
        "sell_gate": dict(gate.metadata),
        "candidate_traces": [tr.to_dict() for tr in gate.traces],
        "sell_permissions": sell_permissions,
        "fee_profile_code": fee_profile_code or FEE_PROFILE_CODE_SBER_INVESTMENT,
        "fee_profile_version": int(fee_profile_version)
        if fee_profile_version is not None
        else FEE_PROFILE_VERSION_SBER_INVESTMENT,
        "fee_estimation_date": fee_as_of.isoformat(),
        "min_execution_market_date": fee_as_of.isoformat(),
        "min_net_rotation_edge_bps": min_edge,
        "slippage_bps": slippage_bps,
    }
    return targets, meta


def _persist_fractional_orders(
    session: Session,
    *,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    decision: ShadowDecision,
    batch: ForwardPredictionBatch,
    target_by_id: dict[int, dict[str, Any]],
    all_ids: set[int],
    nav: float,
    min_delta: float,
    min_exec: date,
    eligible_count: int,
    decision_at: datetime,
) -> None:
    """V1 fractional path — unchanged semantics."""
    for iid in sorted(all_ids):
        ticker = (
            target_by_id[iid]["ticker"]
            if iid in target_by_id
            else str(_positions_dict(portfolio).get(str(iid), {}).get("ticker") or iid)
        )
        target_w = float(target_by_id[iid]["target_weight"]) if iid in target_by_id else 0.0
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
            continue
        if px is None or px <= 0:
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


def _persist_lot_aware_orders(
    session: Session,
    *,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    decision: ShadowDecision,
    batch: ForwardPredictionBatch,
    target_by_id: dict[int, dict[str, Any]],
    all_ids: set[int],
    nav: float,
    min_delta: float,
    min_exec: date,
    eligible_count: int,
    decision_at: datetime,
) -> None:
    """V2/V3 lot-aware path — LOTSIZE + cash-safe OrderPlan."""
    v3 = is_sell_economics_v3_spec(spec)
    perm_by_id = _sell_permissions_from_decision(decision) if v3 else {}
    instruments_orm: list[Instrument] = []
    if all_ids:
        instruments_orm = list(
            session.scalars(select(Instrument).where(Instrument.id.in_(sorted(all_ids))))
        )
    lot_res = resolve_equity_lot_sizes(session, instruments_orm, fetch_missing=True)
    plan_inputs: list[PlanInstrument] = []
    for iid in sorted(all_ids):
        ticker = (
            target_by_id[iid]["ticker"]
            if iid in target_by_id
            else str(_positions_dict(portfolio).get(str(iid), {}).get("ticker") or iid)
        )
        target_w = float(target_by_id[iid]["target_weight"]) if iid in target_by_id else 0.0
        o, c = _candle_open_close(session, iid, batch.as_of_date)
        px = c or o
        current_qty = _position_qty(portfolio, iid)
        current_value = current_qty * px if px and px > 0 else 0.0
        current_w = (current_value / nav) if nav > 0 else 0.0
        if (
            min_delta > 0
            and abs(target_w - current_w) < min_delta - 1e-15
            and not (target_w <= 0 and current_qty > 0)
        ):
            continue
        resolved = lot_res.get(iid)
        lot_size = resolved.lot_size if resolved is not None else None
        rank = (target_by_id.get(iid) or {}).get("rank")
        sell_allowed = True
        max_sell_units: Decimal | None = None
        if v3:
            perm = perm_by_id.get(iid)
            if perm is not None:
                sell_allowed = bool(perm.sell_allowed)
                if perm.max_sell_units is not None:
                    max_sell_units = Decimal(str(perm.max_sell_units))
                elif perm.max_sell_fraction is not None and current_qty > 0:
                    max_sell_units = Decimal(str(current_qty)) * Decimal(
                        str(perm.max_sell_fraction)
                    )
            elif current_qty > 1e-12 and target_w <= 0:
                # Held exit without an explicit permission — block (fail closed).
                sell_allowed = False
        plan_inputs.append(
            PlanInstrument(
                instrument_id=iid,
                ticker=ticker,
                target_weight=Decimal(str(target_w)),
                current_units=Decimal(str(current_qty)),
                price=Decimal(str(px)) if px and px > 0 else None,
                lot_size=lot_size,
                rank=int(rank) if rank is not None else None,
                sell_allowed=sell_allowed,
                max_sell_units=max_sell_units,
            )
        )

    payload = spec.payload or {}
    strategic = float(payload.get("strategic_cash_reserve") or 0.0)
    costs = TransactionCostProfile(
        # V1/V2: flat commission_bps. V3: FeeEngine via fee_for (broker_bps ignored).
        broker_bps=Decimal(str(spec.commission_bps or 0.0)),
        slippage_bps=Decimal(str(spec.slippage_bps or 0.0)),
    )
    fee_for = None
    fee_estimator = None
    fee_profile_code = None
    fee_profile_version = None
    if v3:
        fee_profile_code = (
            payload.get("fee_profile_code")
            if isinstance(payload, dict)
            else None
        ) or FEE_PROFILE_CODE_SBER_INVESTMENT
        fee_profile_version = (
            payload.get("fee_profile_version")
            if isinstance(payload, dict)
            else None
        )
        if fee_profile_version is None:
            fee_profile_version = FEE_PROFILE_VERSION_SBER_INVESTMENT
        fee_estimator = resolve_broker_fee_estimator(
            fee_profile_code=str(fee_profile_code),
            fee_profile_version=int(fee_profile_version),
            commission_bps=0.0,
            session=session,
            allow_legacy_bps_fallback=False,
        )

        def fee_for(side: str, notional: Decimal, inst: PlanInstrument) -> Decimal | None:
            quote = estimate_shadow_fee(
                fee_estimator,
                side=side,
                notional=notional,
                instrument_id=int(inst.instrument_id),
                as_of=min_exec,
                fee_profile_code=str(fee_profile_code),
                fee_profile_version=int(fee_profile_version),
                instrument_symbol=str(inst.ticker),
            )
            return quote.amount

    plan = build_lot_order_plan(
        plan_inputs,
        cash=Decimal(str(portfolio.cash)),
        nav=Decimal(str(nav)),
        costs=costs,
        strategic_cash_reserve=Decimal(str(strategic)),
        fee_for=fee_for,
    )

    if v3:
        unauthorized = [
            r
            for r in plan.executable
            if r.action == "SELL"
            and (
                r.instrument_id not in perm_by_id
                or not perm_by_id[r.instrument_id].sell_allowed
            )
        ]
        if unauthorized:
            # Do not persist — sell permission invariant violated.
            meta = dict(decision.metadata_ or {})
            meta["order_plan_blocked"] = {
                "reason": "UNAUTHORIZED_SELL",
                "instrument_ids": [r.instrument_id for r in unauthorized],
            }
            decision.metadata_ = meta
            return

        # Journal consistency: HOLD/REVIEW_HOLD/DATA_HOLD must not coexist with SELL.
        no_sell_actions = {"HOLD", "REVIEW_HOLD", "DATA_HOLD"}
        for r in plan.executable:
            if r.action != "SELL":
                continue
            perm = perm_by_id.get(r.instrument_id)
            if perm is not None and perm.action in no_sell_actions:
                meta = dict(decision.metadata_ or {})
                meta["order_plan_blocked"] = {
                    "reason": "HOLD_SELL_INCONSISTENCY",
                    "instrument_id": r.instrument_id,
                    "gate_action": perm.action,
                }
                decision.metadata_ = meta
                return

    meta = dict(decision.metadata_ or {})
    meta["order_plan"] = {
        "projected_cash": float(plan.projected_cash),
        "fees_total": float(plan.fees_total),
        "rounding_remainder": float(plan.rounding_remainder),
        "starting_cash": float(plan.starting_cash),
        "strategic_cash_reserve": float(plan.strategic_cash_reserve),
        "sell_proceeds": float(plan.sell_proceeds),
        "buy_notional": float(plan.buy_notional),
        "fee_estimation_date": min_exec.isoformat() if v3 else None,
        "fee_profile_code": fee_profile_code if v3 else None,
        "fee_profile_version": int(fee_profile_version) if v3 and fee_profile_version else None,
        "rows": [
            {
                "instrument_id": r.instrument_id,
                "ticker": r.ticker,
                "action": r.action,
                "lots_delta": r.lots_delta,
                "units_delta": float(r.units_delta),
                "target_weight": float(r.target_weight),
                "current_weight": float(r.current_weight),
                "estimated_notional": float(r.estimated_notional),
                "estimated_fee": float(r.estimated_fee),
                "lot_size": r.lot_size,
                "reason": r.reason,
                "rank": r.rank,
            }
            for r in plan.rows
        ],
        "skipped": [
            {
                "instrument_id": r.instrument_id,
                "ticker": r.ticker,
                "action": r.action,
                "reason": r.reason,
                "lot_size": r.lot_size,
                "rank": r.rank,
            }
            for r in plan.skipped
        ],
        "orders": [
            {
                "instrument_id": r.instrument_id,
                "ticker": r.ticker,
                "action": r.action,
                "lots_delta": r.lots_delta,
                "units_delta": float(r.units_delta),
                "lot_size": r.lot_size,
                "reason": r.reason,
            }
            for r in plan.executable
        ],
    }
    meta["skipped"] = meta["order_plan"]["skipped"]
    meta["execution_version"] = execution_version_for_spec(spec) or EXECUTION_VERSION_LOT_AWARE_V2
    if v3:
        meta["fee_estimation_date"] = min_exec.isoformat()
        meta["fee_profile_code"] = fee_profile_code
        meta["fee_profile_version"] = int(fee_profile_version) if fee_profile_version else None
    decision.metadata_ = meta

    for row in plan.executable:
        action = (target_by_id.get(row.instrument_id) or {}).get("action")
        gate_action = (target_by_id.get(row.instrument_id) or {}).get("gate_action")
        perm = perm_by_id.get(row.instrument_id) if v3 else None
        if perm is not None and gate_action is None:
            gate_action = perm.action
        if row.action == "SELL":
            if v3 and perm is not None:
                # V3: order reason must be the gate authorization reason.
                if perm.action == "ROTATE":
                    rot_ticker = None
                    if perm.rotate_to is not None:
                        rot_tgt = target_by_id.get(int(perm.rotate_to)) or {}
                        rot_ticker = rot_tgt.get("ticker")
                    reason = perm.reason or (
                        f"ROTATE_TO_{rot_ticker or perm.rotate_to}"
                    )
                elif perm.action in {"RISK_EXIT", "RISK_REDUCE", "EXIT_TO_CASH"}:
                    reason = str(perm.reason or perm.action)
                else:
                    reason = str(perm.reason or perm.action)
            elif row.target_weight <= 0:
                if gate_action == "ROTATE":
                    reason = (
                        f"ROTATE_TO_"
                        f"{(target_by_id.get(row.instrument_id) or {}).get('rotate_to')}"
                    )
                elif gate_action in {"RISK_EXIT", "RISK_REDUCE", "EXIT_TO_CASH"}:
                    reason = str(gate_action)
                else:
                    reason = "EXIT_BELOW_TOP35"
            else:
                reason = (
                    "REBALANCE_WEIGHT_DELTA"
                    if action == "HOLD_WITHIN_EXIT_BAND"
                    else str(action or row.action)
                )
        elif row.action == "BUY" and _position_qty(portfolio, row.instrument_id) <= 1e-12:
            if gate_action == "ROTATE":
                reason = f"ROTATE_FROM_{(target_by_id.get(row.instrument_id) or {}).get('rotate_from')}"
            else:
                reason = str(action or "ENTER_TOP20")
        else:
            reason = (
                "REBALANCE_WEIGHT_DELTA"
                if action == "HOLD_WITHIN_EXIT_BAND"
                else str(action or row.action)
            )
        session.add(
            ShadowOrder(
                portfolio_id=portfolio.id,
                decision_id=decision.id,
                instrument_id=row.instrument_id,
                ticker=row.ticker,
                side=row.action,
                target_weight=float(row.target_weight),
                target_notional=float(row.estimated_notional),
                quantity=float(row.units_delta),
                reason=reason,
                status="PENDING",
                predicted_return_20d=(target_by_id.get(row.instrument_id) or {}).get(
                    "predicted_return_20d"
                ),
                rank=row.rank,
                eligible_count=eligible_count,
                decision_at=decision_at,
                min_execution_date=min_exec,
                metadata_=_order_fee_metadata(
                    base={
                        "forward_batch_id": batch.id,
                        "signal_as_of": batch.as_of_date.isoformat(),
                        "signal_generated_at": ensure_aware_utc(
                            batch.generated_at or decision_at
                        ).isoformat(),
                        "policy": spec.policy_name,
                        "risk_mode": portfolio.risk_mode,
                        "kind": SHADOW_KIND,
                        "execution_version": execution_version_for_spec(spec)
                        or EXECUTION_VERSION_LOT_AWARE_V2,
                        "lots": int(row.lots_delta),
                        "lot_size": int(row.lot_size) if row.lot_size else None,
                        "units": float(row.units_delta),
                        "plan_reason": row.reason,
                        "estimated_fee": float(row.estimated_fee),
                        "gate_action": gate_action,
                        "sell_allowed": (
                            bool(perm.sell_allowed) if perm is not None else None
                        ),
                    },
                    v3=v3,
                    fee_estimator=fee_estimator,
                    fee_profile_code=str(fee_profile_code) if fee_profile_code else None,
                    fee_profile_version=(
                        int(fee_profile_version) if fee_profile_version is not None else None
                    ),
                    fee_date=min_exec,
                    side=str(row.action),
                    notional=Decimal(str(row.estimated_notional)),
                    instrument_id=int(row.instrument_id),
                    instrument_symbol=str(row.ticker),
                    estimated=True,
                ),
            )
        )


def _order_fee_metadata(
    *,
    base: dict[str, Any],
    v3: bool,
    fee_estimator: Any,
    fee_profile_code: str | None,
    fee_profile_version: int | None,
    fee_date: date,
    side: str,
    notional: Decimal,
    instrument_id: int,
    instrument_symbol: str,
    estimated: bool,
) -> dict[str, Any]:
    """Attach FeeEngine provenance to order/fill metadata (V3 only)."""
    meta = dict(base)
    if not v3 or fee_estimator is None:
        return meta
    quote = estimate_shadow_fee(
        fee_estimator,
        side=side,
        notional=notional,
        instrument_id=instrument_id,
        as_of=fee_date,
        fee_profile_code=fee_profile_code,
        fee_profile_version=fee_profile_version,
        instrument_symbol=instrument_symbol,
    )
    meta.update(quote.to_provenance(estimated=estimated))
    return meta


def _sell_permissions_from_decision(
    decision: ShadowDecision,
) -> dict[int, SellPermission]:
    """Rebuild SellPermission map from decision metadata (V3)."""
    meta = dict(decision.metadata_ or {})
    raw = meta.get("sell_permissions") or {}
    if not raw and isinstance(meta.get("sell_gate"), dict):
        raw = (meta.get("sell_gate") or {}).get("sell_permissions") or {}
    out: dict[int, SellPermission] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        try:
            iid = int(val.get("instrument_id") or key)
        except (TypeError, ValueError):
            continue
        max_units = val.get("max_sell_units")
        out[iid] = SellPermission(
            instrument_id=iid,
            ticker=str(val.get("ticker") or iid),
            sell_allowed=bool(val.get("sell_allowed")),
            action=str(val.get("action") or "HOLD"),
            reason=val.get("reason"),
            max_sell_units=Decimal(str(max_units)) if max_units is not None else None,
            max_sell_fraction=(
                float(val["max_sell_fraction"])
                if val.get("max_sell_fraction") is not None
                else None
            ),
            rotate_to=(
                int(val["rotate_to"]) if val.get("rotate_to") is not None else None
            ),
        )
    return out


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
    v3 = is_sell_economics_v3_spec(spec)
    payload = spec.payload or {}
    fee_profile_code = None
    fee_profile_version = None
    fee_estimator = None
    if v3:
        fee_profile_code = (
            (payload.get("fee_profile_code") if isinstance(payload, dict) else None)
            or FEE_PROFILE_CODE_SBER_INVESTMENT
        )
        fee_profile_version = (
            payload.get("fee_profile_version") if isinstance(payload, dict) else None
        )
        if fee_profile_version is None:
            fee_profile_version = FEE_PROFILE_VERSION_SBER_INVESTMENT
        fee_estimator = resolve_broker_fee_estimator(
            fee_profile_code=str(fee_profile_code),
            fee_profile_version=int(fee_profile_version),
            commission_bps=0.0,
            session=session,
            allow_legacy_bps_fallback=False,
        )
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
        # V3: slippage via adapter; broker commission from FeeEngine on execution_date.
        fill = adapter.fill(
            intent,
            raw_open=raw_open,
            commission_bps=0.0 if v3 else float(spec.commission_bps or 0.0),
            slippage_bps=float(spec.slippage_bps or 0.0),
        )
        if fill is None:
            continue

        fee_quote = None
        if v3 and fee_estimator is not None:
            # Actual notional after slippage-adjusted fill price.
            fee_quote = estimate_shadow_fee(
                fee_estimator,
                side=str(order.side),
                notional=Decimal(str(fill.notional)),
                instrument_id=int(order.instrument_id),
                as_of=market_date,
                fee_profile_code=str(fee_profile_code),
                fee_profile_version=int(fee_profile_version)
                if fee_profile_version is not None
                else None,
                instrument_symbol=str(order.ticker),
            )
            if fee_quote.is_unknown:
                # Honest degrade — do not invent 0% commission.
                ometa = dict(order.metadata_ or {})
                ometa["limitation"] = FEE_RULE_UNAVAILABLE_AT_EXECUTION
                ometa["fee_status"] = str(fee_quote.status)
                ometa["fee_date"] = market_date.isoformat()
                ometa["fee_explanation"] = fee_quote.explanation
                order.metadata_ = ometa
                order.updated_at = now
                continue
            fill = replace(fill, commission=float(fee_quote.amount or 0))

        lot_aware = is_lot_aware_spec(spec)
        lot_size = _order_lot_size(order)
        # Apply cash / positions: BUY decreases by notional+fee; SELL increases by notional-fee.
        if order.side == "BUY":
            cost = fill.notional + fill.commission
            if cost > float(portfolio.cash) + 1e-6:
                # insufficient cash — skip fill, leave pending
                continue
            new_cash = float(portfolio.cash) - cost
            if new_cash < -1e-9:
                continue
            portfolio.cash = new_cash
            if lot_aware:
                if lot_size is None:
                    continue
                apply_lot_aware_fill_to_portfolio(
                    portfolio,
                    instrument_id=int(order.instrument_id),
                    ticker=order.ticker,
                    side="BUY",
                    quantity=float(fill.quantity),
                    fill_price=float(fill.fill_price),
                    commission=float(fill.commission),
                    lot_size=lot_size,
                )
            else:
                new_qty = _position_qty(portfolio, int(order.instrument_id)) + fill.quantity
                _set_position(portfolio, int(order.instrument_id), order.ticker, new_qty)
        else:
            sell_qty = min(fill.quantity, _position_qty(portfolio, int(order.instrument_id)))
            if sell_qty <= 0:
                order.status = "CANCELLED"
                order.updated_at = now
                continue
            # Recompute commission on actual sell notional when quantity was clipped.
            sell_notional = sell_qty * fill.fill_price
            if v3 and fee_estimator is not None and abs(sell_qty - fill.quantity) > 1e-12:
                fee_quote = estimate_shadow_fee(
                    fee_estimator,
                    side="SELL",
                    notional=Decimal(str(sell_notional)),
                    instrument_id=int(order.instrument_id),
                    as_of=market_date,
                    fee_profile_code=str(fee_profile_code),
                    fee_profile_version=int(fee_profile_version)
                    if fee_profile_version is not None
                    else None,
                    instrument_symbol=str(order.ticker),
                )
                if fee_quote.is_unknown:
                    ometa = dict(order.metadata_ or {})
                    ometa["limitation"] = FEE_RULE_UNAVAILABLE_AT_EXECUTION
                    ometa["fee_status"] = str(fee_quote.status)
                    ometa["fee_date"] = market_date.isoformat()
                    order.metadata_ = ometa
                    order.updated_at = now
                    continue
                commission = float(fee_quote.amount or 0)
            else:
                # Scale legacy bps commission to clipped qty; V3 already set absolute fee.
                if not v3 and fill.quantity > 0 and abs(sell_qty - fill.quantity) > 1e-12:
                    commission = float(fill.commission) * (sell_qty / fill.quantity)
                else:
                    commission = float(fill.commission)
            proceeds = sell_notional - commission
            portfolio.cash = float(portfolio.cash) + proceeds
            if lot_aware:
                if lot_size is None:
                    # fall back: require lot from position
                    pos_row = _positions_dict(portfolio).get(str(order.instrument_id)) or {}
                    lot_size = int(pos_row.get("lot_size") or 0) or None
                if lot_size is None:
                    continue
                apply_lot_aware_fill_to_portfolio(
                    portfolio,
                    instrument_id=int(order.instrument_id),
                    ticker=order.ticker,
                    side="SELL",
                    quantity=float(sell_qty),
                    fill_price=float(fill.fill_price),
                    commission=float(commission),
                    lot_size=lot_size,
                )
            else:
                new_qty = _position_qty(portfolio, int(order.instrument_id)) - sell_qty
                _set_position(portfolio, int(order.instrument_id), order.ticker, new_qty)
            fill = replace(
                fill,
                quantity=sell_qty,
                notional=sell_notional,
                commission=commission,
            )

        # Immutable fill row
        existing_fill = session.scalar(select(ShadowFill).where(ShadowFill.order_id == order.id))
        if existing_fill is not None:
            continue
        fill_meta: dict[str, Any] = {"kind": SHADOW_KIND, "raw_open_source": "market.candles"}
        if lot_aware:
            fill_meta["execution_version"] = (
                execution_version_for_spec(spec) or EXECUTION_VERSION_LOT_AWARE_V2
            )
            if lot_size is not None:
                fill_meta["lot_size"] = lot_size
                fill_meta["lots"] = int(float(fill.quantity) / lot_size)
        if v3 and fee_quote is not None:
            fill_meta.update(fee_quote.to_provenance(estimated=False))
            fill_meta["fee_date"] = market_date.isoformat()
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
                metadata_=fill_meta,
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


def apply_pending_forward_decisions(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    *,
    now: datetime,
    max_as_of: date | None = None,
) -> int:
    """Create weekly decisions/orders from existing Forward batches (idempotent).

    PIT: only batches with ``generated_at <= now`` and optional ``as_of_date <= max_as_of``.
    """
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
        if max_as_of is not None and batch.as_of_date > max_as_of:
            continue
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
    return decisions_made


def refresh_shadow_portfolio_status(session: Session, portfolio: ShadowPortfolio, *, now: datetime) -> None:
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
    decisions_made = apply_pending_forward_decisions(session, portfolio, spec, now=now)

    # Process newly available market dates after watermark (production day path).
    days = _trading_days_after(session, portfolio.last_processed_market_date)
    fills_total = 0
    processed_days: list[str] = []
    for day in days:
        day_result = process_shadow_market_day(session, portfolio, spec, day, now=now)
        fills_total += int(day_result.get("fills") or 0)
        if day_result.get("skipped") is None:
            processed_days.append(day.isoformat())

    refresh_shadow_portfolio_status(session, portfolio, now=now)

    return AdvanceResult(
        portfolio_id=portfolio.id,
        name=spec.name,
        status=portfolio.status,
        summary={
            "decisions_made": decisions_made,
            "fills_this_advance": fills_total,
            "pending_orders": int(
                session.scalar(
                    select(func.count()).select_from(ShadowOrder).where(
                        ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
                    )
                )
                or 0
            ),
            "filled_orders": int(
                session.scalar(
                    select(func.count())
                    .select_from(ShadowFill)
                    .where(ShadowFill.portfolio_id == portfolio.id)
                )
                or 0
            ),
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

    Defaults to operational Shadow groups (V1 forward + Realism V2) so research
    experiments (e.g. Model A/B) never make the operational daily Shadow stage fail.
    """
    groups = list(experiment_groups) if experiment_groups is not None else list(operational_experiment_groups())
    rows = list(
        session.scalars(
            select(ShadowPortfolio)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_(groups))
            .order_by(ShadowPortfolio.id)
        )
    )
    return [advance_shadow_portfolio(session, p.id, clock=clock) for p in rows]
