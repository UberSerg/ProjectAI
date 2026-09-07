"""Intraday session-open fill path for Shadow PENDING orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ports.execution import OrderIntent
from app.domain.ports.intraday_market import IntradayQuote
from app.modules.shadow.domain.open_execution import (
    EXECUTION_PRICE_TYPE,
    POLICY_NAME,
    QUOTE_SOURCE,
    can_fill_with_session_open,
)
from app.modules.shadow.infrastructure.models import (
    ShadowFill,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter


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


@dataclass(slots=True, frozen=True)
class PendingOrderReason:
    order_id: int
    portfolio_id: int
    ticker: str
    reason: str
    session_date: str | None = None
    delayed_observation: bool = False


@dataclass(slots=True)
class OpenExecutionResult:
    filled: int = 0
    skipped: int = 0
    reasons: list[PendingOrderReason] | None = None

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _quote_index(
    quotes: list[IntradayQuote],
    *,
    instrument_by_secid: dict[tuple[str, str], int] | None = None,
) -> dict[int, IntradayQuote]:
    """Map instrument_id → quote when instrument_id present or via lookup."""
    out: dict[int, IntradayQuote] = {}
    for q in quotes:
        if q.instrument_id is not None:
            out[int(q.instrument_id)] = q
            continue
        if instrument_by_secid is not None:
            key = (q.board.upper(), q.secid.upper())
            iid = instrument_by_secid.get(key)
            if iid is not None:
                out[int(iid)] = q
    return out


def fill_pending_orders_with_session_open(
    session: Session,
    *,
    quotes: list[IntradayQuote],
    instrument_by_secid: dict[tuple[str, str], int] | None = None,
    now: datetime | None = None,
    portfolio_ids: list[int] | None = None,
) -> OpenExecutionResult:
    """Attempt OPEN fills for PENDING shadow orders using intraday quotes.

    Does not use LAST as execution price. Candle-based `_fill_pending_orders`
    remains the historical/backfill path.
    """
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    by_instrument = _quote_index(quotes, instrument_by_secid=instrument_by_secid)
    result = OpenExecutionResult()
    adapter = HistoricalNextOpenAdapter()

    order_q = select(ShadowOrder).where(ShadowOrder.status == "PENDING")
    if portfolio_ids is not None:
        order_q = order_q.where(ShadowOrder.portfolio_id.in_(portfolio_ids))
    # Sells first for cash consistency.
    pending = sorted(
        list(session.scalars(order_q)),
        key=lambda o: (0 if o.side == "SELL" else 1, int(o.id)),
    )

    for order in pending:
        # Lock order row when dialect supports it.
        locked = session.scalar(
            select(ShadowOrder).where(ShadowOrder.id == order.id).with_for_update()
        )
        if locked is None or locked.status != "PENDING":
            continue
        order = locked

        existing_fill = session.scalar(select(ShadowFill).where(ShadowFill.order_id == order.id))
        if existing_fill is not None:
            result.skipped += 1
            result.reasons.append(
                PendingOrderReason(
                    order_id=int(order.id),
                    portfolio_id=int(order.portfolio_id),
                    ticker=order.ticker,
                    reason="ALREADY_FILLED",
                )
            )
            continue

        quote = by_instrument.get(int(order.instrument_id))
        if quote is None:
            result.skipped += 1
            result.reasons.append(
                PendingOrderReason(
                    order_id=int(order.id),
                    portfolio_id=int(order.portfolio_id),
                    ticker=order.ticker,
                    reason="QUOTE_UNAVAILABLE",
                )
            )
            continue

        session_date = quote.trading_date
        if session_date is None:
            result.skipped += 1
            result.reasons.append(
                PendingOrderReason(
                    order_id=int(order.id),
                    portfolio_id=int(order.portfolio_id),
                    ticker=order.ticker,
                    reason="OPEN_PRICE_NOT_AVAILABLE",
                )
            )
            continue

        eligibility = can_fill_with_session_open(
            order_created_at=order.created_at,
            min_execution_date=order.min_execution_date,
            session_date=session_date,
            open_price=quote.open_price,
            market_status=quote.market_status,
            quote_freshness=quote.freshness,
            observed_at=quote.observed_at,
            now=clock,
        )
        if not eligibility.eligible:
            result.skipped += 1
            result.reasons.append(
                PendingOrderReason(
                    order_id=int(order.id),
                    portfolio_id=int(order.portfolio_id),
                    ticker=order.ticker,
                    reason=eligibility.reason,
                    session_date=session_date.isoformat(),
                    delayed_observation=eligibility.delayed_observation,
                )
            )
            continue

        portfolio = session.get(ShadowPortfolio, order.portfolio_id)
        if portfolio is None:
            result.skipped += 1
            continue
        spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
        if spec is None:
            result.skipped += 1
            continue

        raw_open = float(quote.open_price)  # type: ignore[arg-type]
        intent = OrderIntent(
            decision_date=order.decision_at.date(),
            execution_date=session_date,
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
            result.skipped += 1
            result.reasons.append(
                PendingOrderReason(
                    order_id=int(order.id),
                    portfolio_id=int(order.portfolio_id),
                    ticker=order.ticker,
                    reason="OPEN_PRICE_NOT_AVAILABLE",
                    session_date=session_date.isoformat(),
                )
            )
            continue

        if order.side == "BUY":
            cost = fill.notional + fill.commission
            if cost > float(portfolio.cash) + 1e-6:
                result.skipped += 1
                result.reasons.append(
                    PendingOrderReason(
                        order_id=int(order.id),
                        portfolio_id=int(order.portfolio_id),
                        ticker=order.ticker,
                        reason="INSUFFICIENT_CASH",
                        session_date=session_date.isoformat(),
                    )
                )
                continue
            portfolio.cash = float(portfolio.cash) - cost
            new_qty = _position_qty(portfolio, int(order.instrument_id)) + fill.quantity
            _set_position(portfolio, int(order.instrument_id), order.ticker, new_qty)
        else:
            sell_qty = min(fill.quantity, _position_qty(portfolio, int(order.instrument_id)))
            if sell_qty <= 0:
                order.status = "CANCELLED"
                order.updated_at = clock
                result.skipped += 1
                result.reasons.append(
                    PendingOrderReason(
                        order_id=int(order.id),
                        portfolio_id=int(order.portfolio_id),
                        ticker=order.ticker,
                        reason="NO_POSITION_TO_SELL",
                        session_date=session_date.isoformat(),
                    )
                )
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

        filled_at = quote.observed_at
        metadata: dict[str, Any] = {
            "kind": "FORWARD_SHADOW",
            "execution_price_type": EXECUTION_PRICE_TYPE,
            "policy": POLICY_NAME,
            "source": QUOTE_SOURCE,
            "board": quote.board,
            "observed_at": quote.observed_at.isoformat(),
            "delayed_observation": bool(eligibility.delayed_observation),
            "session_date": session_date.isoformat(),
            "raw_open_source": "intraday_quote.open",
        }
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
                execution_date=session_date,
                decision_at=order.decision_at,
                filled_at=filled_at,
                metadata_=metadata,
            )
        )
        order.status = "FILLED"
        order.execution_date = session_date
        order.updated_at = clock
        if portfolio.status == "WAITING_FOR_FUTURE_MARKET_OPEN":
            remaining = session.scalar(
                select(ShadowOrder.id).where(
                    ShadowOrder.portfolio_id == portfolio.id,
                    ShadowOrder.status == "PENDING",
                    ShadowOrder.id != order.id,
                )
            )
            if remaining is None:
                portfolio.status = "DECISION_READY"
        portfolio.updated_at = clock
        result.filled += 1
        result.reasons.append(
            PendingOrderReason(
                order_id=int(order.id),
                portfolio_id=int(order.portfolio_id),
                ticker=order.ticker,
                reason="FILLED",
                session_date=session_date.isoformat(),
                delayed_observation=bool(eligibility.delayed_observation),
            )
        )
    return result
