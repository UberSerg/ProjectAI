"""Shadow Decision Journal read models (Decision → Orders → Fills → NAV).

Read-only. Does not invent fills, reason codes, or candidate traces.
Legacy decisions without ``candidate_traces`` remain ``detail_available=false``
but may still expose structured evidence via ``evidence_level`` (PARTIAL/LIMITED).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowFill,
    ShadowNavDaily,
    ShadowOrder,
    ShadowPortfolio,
)

EvidenceLevel = Literal["FULL", "PARTIAL", "LIMITED", "NONE"]
ExecutionTiming = Literal["same_day", "later", "none", "status_fill_mismatch"]

LEGACY_TRACE_MESSAGE_RU = (
    "Подробный decision trace для этой исторической версии не сохранялся."
)

PARTIAL_EVIDENCE_MESSAGE_RU = (
    "Для решений этого периода не сохранялось подробное обоснование отбора "
    "каждой бумаги. При этом сохранились состав заявок и параметры стратегии. "
    "Ниже показаны доступные факты."
)

LIMITED_EVIDENCE_MESSAGE_RU = (
    "По этому дню сохранились лишь отдельные сведения о решении. "
    "Подробное обоснование отбора бумаг недоступно."
)

NONE_EVIDENCE_MESSAGE_RU = "Содержательных сведений о решении за этот день нет."

# Explicit product fields only — never expose free-form / CoT blobs.
_TRACE_PUBLIC_KEYS: frozenset[str] = frozenset(
    {
        "instrument_id",
        "ticker",
        "signal_as_of",
        "rank",
        "eligible_count",
        "prediction_semantic",
        "predicted_value",
        "predicted_return_20d",
        "held_before",
        "quantity_before",
        "current_weight",
        "avg_entry",
        "current_mark",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "entry_band",
        "exit_band",
        "entry_exit_band_state",
        "review_trigger",
        "target_weight",
        "replacement_ticker",
        "replacement_instrument_id",
        "gross_expected_edge",
        "sell_fee_estimate",
        "buy_fee_estimate",
        "slippage_estimate",
        "net_edge",
        "decision_action",
        "reason_codes",
        "limitation_codes",
    }
)

_FILLED_STATUSES = frozenset({"FILLED", "PARTIAL", "PARTIALLY_FILLED"})
_CANCELLED_STATUSES = frozenset({"CANCELLED", "CANCELED"})
_PENDING_STATUSES = frozenset({"PENDING", "OPEN", "NEW", "SUBMITTED", "WORKING"})
_REJECTED_STATUSES = frozenset({"REJECTED", "EXPIRED"})


def _iso_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _normalize_ticker(value: str | None) -> str:
    return (value or "").strip().upper()


def _normalize_action(value: str | None) -> str:
    return (value or "").strip().upper()


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().upper()


def _public_trace(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key in _TRACE_PUBLIC_KEYS:
            out[key] = val
    return out


def _extract_candidate_traces(metadata: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Return candidate_traces list when present and well-typed; else None (legacy)."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("candidate_traces")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    traces: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            traces.append(_public_trace(item))
    return traces


def _decision_has_detail(metadata: dict[str, Any] | None) -> bool:
    """Compat: True iff candidate_traces key was persisted (even if empty list)."""
    traces = _extract_candidate_traces(metadata)
    return traces is not None


def _public_targets(targets: Any) -> list[dict[str, Any]]:
    if not isinstance(targets, list):
        return []
    out: list[dict[str, Any]] = []
    for item in targets:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for key in (
            "ticker",
            "instrument_id",
            "rank",
            "action",
            "policy",
            "target_weight",
            "predicted_return_20d",
        ):
            if key in item:
                row[key] = item[key]
        if row:
            out.append(row)
    return out


def _order_plan_rows(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    plan = metadata.get("order_plan")
    if not isinstance(plan, dict):
        return []
    rows = plan.get("rows")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for key in (
            "ticker",
            "instrument_id",
            "rank",
            "action",
            "reason",
            "lot_size",
            "lots_delta",
            "units_delta",
            "target_weight",
            "current_weight",
            "estimated_notional",
            "estimated_fee",
        ):
            if key in item:
                row[key] = item[key]
        if row:
            out.append(row)
    return out


def classify_evidence_level(
    decision: ShadowDecision | None,
    *,
    orders: list[ShadowOrder] | None = None,
) -> EvidenceLevel:
    """Multi-level evidence without inventing missing why-codes."""
    if decision is None:
        return "NONE"
    meta = decision.metadata_ if isinstance(decision.metadata_, dict) else {}
    traces = _extract_candidate_traces(meta)
    if traces is not None and len(traces) > 0:
        return "FULL"
    # Empty candidate_traces list still means the V3 field existed.
    if traces is not None:
        targets = _public_targets(decision.targets)
        if targets or orders or _order_plan_rows(meta):
            return "PARTIAL"
        return "LIMITED"

    targets = _public_targets(decision.targets)
    plan_rows = _order_plan_rows(meta)
    if targets or plan_rows or orders:
        return "PARTIAL"
    if decision.policy_name or decision.risk_name or meta:
        return "LIMITED"
    return "NONE"


def evidence_message_ru(level: EvidenceLevel, *, detail_available: bool) -> str | None:
    if level == "FULL" and detail_available:
        return None
    if level == "PARTIAL":
        return PARTIAL_EVIDENCE_MESSAGE_RU
    if level == "LIMITED":
        return LIMITED_EVIDENCE_MESSAGE_RU
    if level == "NONE":
        return NONE_EVIDENCE_MESSAGE_RU
    # FULL with empty traces edge — keep legacy wording for compat consumers.
    return LEGACY_TRACE_MESSAGE_RU if not detail_available else None


def _serialize_fill(fill: ShadowFill) -> dict[str, Any]:
    return {
        "id": int(fill.id),
        "order_id": int(fill.order_id),
        "instrument_id": int(fill.instrument_id),
        "ticker": fill.ticker,
        "side": fill.side,
        "quantity": float(fill.quantity),
        "raw_open": float(fill.raw_open),
        "fill_price": float(fill.fill_price),
        "notional": float(fill.notional),
        "commission": float(fill.commission or 0.0),
        "slippage_cost": float(fill.slippage_cost or 0.0),
        "execution_date": fill.execution_date.isoformat(),
        "filled_at": _iso_dt(fill.filled_at),
        "decision_at": _iso_dt(fill.decision_at),
    }


def _execution_timing(
    *,
    signal_day: date | None,
    status: str,
    fills: list[ShadowFill],
) -> ExecutionTiming:
    status_u = _normalize_status(status)
    if fills:
        if signal_day is None:
            return "later"
        dates = {f.execution_date for f in fills}
        if dates == {signal_day}:
            return "same_day"
        return "later"
    if status_u in _FILLED_STATUSES:
        return "status_fill_mismatch"
    return "none"


def _serialize_order(
    order: ShadowOrder,
    *,
    fills: list[ShadowFill],
    signal_day: date | None,
) -> dict[str, Any]:
    fills_sorted = sorted(fills, key=lambda f: (f.execution_date, int(f.id)))
    timing = _execution_timing(signal_day=signal_day, status=order.status, fills=fills_sorted)
    return {
        "id": int(order.id),
        "decision_id": int(order.decision_id),
        "instrument_id": int(order.instrument_id),
        "ticker": order.ticker,
        "side": order.side,
        "quantity": float(order.quantity),
        "target_weight": float(order.target_weight),
        "target_notional": float(order.target_notional),
        "reason": order.reason,
        "status": order.status,
        "rank": order.rank,
        "predicted_return_20d": order.predicted_return_20d,
        "eligible_count": order.eligible_count,
        "decision_at": _iso_dt(order.decision_at),
        "min_execution_date": order.min_execution_date.isoformat()
        if order.min_execution_date
        else None,
        "execution_date": _iso_date(order.execution_date),
        "metadata": order.metadata_ or {},
        "fills": [_serialize_fill(f) for f in fills_sorted],
        "has_confirmed_fill": bool(fills_sorted),
        "execution_timing": timing,
    }


def _serialize_nav(nav: ShadowNavDaily | None) -> dict[str, Any] | None:
    if nav is None:
        return None
    return {
        "as_of_date": nav.as_of_date.isoformat(),
        "cash": float(nav.cash),
        "market_value": float(nav.market_value),
        "nav": float(nav.nav),
        "gross_exposure": float(nav.gross_exposure),
        "drawdown": float(nav.drawdown),
        "peak_nav": float(nav.peak_nav),
        "position_count": int(nav.position_count),
        "benchmark_value": nav.benchmark_value,
    }


def _serialize_decision_summary(decision: ShadowDecision) -> dict[str, Any]:
    return {
        "id": int(decision.id),
        "forward_batch_id": int(decision.forward_batch_id),
        "signal_as_of_date": decision.signal_as_of_date.isoformat(),
        "signal_generated_at": _iso_dt(decision.signal_generated_at),
        "decision_at": _iso_dt(decision.decision_at),
        "iso_week": decision.iso_week,
        "risk_mode": decision.risk_mode,
        "exposure_cap": float(decision.exposure_cap),
        "policy_name": decision.policy_name,
        "risk_name": decision.risk_name,
        "targets": _public_targets(decision.targets),
    }


def _action_matches(filter_action: str, *, decision_action: str | None, order_side: str | None) -> bool:
    fa = _normalize_action(filter_action)
    if not fa:
        return True
    da = _normalize_action(decision_action)
    side = _normalize_action(order_side)
    if da == fa or side == fa:
        return True
    if da.startswith(fa + "_") or da.startswith(fa + "-"):
        return True
    return False


def _ticker_matches(filter_ticker: str, *tickers: str | None) -> bool:
    ft = _normalize_ticker(filter_ticker)
    if not ft:
        return True
    return any(_normalize_ticker(t) == ft for t in tickers if t)


def _count_actions(
    candidates: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, int]:
    buy = sell = hold = review = 0
    for c in candidates:
        action = _normalize_action(str(c.get("decision_action") or ""))
        if action in {"BUY", "ENTER"} or action.startswith("ENTER"):
            buy += 1
        elif action in {"SELL", "EXIT", "ROTATE"} or action.startswith("EXIT"):
            sell += 1
        elif action.startswith("REVIEW"):
            review += 1
        elif action.startswith("HOLD") or action == "SKIP":
            hold += 1

    buy_orders = sell_orders = 0
    filled_orders = cancelled_orders = pending_orders = rejected_orders = 0
    fill_records = 0
    for o in orders:
        side = _normalize_action(str(o.get("side") or ""))
        if side == "BUY":
            buy_orders += 1
        elif side == "SELL":
            sell_orders += 1
        status = _normalize_status(str(o.get("status") or ""))
        fills = o.get("fills") if isinstance(o.get("fills"), list) else []
        fill_records += len(fills)
        if fills:
            filled_orders += 1
        elif status in _CANCELLED_STATUSES:
            cancelled_orders += 1
        elif status in _REJECTED_STATUSES:
            rejected_orders += 1
        elif status in _PENDING_STATUSES or status == "":
            pending_orders += 1
        elif status in _FILLED_STATUSES:
            # Status claims fill but no ShadowFill — count neither as confirmed fill.
            pass
        else:
            pending_orders += 1

    # Compat buy/sell: prefer candidate actions; else order sides (labelled as orders in UI).
    if not candidates:
        buy = buy_orders
        sell = sell_orders

    return {
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "review": review,
        "candidates_reviewed": len(candidates),
        "orders": len(orders),
        "buy_orders": buy_orders,
        "sell_orders": sell_orders,
        "filled_orders": filled_orders,
        "cancelled_orders": cancelled_orders,
        "pending_orders": pending_orders,
        "rejected_orders": rejected_orders,
        "fill_records": fill_records,
        "fills": fill_records,
    }


def _modeled_costs(fills: list[dict[str, Any]]) -> dict[str, float]:
    commission = sum(float(f.get("commission") or 0.0) for f in fills)
    slippage = sum(float(f.get("slippage_cost") or 0.0) for f in fills)
    return {
        "commission": commission,
        "slippage_cost": slippage,
        "total": commission + slippage,
    }


def _recorded_facts(
    decision: ShadowDecision | None,
    *,
    evidence_level: EvidenceLevel,
    orders_ser: list[dict[str, Any]],
) -> dict[str, Any]:
    if decision is None:
        return {
            "evidence_level": evidence_level,
            "has_candidate_traces": False,
            "targets": [],
            "order_plan_rows": [],
            "policy_name": None,
            "risk_name": None,
            "risk_mode": None,
            "order_reasons": [],
        }
    meta = decision.metadata_ if isinstance(decision.metadata_, dict) else {}
    reasons = sorted(
        {
            str(o.get("reason")).strip()
            for o in orders_ser
            if o.get("reason") is not None and str(o.get("reason")).strip()
        }
    )
    return {
        "evidence_level": evidence_level,
        "has_candidate_traces": _decision_has_detail(meta),
        "targets": _public_targets(decision.targets),
        "order_plan_rows": _order_plan_rows(meta),
        "policy_name": decision.policy_name,
        "risk_name": decision.risk_name,
        "risk_mode": decision.risk_mode,
        "eligible_n": meta.get("eligible_n"),
        "k_entry": meta.get("k_entry"),
        "k_max": meta.get("k_max"),
        "order_reasons": reasons,
    }


def build_shadow_journal(
    session: Session,
    *,
    portfolio_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 60,
    ticker: str | None = None,
    action: str | None = None,
) -> dict[str, Any] | None:
    """Joined Decision Journal for one portfolio. ``None`` if portfolio missing."""
    portfolio = session.get(ShadowPortfolio, portfolio_id)
    if portfolio is None:
        return None

    limit = max(1, min(int(limit), 365))
    filter_ticker = _normalize_ticker(ticker) if ticker else ""
    filter_action = _normalize_action(action) if action else ""

    decision_q = select(ShadowDecision).where(ShadowDecision.portfolio_id == portfolio_id)
    if date_from is not None:
        decision_q = decision_q.where(ShadowDecision.signal_as_of_date >= date_from)
    if date_to is not None:
        decision_q = decision_q.where(ShadowDecision.signal_as_of_date <= date_to)
    decisions = list(
        session.scalars(
            decision_q.order_by(ShadowDecision.signal_as_of_date.asc(), ShadowDecision.id.asc())
        )
    )

    # Calendar-window fills (for fill-only days / same-day cost rollups).
    fill_q = select(ShadowFill).where(ShadowFill.portfolio_id == portfolio_id)
    if date_from is not None:
        fill_q = fill_q.where(ShadowFill.execution_date >= date_from)
    if date_to is not None:
        fill_q = fill_q.where(ShadowFill.execution_date <= date_to)
    if filter_ticker:
        fill_q = fill_q.where(ShadowFill.ticker == filter_ticker)
    window_fills = list(
        session.scalars(fill_q.order_by(ShadowFill.execution_date.asc(), ShadowFill.id.asc()))
    )

    order_q = select(ShadowOrder).where(ShadowOrder.portfolio_id == portfolio_id)
    if filter_ticker:
        order_q = order_q.where(ShadowOrder.ticker == filter_ticker)
    if date_from is not None or date_to is not None:
        decision_ids = [int(d.id) for d in decisions]
        fill_order_ids = [int(f.order_id) for f in window_fills]
        id_filters = []
        if decision_ids:
            id_filters.append(ShadowOrder.decision_id.in_(decision_ids))
        if fill_order_ids:
            id_filters.append(ShadowOrder.id.in_(fill_order_ids))
        if id_filters:
            order_q = order_q.where(or_(*id_filters))
        else:
            order_q = order_q.where(ShadowOrder.id == -1)
    orders = list(session.scalars(order_q.order_by(ShadowOrder.id.asc())))

    # Batch-load ALL fills for displayed orders (may be outside the calendar window).
    order_ids = [int(o.id) for o in orders]
    linked_fills: list[ShadowFill] = []
    if order_ids:
        linked_fills = list(
            session.scalars(
                select(ShadowFill)
                .where(
                    ShadowFill.portfolio_id == portfolio_id,
                    ShadowFill.order_id.in_(order_ids),
                )
                .order_by(ShadowFill.execution_date.asc(), ShadowFill.id.asc())
            )
        )

    fills_by_order: dict[int, list[ShadowFill]] = {}
    for fill in linked_fills:
        # Defend against cross-portfolio leakage even if query is scoped.
        if int(fill.portfolio_id) != int(portfolio_id):
            continue
        fills_by_order.setdefault(int(fill.order_id), []).append(fill)

    nav_q = select(ShadowNavDaily).where(ShadowNavDaily.portfolio_id == portfolio_id)
    if date_from is not None:
        nav_q = nav_q.where(ShadowNavDaily.as_of_date >= date_from)
    if date_to is not None:
        nav_q = nav_q.where(ShadowNavDaily.as_of_date <= date_to)
    nav_rows = list(session.scalars(nav_q.order_by(ShadowNavDaily.as_of_date.asc())))

    orders_by_decision: dict[int, list[ShadowOrder]] = {}
    for order in orders:
        orders_by_decision.setdefault(int(order.decision_id), []).append(order)

    fills_by_date: dict[date, list[ShadowFill]] = {}
    for fill in window_fills:
        fills_by_date.setdefault(fill.execution_date, []).append(fill)

    nav_by_date: dict[date, ShadowNavDaily] = {n.as_of_date: n for n in nav_rows}
    decisions_by_date: dict[date, list[ShadowDecision]] = {}
    for d in decisions:
        decisions_by_date.setdefault(d.signal_as_of_date, []).append(d)

    day_set: set[date] = set(decisions_by_date) | set(fills_by_date) | set(nav_by_date)
    if date_from is not None:
        day_set = {d for d in day_set if d >= date_from}
    if date_to is not None:
        day_set = {d for d in day_set if d <= date_to}

    days_out: list[dict[str, Any]] = []
    for day in sorted(day_set):
        day_decisions = decisions_by_date.get(day, [])
        day_fills_raw = fills_by_date.get(day, [])
        day_nav = nav_by_date.get(day)

        day_orders_raw: list[ShadowOrder] = []
        seen_order_ids: set[int] = set()
        for decision in day_decisions:
            for order in orders_by_decision.get(int(decision.id), []):
                oid = int(order.id)
                if oid not in seen_order_ids:
                    seen_order_ids.add(oid)
                    day_orders_raw.append(order)
        for fill in day_fills_raw:
            order = next((o for o in orders if int(o.id) == int(fill.order_id)), None)
            if order is not None and int(order.id) not in seen_order_ids:
                seen_order_ids.add(int(order.id))
                day_orders_raw.append(order)

        primary = day_decisions[-1] if day_decisions else None
        detail_available = (
            _decision_has_detail(primary.metadata_) if primary is not None else False
        )
        traces_raw = (
            _extract_candidate_traces(primary.metadata_) if primary is not None else None
        )
        candidates: list[dict[str, Any]] = list(traces_raw) if traces_raw is not None else []
        evidence_level = classify_evidence_level(primary, orders=day_orders_raw)

        if filter_ticker or filter_action:
            cand_hit = [
                c
                for c in candidates
                if _ticker_matches(filter_ticker, str(c.get("ticker") or ""))
                and _action_matches(
                    filter_action,
                    decision_action=str(c.get("decision_action") or "") or None,
                    order_side=None,
                )
            ]
            order_hit = [
                o
                for o in day_orders_raw
                if _ticker_matches(filter_ticker, o.ticker)
                and _action_matches(
                    filter_action,
                    decision_action=None,
                    order_side=o.side,
                )
            ]
            fill_hit = [
                f
                for f in day_fills_raw
                if _ticker_matches(filter_ticker, f.ticker)
                and _action_matches(filter_action, decision_action=None, order_side=f.side)
            ]
            if not cand_hit and not order_hit and not fill_hit:
                continue
            candidates = cand_hit
            day_orders_raw = order_hit
            day_fills_raw = fill_hit

        signal_day = primary.signal_as_of_date if primary is not None else day
        orders_ser = [
            _serialize_order(
                o,
                fills=fills_by_order.get(int(o.id), []),
                signal_day=signal_day if primary is not None else None,
            )
            for o in day_orders_raw
        ]
        # Day-level fills: calendar fills for this date (unchanged source dates).
        fills_ser = [_serialize_fill(f) for f in day_fills_raw]
        # Costs for decision-centric view: prefer linked fills on orders of this day.
        linked_fill_ser = [f for o in orders_ser for f in (o.get("fills") or [])]
        costs_source = linked_fill_ser if primary is not None and linked_fill_ser else fills_ser
        counts = _count_actions(candidates, orders_ser)

        day_payload: dict[str, Any] = {
            "date": day.isoformat(),
            "signal_as_of_date": primary.signal_as_of_date.isoformat() if primary else None,
            "decision": _serialize_decision_summary(primary) if primary else None,
            "decision_ids": [int(d.id) for d in day_decisions],
            "risk_mode": primary.risk_mode if primary else None,
            "nav": _serialize_nav(day_nav),
            "detail_available": bool(detail_available) if primary is not None else False,
            "evidence_level": evidence_level if primary is not None else "NONE",
            "message_ru": evidence_message_ru(
                evidence_level if primary is not None else "NONE",
                detail_available=bool(detail_available) if primary is not None else False,
            ),
            "recorded_facts": _recorded_facts(
                primary, evidence_level=evidence_level, orders_ser=orders_ser
            ),
            "candidates": candidates,
            "orders": orders_ser,
            "fills": fills_ser,
            "counts": counts,
            "total_modeled_costs": _modeled_costs(costs_source),
        }
        days_out.append(day_payload)

    truncated = len(days_out) > limit
    if truncated:
        days_out = days_out[-limit:]

    return {
        "portfolio_id": int(portfolio_id),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "limit": limit,
        "ticker": filter_ticker or None,
        "action": filter_action or None,
        "returned_days": len(days_out),
        "truncated": truncated,
        "order": "asc_by_date",
        "days": days_out,
    }


def build_candidate_history(
    session: Session,
    *,
    portfolio_id: int,
    ticker: str,
    limit: int = 100,
) -> dict[str, Any] | None:
    """Lifecycle of one ticker across Shadow decisions for a portfolio."""
    portfolio = session.get(ShadowPortfolio, portfolio_id)
    if portfolio is None:
        return None

    ticker_norm = _normalize_ticker(ticker)
    if not ticker_norm:
        return {
            "portfolio_id": int(portfolio_id),
            "ticker": ticker,
            "events": [],
            "summary": {"first_seen": None, "last_seen": None, "event_count": 0},
        }

    limit = max(1, min(int(limit), 500))

    decisions = list(
        session.scalars(
            select(ShadowDecision)
            .where(ShadowDecision.portfolio_id == portfolio_id)
            .order_by(ShadowDecision.signal_as_of_date.asc(), ShadowDecision.id.asc())
        )
    )
    from sqlalchemy import func as sa_func

    orders = list(
        session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio_id,
                sa_func.upper(ShadowOrder.ticker) == ticker_norm,
            )
        )
    )

    fills = list(
        session.scalars(
            select(ShadowFill).where(
                ShadowFill.portfolio_id == portfolio_id,
                sa_func.upper(ShadowFill.ticker) == ticker_norm,
            )
        )
    )
    fills_by_order: dict[int, list[ShadowFill]] = {}
    for f in fills:
        fills_by_order.setdefault(int(f.order_id), []).append(f)
    orders_by_decision: dict[int, list[ShadowOrder]] = {}
    for order in orders:
        orders_by_decision.setdefault(int(order.decision_id), []).append(order)

    nav_rows = {
        n.as_of_date: n
        for n in session.scalars(
            select(ShadowNavDaily).where(ShadowNavDaily.portfolio_id == portfolio_id)
        )
    }

    events: list[dict[str, Any]] = []
    for decision in decisions:
        meta = decision.metadata_ or {}
        traces = _extract_candidate_traces(meta)
        matching_traces = [
            t
            for t in (traces or [])
            if _normalize_ticker(str(t.get("ticker") or "")) == ticker_norm
        ]
        matching_orders = orders_by_decision.get(int(decision.id), [])

        if not matching_traces and not matching_orders:
            continue

        evidence = classify_evidence_level(decision, orders=matching_orders)

        if matching_traces:
            for trace in matching_traces:
                order = matching_orders[0] if matching_orders else None
                order_fills = fills_by_order.get(int(order.id), []) if order is not None else []
                events.append(
                    {
                        "decision_id": int(decision.id),
                        "iso_week": decision.iso_week,
                        "signal_as_of_date": decision.signal_as_of_date.isoformat(),
                        "decision_at": _iso_dt(decision.decision_at),
                        "action": trace.get("decision_action"),
                        "rank": trace.get("rank"),
                        "reason_codes": trace.get("reason_codes") or [],
                        "replacement_ticker": trace.get("replacement_ticker"),
                        "net_edge": trace.get("net_edge"),
                        "sell_fee_estimate": trace.get("sell_fee_estimate"),
                        "buy_fee_estimate": trace.get("buy_fee_estimate"),
                        "slippage_estimate": trace.get("slippage_estimate"),
                        "review_trigger": trace.get("review_trigger"),
                        "trace": trace,
                        "detail_available": True,
                        "evidence_level": evidence,
                        "message_ru": None,
                        "order": _serialize_order(
                            order,
                            fills=order_fills,
                            signal_day=decision.signal_as_of_date,
                        )
                        if order
                        else None,
                        "fill": _serialize_fill(order_fills[0]) if order_fills else None,
                        "nav_at_signal": _serialize_nav(nav_rows.get(decision.signal_as_of_date)),
                    }
                )
        else:
            for order in matching_orders:
                order_fills = fills_by_order.get(int(order.id), [])
                events.append(
                    {
                        "decision_id": int(decision.id),
                        "iso_week": decision.iso_week,
                        "signal_as_of_date": decision.signal_as_of_date.isoformat(),
                        "decision_at": _iso_dt(decision.decision_at),
                        "action": order.side,
                        "rank": order.rank,
                        "reason_codes": [order.reason] if order.reason else [],
                        "replacement_ticker": None,
                        "net_edge": None,
                        "sell_fee_estimate": None,
                        "buy_fee_estimate": None,
                        "slippage_estimate": None,
                        "review_trigger": None,
                        "trace": None,
                        "detail_available": False,
                        "evidence_level": evidence,
                        "message_ru": evidence_message_ru(evidence, detail_available=False),
                        "order": _serialize_order(
                            order,
                            fills=order_fills,
                            signal_day=decision.signal_as_of_date,
                        ),
                        "fill": _serialize_fill(order_fills[0]) if order_fills else None,
                        "nav_at_signal": _serialize_nav(nav_rows.get(decision.signal_as_of_date)),
                    }
                )

    truncated = len(events) > limit
    if truncated:
        events = events[-limit:]

    first_seen = events[0]["signal_as_of_date"] if events else None
    last_seen = events[-1]["signal_as_of_date"] if events else None
    any_detail = any(bool(e.get("detail_available")) for e in events)

    return {
        "portfolio_id": int(portfolio_id),
        "ticker": ticker_norm,
        "detail_available": any_detail if events else False,
        "message_ru": None
        if (any_detail or not events)
        else LEGACY_TRACE_MESSAGE_RU,
        "returned_events": len(events),
        "truncated": truncated,
        "order": "asc_by_signal_date",
        "events": events,
        "summary": {
            "first_seen": first_seen,
            "last_seen": last_seen,
            "event_count": len(events),
        },
    }
