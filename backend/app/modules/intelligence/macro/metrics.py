"""Pure deterministic macro metric helpers (no I/O, no look-ahead)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date


def simple_return(closes: Sequence[float], window: int) -> float | None:
    """Close[t] / close[t-window] - 1. Requires len(closes) >= window + 1."""
    if window <= 0 or len(closes) < window + 1:
        return None
    base = float(closes[-(window + 1)])
    last = float(closes[-1])
    if base == 0.0:
        return None
    return last / base - 1.0


def realized_vol_log(closes: Sequence[float], window: int, *, ddof: int = 1) -> float | None:
    """Sample std of the last ``window`` daily log returns (needs window+1 closes)."""
    if window <= 0 or len(closes) < window + 1:
        return None
    rets: list[float] = []
    for i in range(len(closes) - window, len(closes)):
        prev = float(closes[i - 1])
        cur = float(closes[i])
        if prev <= 0.0 or cur <= 0.0:
            return None
        rets.append(math.log(cur / prev))
    if len(rets) < 2 and ddof > 0:
        return None
    mean = sum(rets) / len(rets)
    denom = len(rets) - ddof
    if denom <= 0:
        return None
    var = sum((r - mean) ** 2 for r in rets) / denom
    return math.sqrt(var)


def series_level_change(
    points: Sequence[tuple[date, float]],
    *,
    as_of: date,
    lookback_days: int,
) -> tuple[float | None, date | None, date | None]:
    """Absolute change vs latest point on/before (as_of - lookback_days).

    Returns (change, from_date, to_date). Points must be sorted ascending and
    already filtered to <= as_of.
    """
    if not points:
        return None, None, None
    latest_date, latest_value = points[-1]
    cutoff = date.fromordinal(as_of.toordinal() - lookback_days)
    baseline: tuple[date, float] | None = None
    for d, v in points:
        if d <= cutoff:
            baseline = (d, v)
        else:
            break
    if baseline is None:
        # Fall back to first available observation in the window (still <= as_of).
        baseline = points[0]
    if baseline[0] == latest_date:
        return 0.0, baseline[0], latest_date
    return float(latest_value) - float(baseline[1]), baseline[0], latest_date


def last_nonzero_change(
    points: Sequence[tuple[date, float]],
) -> tuple[float | None, date | None]:
    """Most recent non-zero level change (policy move)."""
    if len(points) < 2:
        return None, None
    for i in range(len(points) - 1, 0, -1):
        chg = float(points[i][1]) - float(points[i - 1][1])
        if chg != 0.0:
            return chg, points[i][0]
    return 0.0, points[-1][0]


def pct_change_from_levels(
    points: Sequence[tuple[date, float]],
    window_obs: int,
) -> float | None:
    """Simple pct change using the observation ``window_obs`` steps back."""
    if window_obs <= 0 or len(points) < window_obs + 1:
        return None
    base = float(points[-(window_obs + 1)][1])
    last = float(points[-1][1])
    if base == 0.0:
        return None
    return last / base - 1.0


def breadth_advance_share(returns: Sequence[float | None]) -> tuple[float | None, int]:
    """Share of names with positive return among those with a defined return."""
    usable = [r for r in returns if r is not None]
    if not usable:
        return None, 0
    advances = sum(1 for r in usable if r > 0.0)
    return advances / len(usable), len(usable)
