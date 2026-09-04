"""Historical next-open execution adapter."""

from __future__ import annotations

from app.domain.ports.execution import ExecutionAdapter, HistoricalFill, OrderIntent


class HistoricalNextOpenAdapter(ExecutionAdapter):
    """Fill at next daily OPEN ± slippage; commission on abs(notional).

    No partial fills, no market impact, no lot constraints (fractional research).
    """

    def fill(
        self,
        intent: OrderIntent,
        *,
        raw_open: float | None,
        commission_bps: float,
        slippage_bps: float,
    ) -> HistoricalFill | None:
        if raw_open is None or raw_open <= 0 or intent.quantity == 0:
            return None
        slip = float(slippage_bps) / 10_000.0
        commission_rate = float(commission_bps) / 10_000.0
        if intent.side == "BUY":
            fill_price = raw_open * (1.0 + slip)
        else:
            fill_price = raw_open * (1.0 - slip)
        qty = abs(float(intent.quantity))
        notional = qty * fill_price
        commission = abs(notional) * commission_rate
        slippage_cost = abs(qty * (fill_price - raw_open))
        return HistoricalFill(
            execution_date=intent.execution_date,
            instrument_id=intent.instrument_id,
            ticker=intent.ticker,
            side=intent.side,
            quantity=qty,
            raw_open=float(raw_open),
            fill_price=fill_price,
            notional=notional,
            commission=commission,
            slippage_cost=slippage_cost,
            decision_date=intent.decision_date,
            metadata=dict(intent.metadata or {}),
        )
