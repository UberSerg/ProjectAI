"""Portfolio performance metrics from simulator NAV (not ML IC)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.simulator.application.ledger import DailySnapshot, PortfolioLedger


@dataclass(frozen=True, slots=True)
class DrawdownInfo:
    max_drawdown: float
    peak_date: date | None
    trough_date: date | None
    recovery_date: date | None


def compute_drawdown(snapshots: list[DailySnapshot]) -> DrawdownInfo:
    if not snapshots:
        return DrawdownInfo(0.0, None, None, None)
    peak = snapshots[0].nav
    peak_date = snapshots[0].as_of
    max_dd = 0.0
    trough_date = snapshots[0].as_of
    max_peak_date = peak_date
    recovery: date | None = None
    for snap in snapshots:
        if snap.nav > peak:
            peak = snap.nav
            peak_date = snap.as_of
        dd = (snap.nav / peak) - 1.0 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            trough_date = snap.as_of
            max_peak_date = peak_date
            recovery = None
        elif max_dd < 0 and recovery is None and snap.nav >= peak and snap.as_of > trough_date:
            # recovered relative to running peak after trough — approximate
            recovery = snap.as_of
    # Recovery: first day after trough where NAV >= peak NAV at start of that DD episode
    if max_dd < 0:
        recovery = None
        peak_at_episode = None
        for snap in snapshots:
            if snap.as_of == max_peak_date:
                peak_at_episode = snap.nav
                break
        if peak_at_episode is not None:
            for snap in snapshots:
                if snap.as_of > trough_date and snap.nav >= peak_at_episode - 1e-9:
                    recovery = snap.as_of
                    break
    return DrawdownInfo(max_dd, max_peak_date, trough_date, recovery)


def compute_metrics(ledger: PortfolioLedger, *, initial_capital: float) -> dict[str, Any]:
    snaps = ledger.snapshots
    if not snaps:
        return {
            "initial_nav": initial_capital,
            "final_nav": initial_capital,
            "total_price_return": 0.0,
            "note": "no snapshots",
        }
    navs = [s.nav for s in snaps]
    initial = snaps[0].nav
    final = snaps[-1].nav
    total_return = (final / initial) - 1.0 if initial else 0.0
    n_days = max(1, len(navs) - 1)
    years = n_days / 252.0
    cagr = None
    if years >= 0.25 and initial > 0 and final > 0:
        cagr = (final / initial) ** (1.0 / years) - 1.0

    rets: list[float] = []
    for i in range(1, len(navs)):
        if navs[i - 1] > 0:
            rets.append(navs[i] / navs[i - 1] - 1.0)
    vol = None
    sharpe = None
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        daily_vol = math.sqrt(var)
        vol = daily_vol * math.sqrt(252.0)
        if daily_vol > 0:
            sharpe = (mean / daily_vol) * math.sqrt(252.0)  # rf=0 research metric

    dd = compute_drawdown(snaps)
    turnover = 0.0
    for fill in ledger.fills:
        # turnover ≈ sum(|notional|) / (2 * average NAV) optional; report gross traded / avg NAV
        turnover += fill.notional
    avg_nav = sum(navs) / len(navs)
    turnover_ratio = (turnover / avg_nav) if avg_nav else 0.0

    avg_gross = sum(s.gross_exposure for s in snaps) / len(snaps)
    avg_cash = sum(s.cash_weight for s in snaps) / len(snaps)

    return {
        "initial_nav": initial,
        "final_nav": final,
        "total_price_return": total_return,
        "cagr": cagr,
        "annualized_volatility": vol,
        "sharpe_rf0": sharpe,
        "sharpe_note": "Sharpe (rf=0 research metric); not broker realism",
        "max_drawdown": dd.max_drawdown,
        "max_drawdown_peak_date": dd.peak_date.isoformat() if dd.peak_date else None,
        "max_drawdown_trough_date": dd.trough_date.isoformat() if dd.trough_date else None,
        "max_drawdown_recovery_date": dd.recovery_date.isoformat() if dd.recovery_date else None,
        "turnover_notional": turnover,
        "turnover_ratio": turnover_ratio,
        "trade_count": len(ledger.fills),
        "rebalance_count": ledger.rebalance_count,
        "average_gross_exposure": avg_gross,
        "average_cash_weight": avg_cash,
        "trading_days": len(snaps),
        "dividend_cash": False,
        "return_type": "price_return",
        "trade_win_rate_note": (
            "Trade-level realized PnL deferred: incremental rebalancing makes "
            "closed-lot win rate ambiguous; prefer portfolio/rebalance metrics."
        ),
    }
