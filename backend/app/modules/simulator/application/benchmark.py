"""IMOEX price-index benchmark alignment."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.simulator.application.market_view import MarketView


def imoex_price_series(
    market: MarketView,
    *,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Price index series on intersection of portfolio dates with IMOEX closes."""
    if market.imoex_id is None:
        return []
    out: list[dict[str, Any]] = []
    for d in market.trading_days:
        if d < start or d > end:
            continue
        px = market.imoex_close(d)
        if px is None:
            continue
        out.append({"date": d.isoformat(), "close": px})
    return out


def imoex_price_return(series: list[dict[str, Any]]) -> dict[str, Any]:
    if len(series) < 2:
        return {
            "benchmark_type": "IMOEX_PRICE_INDEX",
            "total_price_return": None,
            "note": "insufficient overlapping IMOEX days",
            "dividend_treatment": "price index; dividends excluded",
        }
    first = float(series[0]["close"])
    last = float(series[-1]["close"])
    ret = (last / first) - 1.0 if first else None
    return {
        "benchmark_type": "IMOEX_PRICE_INDEX",
        "date_from": series[0]["date"],
        "date_to": series[-1]["date"],
        "points": len(series),
        "initial_close": first,
        "final_close": last,
        "total_price_return": ret,
        "note": "INDEX BENCHMARK — not an investable ETF simulation",
        "dividend_treatment": "price index; dividends excluded (aligned with Simulator V0)",
    }
