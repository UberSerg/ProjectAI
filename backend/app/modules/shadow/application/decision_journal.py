"""Shadow Decision Journal read models (Decision → traces → Orders → Fills → NAV).

Read-only. Does not invent fills or candidate traces. Legacy decisions without
``candidate_traces`` degrade with an honest ``detail_available=false`` flag.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowFill,
    ShadowNavDaily,
    ShadowOrder,
    ShadowPortfolio,
)

LEGACY_TRACE_MESSAGE_RU = (
    "Подробный decision trace для этой исторической версии не сохранялся."
)

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
    traces = _extract_candidate_traces(metadata)
    return traces is not None


def _serialize_order(order: ShadowOrder) -> dict[str, Any]:
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
        "min_execution_date": order.min_execution_date.isoformat(),
        "execution_date": _iso_date(order.execution_date),
        "metadata": order.metadata_ or {},
    }


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
        "targets": decision.targets or [],
    }


def _action_matches(filter_action: str, *, decision_action: str | None, order_side: str | None) -> bool:
    fa = _normalize_action(filter_action)
    if not fa:
        return True
    da = _normalize_action(decision_action)
    side = _normalize_action(order_side)
    if da == fa or side == fa:
        return True
    # REVIEW matches REVIEW_HOLD / REVIEW_TRIGGER etc.
    if da.startswith(fa + "_") or da.startswith(fa + "-"):
        return True
    return False


def _ticker_matches(filter_ticker: str, *tickers: str | None) -> bool:
    ft = _normalize_ticker(filter_ticker)
    if not ft:
        return True
    return any(_normalize_ticker(t) == ft for t in tickers if t)


def _count_actions(candidates: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, int]:
    buy = sell = hold = review = 0
    for c in candidates:
        action = _normalize_action(str(c.get("decision_action") or ""))
        if action in {"BUY", "ENTER"}:
            buy += 1
        elif action in {"SELL", "EXIT", "ROTATE"}:
            sell += 1
        elif action.startswith("REVIEW"):
            review += 1
        elif action.startswith("HOLD") or action == "SKIP":
            hold += 1
    # Fall back to orders when traces absent
    if not candidates:
        for o in orders:
            side = _normalize_action(str(o.get("side") or ""))
            if side == "BUY":
                buy += 1
            elif side == "SELL":
                sell += 1
    return {
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "review": review,
        "candidates_reviewed": len(candidates),
        "orders": len(orders),
    }


def _modeled_costs(fills: list[dict[str, Any]]) -> dict[str, float]:
    commission = sum(float(f.get("commission") or 0.0) for f in fills)
    slippage = sum(float(f.get("slippage_cost") or 0.0) for f in fills)
    return {
        "commission": commission,
        "slippage_cost": slippage,
        "total": commission + slippage,
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

    decisions = list(
        session.scalars(
            select(ShadowDecision)
            .where(ShadowDecision.portfolio_id == portfolio_id)
            .order_by(ShadowDecision.signal_as_of_date.asc(), ShadowDecision.id.asc())
        )
    )
    orders = list(
        session.scalars(
            select(ShadowOrder)
            .where(ShadowOrder.portfolio_id == portfolio_id)
            .order_by(ShadowOrder.id.asc())
        )
    )
    fills = list(
        session.scalars(
            select(ShadowFill)
            .where(ShadowFill.portfolio_id == portfolio_id)
            .order_by(ShadowFill.execution_date.asc(), ShadowFill.id.asc())
        )
    )
    nav_rows = list(
        session.scalars(
            select(ShadowNavDaily)
            .where(ShadowNavDaily.portfolio_id == portfolio_id)
            .order_by(ShadowNavDaily.as_of_date.asc())
        )
    )

    orders_by_decision: dict[int, list[ShadowOrder]] = {}
    for order in orders:
        orders_by_decision.setdefault(int(order.decision_id), []).append(order)

    fills_by_date: dict[date, list[ShadowFill]] = {}
    for fill in fills:
        fills_by_date.setdefault(fill.execution_date, []).append(fill)

    nav_by_date: dict[date, ShadowNavDaily] = {n.as_of_date: n for n in nav_rows}
    decisions_by_date: dict[date, list[ShadowDecision]] = {}
    for d in decisions:
        decisions_by_date.setdefault(d.signal_as_of_date, []).append(d)

    # Days = union of decision signal dates, fill execution dates, NAV dates
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

        # Orders linked to decisions on this signal day OR filled today
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
        detail_available = _decision_has_detail(primary.metadata_ if primary else None)
        traces_raw = (
            _extract_candidate_traces(primary.metadata_) if primary is not None else None
        )
        candidates: list[dict[str, Any]] = list(traces_raw) if traces_raw is not None else []

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

        orders_ser = [_serialize_order(o) for o in day_orders_raw]
        fills_ser = [_serialize_fill(f) for f in day_fills_raw]
        counts = _count_actions(candidates, orders_ser)
        counts["fills"] = len(fills_ser)

        day_payload: dict[str, Any] = {
            "date": day.isoformat(),
            "signal_as_of_date": primary.signal_as_of_date.isoformat() if primary else None,
            "decision": _serialize_decision_summary(primary) if primary else None,
            "decision_ids": [int(d.id) for d in day_decisions],
            "risk_mode": primary.risk_mode if primary else None,
            "nav": _serialize_nav(day_nav),
            "detail_available": bool(detail_available) if primary is not None else False,
            "message_ru": None
            if (primary is None or detail_available)
            else LEGACY_TRACE_MESSAGE_RU,
            "candidates": candidates,
            "orders": orders_ser,
            "fills": fills_ser,
            "counts": counts,
            "total_modeled_costs": _modeled_costs(fills_ser),
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
    orders = list(
        session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio_id,
                ShadowOrder.ticker == ticker_norm,
            )
        )
    )
    # Also match case-insensitive via Python if DB collation is sensitive
    if not orders:
        all_orders = list(
            session.scalars(
                select(ShadowOrder).where(ShadowOrder.portfolio_id == portfolio_id)
            )
        )
        orders = [o for o in all_orders if _normalize_ticker(o.ticker) == ticker_norm]

    fills = list(
        session.scalars(
            select(ShadowFill).where(ShadowFill.portfolio_id == portfolio_id)
        )
    )
    fills_by_order = {
        int(f.order_id): f
        for f in fills
        if _normalize_ticker(f.ticker) == ticker_norm
    }
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

        if matching_traces:
            for trace in matching_traces:
                order = matching_orders[0] if matching_orders else None
                fill = fills_by_order.get(int(order.id)) if order is not None else None
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
                        "message_ru": None,
                        "order": _serialize_order(order) if order else None,
                        "fill": _serialize_fill(fill) if fill else None,
                        "nav_at_signal": _serialize_nav(nav_rows.get(decision.signal_as_of_date)),
                    }
                )
        else:
            # Legacy: orders only, honest degradation
            for order in matching_orders:
                fill = fills_by_order.get(int(order.id))
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
                        "message_ru": LEGACY_TRACE_MESSAGE_RU,
                        "order": _serialize_order(order),
                        "fill": _serialize_fill(fill) if fill else None,
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
