"""Tests for lot-aware Shadow order plan and accounting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.shadow.domain.accounting import apply_buy, apply_sell, empty_position
from app.modules.shadow.domain.lot_plan import PlanInstrument, build_lot_order_plan


COSTS0 = TransactionCostProfile(Decimal("0"))
COSTS5 = TransactionCostProfile(Decimal("5"))


def test_lot_sizes_1_100_1000() -> None:
    nav = Decimal("100000")
    cash = Decimal("100000")
    instruments = [
        PlanInstrument(1, "ONE", Decimal("0.30"), Decimal("0"), Decimal("100"), 1, rank=1),
        PlanInstrument(2, "HUN", Decimal("0.30"), Decimal("0"), Decimal("10"), 100, rank=2),
        PlanInstrument(3, "THO", Decimal("0.30"), Decimal("0"), Decimal("1"), 1000, rank=3),
    ]
    plan = build_lot_order_plan(instruments, cash=cash, nav=nav, costs=COSTS0)
    buys = {r.ticker: r for r in plan.executable if r.action == "BUY"}
    assert buys["ONE"].units_delta == Decimal("300")  # 300 lots × 1
    assert buys["HUN"].units_delta == Decimal("3000")  # 30 lots × 100
    assert buys["THO"].units_delta == Decimal("30000")  # 30 lots × 1000
    assert all(int(r.units_delta) % int(r.lot_size) == 0 for r in plan.executable)
    assert plan.projected_cash >= 0


def test_unknown_lot_size_skips() -> None:
    plan = build_lot_order_plan(
        [PlanInstrument(1, "X", Decimal("0.5"), Decimal("0"), Decimal("10"), None, rank=1)],
        cash=Decimal("10000"),
        nav=Decimal("10000"),
        costs=COSTS0,
    )
    assert plan.executable == []
    assert plan.skipped[0].reason == "UNKNOWN_LOT_SIZE"


def test_insufficient_cash_for_one_lot() -> None:
    plan = build_lot_order_plan(
        [PlanInstrument(1, "EXP", Decimal("1.0"), Decimal("0"), Decimal("900"), 100, rank=1)],
        cash=Decimal("1000"),
        nav=Decimal("100000"),
        costs=COSTS0,
    )
    assert plan.executable == []
    assert plan.skipped[0].reason == "INSUFFICIENT_CASH_FOR_ONE_LOT"


def test_fees_reduce_affordable_lots() -> None:
    # Without fees: 10 lots of 100u @ 10 = 10000
    # With 5bps fees, last lot may not fit
    plan = build_lot_order_plan(
        [PlanInstrument(1, "SBER", Decimal("1.0"), Decimal("0"), Decimal("10"), 100, rank=1)],
        cash=Decimal("10000"),
        nav=Decimal("10000"),
        costs=COSTS5,
    )
    assert len(plan.executable) == 1
    assert plan.executable[0].lots_delta < 10 or plan.projected_cash >= 0
    assert plan.projected_cash >= 0
    used = plan.buy_notional + plan.fees_total
    assert used <= Decimal("10000")


def test_sell_then_buy_no_negative_cash() -> None:
    # Hold 10 lots of A, target 0; buy B with proceeds
    instruments = [
        PlanInstrument(1, "AAA", Decimal("0"), Decimal("1000"), Decimal("10"), 100, rank=2),
        PlanInstrument(2, "BBB", Decimal("0.5"), Decimal("0"), Decimal("10"), 100, rank=1),
    ]
    plan = build_lot_order_plan(
        instruments,
        cash=Decimal("100"),
        nav=Decimal("10100"),
        costs=COSTS0,
    )
    assert any(r.action == "SELL" for r in plan.executable)
    assert any(r.action == "BUY" for r in plan.executable)
    assert plan.projected_cash >= 0


def test_priority_buys_higher_rank_first() -> None:
    # Cash only enough for one of two identical-priced targets
    instruments = [
        PlanInstrument(1, "LOW", Decimal("0.5"), Decimal("0"), Decimal("100"), 1, rank=2),
        PlanInstrument(2, "HIGH", Decimal("0.5"), Decimal("0"), Decimal("100"), 1, rank=1),
    ]
    plan = build_lot_order_plan(
        instruments,
        cash=Decimal("5000"),
        nav=Decimal("10000"),
        costs=COSTS0,
    )
    buys = [r for r in plan.executable if r.action == "BUY"]
    assert buys[0].ticker == "HIGH"


def test_accounting_buy_partial_sell() -> None:
    s = apply_buy(None, units=Decimal("200"), fill_price=Decimal("10"), lot_size=100)
    assert s.lots == 2
    assert s.avg_entry == Decimal("10")
    s2, realized = apply_sell(s, units=Decimal("100"), fill_price=Decimal("12"))
    assert s2.lots == 1
    assert s2.quantity == Decimal("100")
    assert realized == Decimal("200")
    s3, realized2 = apply_sell(s2, units=Decimal("100"), fill_price=Decimal("9"))
    assert s3.quantity == 0
    assert realized2 == Decimal("-100")
    assert s3.realized_pnl == Decimal("100")


def test_accounting_rejects_non_lot_units() -> None:
    with pytest.raises(ValueError):
        apply_buy(None, units=Decimal("50"), fill_price=Decimal("10"), lot_size=100)
