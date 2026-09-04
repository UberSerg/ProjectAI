"""In-memory portfolio ledger with chronological audit trail."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.domain.ports.execution import HistoricalFill, OrderIntent


@dataclass
class PositionState:
    instrument_id: int
    ticker: str
    quantity: float = 0.0


@dataclass
class DailySnapshot:
    as_of: date
    cash: float
    nav: float
    gross_exposure: float
    cash_weight: float
    positions: dict[int, dict[str, Any]]
    peak_nav: float
    drawdown: float


@dataclass
class PortfolioLedger:
    cash: float
    positions: dict[int, PositionState] = field(default_factory=dict)
    pending_intents: list[OrderIntent] = field(default_factory=list)
    fills: list[HistoricalFill] = field(default_factory=list)
    orders: list[OrderIntent] = field(default_factory=list)
    ca_events: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[DailySnapshot] = field(default_factory=list)
    peak_nav: float = 0.0
    rebalance_count: int = 0

    def position_qty(self, instrument_id: int) -> float:
        pos = self.positions.get(instrument_id)
        return 0.0 if pos is None else pos.quantity

    def set_position(self, instrument_id: int, ticker: str, quantity: float) -> None:
        if abs(quantity) < 1e-12:
            self.positions.pop(instrument_id, None)
            return
        self.positions[instrument_id] = PositionState(
            instrument_id=instrument_id, ticker=ticker, quantity=quantity
        )

    def market_value(self, closes: dict[int, float | None]) -> float:
        total = 0.0
        for iid, pos in self.positions.items():
            px = closes.get(iid)
            if px is None:
                continue
            total += pos.quantity * px
        return total

    def nav(self, closes: dict[int, float | None]) -> float:
        return self.cash + self.market_value(closes)

    def record_snapshot(self, as_of: date, closes: dict[int, float | None]) -> DailySnapshot:
        mv = self.market_value(closes)
        nav = self.cash + mv
        if self.peak_nav <= 0:
            self.peak_nav = nav
        self.peak_nav = max(self.peak_nav, nav)
        dd = 0.0 if self.peak_nav <= 0 else (nav / self.peak_nav) - 1.0
        gross = 0.0 if nav <= 0 else mv / nav
        cash_w = 0.0 if nav <= 0 else self.cash / nav
        positions: dict[int, dict[str, Any]] = {}
        for iid, pos in self.positions.items():
            px = closes.get(iid)
            mkt = None if px is None else pos.quantity * px
            w = None if (mkt is None or nav <= 0) else mkt / nav
            positions[iid] = {
                "instrument_id": iid,
                "ticker": pos.ticker,
                "quantity": pos.quantity,
                "market_price": px,
                "market_value": mkt,
                "weight": w,
            }
        snap = DailySnapshot(
            as_of=as_of,
            cash=self.cash,
            nav=nav,
            gross_exposure=gross,
            cash_weight=cash_w,
            positions=positions,
            peak_nav=self.peak_nav,
            drawdown=dd,
        )
        self.snapshots.append(snap)
        return snap
