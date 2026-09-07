"""Regression: HistoricalNextOpenAdapter.fill (not .fills)."""

from __future__ import annotations

from datetime import date

from app.domain.ports.execution import OrderIntent
from app.modules.simulator.application.execution import HistoricalNextOpenAdapter


def test_historical_next_open_adapter_fill_method_exists() -> None:
    adapter = HistoricalNextOpenAdapter()
    assert hasattr(adapter, "fill")
    assert not hasattr(adapter, "fills")
    assert callable(adapter.fill)


def test_historical_next_open_adapter_fill_buy() -> None:
    adapter = HistoricalNextOpenAdapter()
    intent = OrderIntent(
        decision_date=date(2026, 9, 4),
        execution_date=date(2026, 9, 5),
        instrument_id=1,
        ticker="SBER",
        side="BUY",
        target_weight=0.1,
        target_notional=10_000.0,
        quantity=100.0,
        reason="test",
    )
    fill = adapter.fill(intent, raw_open=100.0, commission_bps=10, slippage_bps=20)
    assert fill is not None
    assert fill.raw_open == 100.0
    assert fill.fill_price == 100.0 * (1.0 + 0.002)
    assert fill.quantity == 100.0
