"""Lot-aware cash-safe Shadow order plan (framework-free, Decimal)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from app.modules.investment.domain.fixed_income import TransactionCostProfile

Side = Literal["BUY", "SELL"]
PlanAction = Literal["BUY", "SELL", "SKIP"]


@dataclass(frozen=True, slots=True)
class PlanInstrument:
    instrument_id: int
    ticker: str
    target_weight: Decimal
    current_units: Decimal
    price: Decimal | None
    lot_size: int | None
    rank: int | None = None
    priority: int | None = None  # lower = earlier for buys


@dataclass(frozen=True, slots=True)
class PlanRow:
    instrument_id: int
    ticker: str
    action: PlanAction
    lots_delta: int
    units_delta: Decimal
    target_weight: Decimal
    current_weight: Decimal
    estimated_price: Decimal | None
    estimated_notional: Decimal
    estimated_fee: Decimal
    lot_size: int | None
    reason: str
    rank: int | None = None


@dataclass(slots=True)
class OrderPlan:
    starting_cash: Decimal
    strategic_cash_reserve: Decimal
    rows: list[PlanRow] = field(default_factory=list)
    projected_cash: Decimal = Decimal("0")
    fees_total: Decimal = Decimal("0")
    sell_proceeds: Decimal = Decimal("0")
    buy_notional: Decimal = Decimal("0")
    rounding_remainder: Decimal = Decimal("0")
    diagnostics: list[str] = field(default_factory=list)

    @property
    def executable(self) -> list[PlanRow]:
        return [r for r in self.rows if r.action in ("BUY", "SELL") and r.units_delta > 0]

    @property
    def skipped(self) -> list[PlanRow]:
        return [r for r in self.rows if r.action == "SKIP"]


def _d(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _weight(units: Decimal, price: Decimal | None, nav: Decimal) -> Decimal:
    if price is None or price <= 0 or nav <= 0:
        return Decimal("0")
    return (units * price) / nav


def _floor_lots(units: Decimal, lot_size: int) -> int:
    if lot_size <= 0:
        return 0
    return int((units / Decimal(lot_size)).to_integral_value(rounding=ROUND_FLOOR))


def build_lot_order_plan(
    instruments: list[PlanInstrument],
    *,
    cash: Decimal,
    nav: Decimal,
    costs: TransactionCostProfile,
    strategic_cash_reserve: Decimal = Decimal("0"),
) -> OrderPlan:
    """Deterministic sell-then-buy integer-lot plan. Never returns negative projected cash."""
    if cash < 0:
        raise ValueError("cash must be non-negative")
    if strategic_cash_reserve < 0:
        raise ValueError("strategic_cash_reserve must be non-negative")

    plan = OrderPlan(
        starting_cash=cash,
        strategic_cash_reserve=strategic_cash_reserve,
        projected_cash=cash,
    )
    working_cash = cash
    reserved = min(strategic_cash_reserve, working_cash)
    allocable = working_cash - reserved

    # Working units map (apply sells then buys).
    units: dict[int, Decimal] = {i.instrument_id: _d(i.current_units) for i in instruments}
    by_id = {i.instrument_id: i for i in instruments}

    # --- Sells first (stable ticker order among equals) ---
    sell_candidates = sorted(
        instruments,
        key=lambda i: (i.ticker.upper(), i.instrument_id),
    )
    for inst in sell_candidates:
        px = inst.price
        tw = _d(inst.target_weight)
        cur = units[inst.instrument_id]
        cw = _weight(cur, px, nav)

        if px is None or px <= 0:
            if cur > 0 and tw <= 0:
                plan.rows.append(
                    PlanRow(
                        instrument_id=inst.instrument_id,
                        ticker=inst.ticker,
                        action="SKIP",
                        lots_delta=0,
                        units_delta=Decimal("0"),
                        target_weight=tw,
                        current_weight=cw,
                        estimated_price=None,
                        estimated_notional=Decimal("0"),
                        estimated_fee=Decimal("0"),
                        lot_size=inst.lot_size,
                        reason="NO_EXECUTION_PRICE",
                        rank=inst.rank,
                    )
                )
            continue

        if inst.lot_size is None or inst.lot_size <= 0:
            if cur > 0 and tw < cw:
                plan.rows.append(
                    PlanRow(
                        instrument_id=inst.instrument_id,
                        ticker=inst.ticker,
                        action="SKIP",
                        lots_delta=0,
                        units_delta=Decimal("0"),
                        target_weight=tw,
                        current_weight=cw,
                        estimated_price=px,
                        estimated_notional=Decimal("0"),
                        estimated_fee=Decimal("0"),
                        lot_size=None,
                        reason="UNKNOWN_LOT_SIZE",
                        rank=inst.rank,
                    )
                )
            continue

        lot_size = int(inst.lot_size)
        target_units = (nav * tw / px).to_integral_value(rounding=ROUND_FLOOR)
        # Align target to lots
        target_lots = _floor_lots(target_units, lot_size)
        target_units = Decimal(target_lots * lot_size)
        current_lots = _floor_lots(cur, lot_size)
        # If current has non-lot dust (legacy), only sell whole lots
        sellable_lots = current_lots
        desired_lots = target_lots
        if desired_lots >= sellable_lots:
            # no sell
            continue
        lots_delta = sellable_lots - desired_lots
        if lots_delta <= 0:
            continue
        units_delta = Decimal(lots_delta * lot_size)
        exec_px = costs.execution_price(px, "SELL")
        notional = exec_px * units_delta
        fee = costs.fee(notional)
        proceeds = notional - fee
        if proceeds < 0:
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=px,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=lot_size,
                    reason="INSUFFICIENT_CASH_AFTER_FEES",
                    rank=inst.rank,
                )
            )
            continue

        units[inst.instrument_id] = cur - units_delta
        working_cash += proceeds
        allocable += proceeds
        plan.sell_proceeds += proceeds
        plan.fees_total += fee
        plan.rows.append(
            PlanRow(
                instrument_id=inst.instrument_id,
                ticker=inst.ticker,
                action="SELL",
                lots_delta=lots_delta,
                units_delta=units_delta,
                target_weight=tw,
                current_weight=cw,
                estimated_price=exec_px,
                estimated_notional=notional,
                estimated_fee=fee,
                lot_size=lot_size,
                reason="REBALANCE_SELL",
                rank=inst.rank,
            )
        )

    # --- Buys: priority = rank (asc), then -target_weight, then ticker ---
    buy_candidates = sorted(
        instruments,
        key=lambda i: (
            i.priority if i.priority is not None else (i.rank if i.rank is not None else 10**9),
            -_d(i.target_weight),
            i.ticker.upper(),
            i.instrument_id,
        ),
    )
    for inst in buy_candidates:
        px = inst.price
        tw = _d(inst.target_weight)
        cur = units[inst.instrument_id]
        cw = _weight(cur, px, nav)

        if tw <= 0:
            if cur <= 0:
                # nothing to do
                continue
            # sell path already handled exits; leftover non-lot dust → skip note
            continue

        if px is None or px <= 0:
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=None,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=inst.lot_size,
                    reason="NO_EXECUTION_PRICE",
                    rank=inst.rank,
                )
            )
            continue

        if inst.lot_size is None or inst.lot_size <= 0:
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=px,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=None,
                    reason="UNKNOWN_LOT_SIZE",
                    rank=inst.rank,
                )
            )
            continue

        lot_size = int(inst.lot_size)
        target_units = (nav * tw / px).to_integral_value(rounding=ROUND_FLOOR)
        target_lots = _floor_lots(target_units, lot_size)
        current_lots = _floor_lots(cur, lot_size)
        need_lots = target_lots - current_lots
        if need_lots <= 0:
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=px,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=lot_size,
                    reason="NO_REBALANCE_REQUIRED" if target_lots == current_lots else "BELOW_ONE_LOT",
                    rank=inst.rank,
                )
            )
            continue

        exec_px = costs.execution_price(px, "BUY")
        lot_notional = exec_px * Decimal(lot_size)
        # Cap by target need and allocable cash (keep strategic reserve)
        max_by_cash = 0
        if lot_notional > 0 and allocable > 0:
            from app.modules.investment.domain.fixed_income import affordable_lots

            max_by_cash = affordable_lots(allocable, lot_notional, costs)
        lots = min(need_lots, max_by_cash)
        if lots <= 0:
            reason = (
                "INSUFFICIENT_CASH_FOR_ONE_LOT"
                if lot_notional + costs.fee(lot_notional) > allocable
                else "BELOW_ONE_LOT"
            )
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=exec_px,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=lot_size,
                    reason=reason,
                    rank=inst.rank,
                )
            )
            continue

        units_delta = Decimal(lots * lot_size)
        notional = exec_px * units_delta
        fee = costs.fee(notional)
        used = notional + fee
        if used > allocable + Decimal("0.0000001"):
            plan.rows.append(
                PlanRow(
                    instrument_id=inst.instrument_id,
                    ticker=inst.ticker,
                    action="SKIP",
                    lots_delta=0,
                    units_delta=Decimal("0"),
                    target_weight=tw,
                    current_weight=cw,
                    estimated_price=exec_px,
                    estimated_notional=Decimal("0"),
                    estimated_fee=Decimal("0"),
                    lot_size=lot_size,
                    reason="INSUFFICIENT_CASH_AFTER_FEES",
                    rank=inst.rank,
                )
            )
            continue

        units[inst.instrument_id] = cur + units_delta
        working_cash -= used
        allocable -= used
        plan.buy_notional += notional
        plan.fees_total += fee
        plan.rows.append(
            PlanRow(
                instrument_id=inst.instrument_id,
                ticker=inst.ticker,
                action="BUY",
                lots_delta=lots,
                units_delta=units_delta,
                target_weight=tw,
                current_weight=cw,
                estimated_price=exec_px,
                estimated_notional=notional,
                estimated_fee=fee,
                lot_size=lot_size,
                reason="REBALANCE_BUY",
                rank=inst.rank,
            )
        )

    plan.projected_cash = working_cash
    plan.rounding_remainder = max(Decimal("0"), working_cash - reserved)
    if plan.projected_cash < 0:
        plan.diagnostics.append("projected_cash_negative")
        raise AssertionError("lot plan invariant violated: negative projected cash")

    # Validate executable rows are lot-aligned
    for row in plan.executable:
        assert row.lot_size and row.lot_size > 0
        assert int(row.units_delta) % row.lot_size == 0
        assert row.units_delta == Decimal(row.lots_delta * row.lot_size)

    _ = by_id  # reserved for future weight reconciliation
    return plan
