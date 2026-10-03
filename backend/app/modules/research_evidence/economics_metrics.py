"""Metrics for the long-only research economics simulator (PRICE_RETURN)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from app.modules.simulator.application.ledger import DailySnapshot, PortfolioLedger

MIN_ANNUALIZE_YEARS = 0.25
MIN_VOL_OBSERVATIONS = 2
TRADING_DAYS_PER_YEAR = 252.0


def _drawdown(snapshots: list[DailySnapshot]) -> float:
    if not snapshots:
        return 0.0
    peak = snapshots[0].nav
    max_dd = 0.0
    for snap in snapshots:
        if snap.nav > peak:
            peak = snap.nav
        if peak > 0:
            dd = (snap.nav / peak) - 1.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _daily_returns(snapshots: list[DailySnapshot]) -> list[float]:
    rets: list[float] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1].nav
        if prev > 0:
            rets.append(snapshots[i].nav / prev - 1.0)
    return rets


def compute_research_metrics(
    ledger: PortfolioLedger,
    *,
    initial_capital: float,
    include_sharpe_rf0_research: bool = False,
) -> dict[str, Any]:
    snaps = ledger.snapshots
    start_nav = float(snaps[0].nav) if snaps else float(initial_capital)
    end_nav = float(snaps[-1].nav) if snaps else float(initial_capital)
    cumulative = (end_nav / start_nav - 1.0) if start_nav else None

    n_days = max(0, len(snaps) - 1)
    years = n_days / TRADING_DAYS_PER_YEAR if n_days else 0.0
    annualized_return: float | None
    annualized_return_reason: str | None
    if cumulative is None or start_nav <= 0 or end_nav <= 0:
        annualized_return = None
        annualized_return_reason = "non-positive NAV; annualized return not defined"
    elif years < MIN_ANNUALIZE_YEARS:
        annualized_return = None
        annualized_return_reason = (
            f"horizon {years:.4f}y < {MIN_ANNUALIZE_YEARS}y; annualized return not meaningful"
        )
    else:
        annualized_return = (end_nav / start_nav) ** (1.0 / years) - 1.0
        annualized_return_reason = None

    rets = _daily_returns(snaps)
    annualized_vol: float | None
    annualized_vol_reason: str | None
    if len(rets) < MIN_VOL_OBSERVATIONS:
        annualized_vol = None
        annualized_vol_reason = (
            f"fewer than {MIN_VOL_OBSERVATIONS} daily returns; volatility not meaningful"
        )
    else:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        annualized_vol = math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)
        annualized_vol_reason = None

    turnover_notional = sum(float(f.notional) for f in ledger.fills)
    avg_nav = (sum(s.nav for s in snaps) / len(snaps)) if snaps else 0.0
    turnover = (turnover_notional / avg_nav) if avg_nav else 0.0

    avg_holdings = 0.0
    avg_cash_weight = 0.0
    avg_gross = 0.0
    if snaps:
        avg_holdings = sum(
            sum(1 for p in s.positions.values() if abs(float(p.get("quantity") or 0.0)) > 1e-12)
            for s in snaps
        ) / len(snaps)
        avg_cash_weight = sum(s.cash_weight for s in snaps) / len(snaps)
        avg_gross = sum(s.gross_exposure for s in snaps) / len(snaps)

    total_cost = sum(float(f.commission) + float(f.slippage_cost) for f in ledger.fills)

    out: dict[str, Any] = {
        "start_nav": start_nav,
        "end_nav": end_nav,
        "cumulative_price_return": cumulative,
        "return_semantic": "PRICE_RETURN",
        "annualized_return": annualized_return,
        "annualized_return_reason": annualized_return_reason,
        "annualized_vol": annualized_vol,
        "annualized_vol_reason": annualized_vol_reason,
        "max_drawdown": _drawdown(snaps),
        "turnover": turnover,
        "turnover_notional": turnover_notional,
        "n_rebalances": int(ledger.rebalance_count),
        "n_trades": len(ledger.fills),
        "avg_holdings": avg_holdings,
        "avg_cash_weight": avg_cash_weight,
        "avg_gross_exposure": avg_gross,
        "assumed_cost_paid": total_cost,
        "start_date": snaps[0].as_of.isoformat() if snaps else None,
        "end_date": snaps[-1].as_of.isoformat() if snaps else None,
        "trading_sessions": len(snaps),
    }
    if include_sharpe_rf0_research:
        sharpe = None
        sharpe_reason = None
        if annualized_vol is None or annualized_vol <= 0 or not rets:
            sharpe_reason = "volatility not meaningful; SHARPE_RF0_RESEARCH omitted"
        else:
            mean = sum(rets) / len(rets)
            sharpe = (mean / math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))) * math.sqrt(
                TRADING_DAYS_PER_YEAR
            )
        out["SHARPE_RF0_RESEARCH"] = sharpe
        out["SHARPE_RF0_RESEARCH_assumption"] = (
            "rf=0; research metric on daily PRICE_RETURN NAV; not a broker Sharpe"
        )
        out["SHARPE_RF0_RESEARCH_reason"] = sharpe_reason
    return out


def cost_drag(*, gross_return: float | None, net_return: float | None) -> float | None:
    if gross_return is None or net_return is None:
        return None
    return float(gross_return) - float(net_return)


def snapshot_dates(ledger: PortfolioLedger) -> list[date]:
    return [s.as_of for s in ledger.snapshots]
