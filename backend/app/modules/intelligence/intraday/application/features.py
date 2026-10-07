"""PIT daily aggregation of 60m bars → IntradayFeatureSnapshotV1.

Only bars with Moscow calendar date == as_of are used.
No interpolation of missing hours. Missing inputs → None + coverage/limitations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.intelligence.contracts.snapshots_domain import IntradayFeatureSnapshotV1
from app.modules.intelligence.intraday.constants import (
    AFTERNOON_HOURS,
    COVERAGE_MISSING,
    COVERAGE_PARTIAL,
    COVERAGE_READY,
    FEATURE_SET_VERSION,
    FIRST_HOUR,
    LAST_MAIN_HOUR,
    MAIN_SESSION_HOURS,
    MIN_BARS_PARTIAL,
    MIN_BARS_READY,
    MORNING_HOURS,
    PRIMARY_INTERVAL,
)

MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True, slots=True)
class IntervalBar:
    """Normalized intraday bar for feature math."""

    begin_msk: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float | None = None

    @property
    def hour(self) -> int:
        return self.begin_msk.hour


def _f(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def bar_from_mapping(row: dict[str, Any]) -> IntervalBar | None:
    begin = row.get("begin_msk")
    if begin is None and row.get("timestamp") is not None:
        ts = row["timestamp"]
        if isinstance(ts, datetime):
            begin = ts.astimezone(MSK) if ts.tzinfo else ts.replace(tzinfo=UTC).astimezone(MSK)
    if not isinstance(begin, datetime):
        return None
    if begin.tzinfo is None:
        begin = begin.replace(tzinfo=MSK)
    else:
        begin = begin.astimezone(MSK)
    o = _f(row.get("open"))
    h = _f(row.get("high"))
    low = _f(row.get("low"))
    c = _f(row.get("close"))
    if c is None:
        return None
    o = o if o is not None else c
    h = h if h is not None else max(o, c)
    low = low if low is not None else min(o, c)
    vol = _f(row.get("volume")) or 0.0
    val = _f(row.get("value"))
    return IntervalBar(
        begin_msk=begin,
        open=o,
        high=h,
        low=low,
        close=c,
        volume=max(0.0, vol),
        value=val,
    )


def bars_for_as_of(bars: list[IntervalBar], as_of: date) -> list[IntervalBar]:
    day = [b for b in bars if b.begin_msk.date() == as_of]
    return sorted(day, key=lambda b: b.begin_msk)


def _by_hour(bars: list[IntervalBar]) -> dict[int, IntervalBar]:
    # Last write wins if duplicates (should not happen after dedupe).
    return {b.hour: b for b in bars}


def _ret(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a / b) - 1.0


def _bar_returns(bars: list[IntervalBar]) -> list[float]:
    out: list[float] = []
    for b in bars:
        if b.open == 0:
            continue
        out.append((b.close / b.open) - 1.0)
    return out


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _pick(by_hour: dict[int, IntervalBar], hours: tuple[int, ...]) -> IntervalBar | None:
    for h in hours:
        if h in by_hour:
            return by_hour[h]
    return None


def _session_vwap(bars: list[IntervalBar]) -> float | None:
    # Prefer official turnover/volume when present; else typical price * volume.
    num = 0.0
    den = 0.0
    for b in bars:
        if b.volume <= 0:
            continue
        if b.value is not None and b.value > 0:
            num += b.value
            den += b.volume
        else:
            typical = (b.high + b.low + b.close) / 3.0
            num += typical * b.volume
            den += b.volume
    if den <= 0:
        return None
    return num / den


def eod_known_at(as_of: date, last_bar: IntervalBar | None) -> datetime:
    """Earliest honest known_at for a completed as_of session (MSK EOD / last bar end)."""
    if last_bar is not None:
        # Bar covers [begin, begin+1h); available after that hour ends.
        end = last_bar.begin_msk + timedelta(hours=1)
        return end.astimezone(UTC)
    return datetime.combine(as_of, time(23, 59, 59), tzinfo=MSK).astimezone(UTC)


def compute_intraday_features(
    *,
    instrument_id: int,
    as_of: date,
    day_bars: list[IntervalBar],
    prev_close: float | None,
    interval: str = PRIMARY_INTERVAL,
    now_utc: datetime | None = None,
) -> IntradayFeatureSnapshotV1:
    """Aggregate one instrument/day. day_bars must already be filtered to as_of."""
    bars = sorted(day_bars, key=lambda b: b.begin_msk)
    limitations: list[str] = []
    features: dict[str, float | None] = {
        "overnight_gap": None,
        "open_to_close_return": None,
        "first_hour_return": None,
        "last_hour_return": None,
        "morning_return": None,
        "afternoon_return": None,
        "session_high_low_range": None,
        "realized_intraday_volatility": None,
        "intraday_return_std": None,
        "absolute_move_sum": None,
        "trend_efficiency": None,
        "close_vs_session_vwap": None,
        "close_location_in_range": None,
        "max_positive_bar": None,
        "max_negative_bar": None,
        "volume_first_hour_share": None,
        "volume_last_hour_share": None,
        "volume_concentration": None,
        "intraday_volume_zscore": None,
        "price_volume_confirmation": None,
        "morning_vs_afternoon_divergence": None,
        "intraday_reversal": None,
        "intraday_momentum": None,
    }

    if not bars:
        return IntradayFeatureSnapshotV1(
            instrument_id=instrument_id,
            as_of=as_of,
            known_at=eod_known_at(as_of, None),
            interval=interval,
            coverage_status=COVERAGE_MISSING,
            features=features,
            bars_used=0,
            limitations=("no_bars_for_as_of", f"feature_set={FEATURE_SET_VERSION}"),
        )

    by_hour = _by_hour(bars)
    main_bars = [b for b in bars if b.hour in MAIN_SESSION_HOURS]
    n_main = len(main_bars)
    now = now_utc or datetime.now(UTC)
    as_of_end = datetime.combine(as_of, time(23, 59, 59), tzinfo=MSK).astimezone(UTC)
    session_complete = now >= as_of_end

    if n_main >= MIN_BARS_READY and session_complete:
        coverage = COVERAGE_READY
    elif len(bars) >= MIN_BARS_PARTIAL:
        coverage = COVERAGE_PARTIAL
        if not session_complete:
            limitations.append("session_incomplete_or_partial")
        if n_main < MIN_BARS_READY:
            limitations.append(f"main_bars_{n_main}_lt_{MIN_BARS_READY}")
    else:
        coverage = COVERAGE_MISSING

    day_open = bars[0].open
    day_close = bars[-1].close
    day_high = max(b.high for b in bars)
    day_low = min(b.low for b in bars)
    total_vol = sum(b.volume for b in bars)

    features["overnight_gap"] = _ret(day_open, prev_close)
    if prev_close is None:
        limitations.append("prev_close_unavailable")

    features["open_to_close_return"] = _ret(day_close, day_open)
    if day_open and day_open > 0:
        features["session_high_low_range"] = (day_high - day_low) / day_open

    first = by_hour.get(FIRST_HOUR)
    last = by_hour.get(LAST_MAIN_HOUR) or _pick(by_hour, tuple(reversed(MAIN_SESSION_HOURS)))
    if first is not None:
        features["first_hour_return"] = _ret(first.close, first.open)
    else:
        limitations.append("missing_first_hour_bar")
    if last is not None:
        features["last_hour_return"] = _ret(last.close, last.open)
    else:
        limitations.append("missing_last_main_hour_bar")

    morning_bars = [by_hour[h] for h in MORNING_HOURS if h in by_hour]
    afternoon_bars = [by_hour[h] for h in AFTERNOON_HOURS if h in by_hour]
    if morning_bars:
        features["morning_return"] = _ret(morning_bars[-1].close, morning_bars[0].open)
    if afternoon_bars:
        features["afternoon_return"] = _ret(afternoon_bars[-1].close, afternoon_bars[0].open)

    bar_rets = _bar_returns(main_bars if main_bars else bars)
    features["intraday_return_std"] = _std(bar_rets)
    if bar_rets:
        features["absolute_move_sum"] = sum(abs(r) for r in bar_rets)
        features["max_positive_bar"] = max(bar_rets)
        features["max_negative_bar"] = min(bar_rets)
        abs_sum = features["absolute_move_sum"] or 0.0
        net = sum(bar_rets)
        features["trend_efficiency"] = (abs(net) / abs_sum) if abs_sum > 0 else None
        # Realized vol: std of bar returns scaled by sqrt(n) for session.
        std = features["intraday_return_std"]
        features["realized_intraday_volatility"] = (
            std * math.sqrt(len(bar_rets)) if std is not None else None
        )

    vwap = _session_vwap(bars)
    features["close_vs_session_vwap"] = _ret(day_close, vwap)
    span = day_high - day_low
    if span > 0:
        features["close_location_in_range"] = (day_close - day_low) / span
    else:
        features["close_location_in_range"] = None
        limitations.append("zero_range_session")

    if total_vol > 0:
        if first is not None:
            features["volume_first_hour_share"] = first.volume / total_vol
        if last is not None:
            features["volume_last_hour_share"] = last.volume / total_vol
        max_vol = max(b.volume for b in bars)
        features["volume_concentration"] = max_vol / total_vol
        vols = [b.volume for b in bars]
        vstd = _std(vols)
        vmean = sum(vols) / len(vols)
        if vstd is not None and vstd > 0:
            features["intraday_volume_zscore"] = (bars[-1].volume - vmean) / vstd

    morning_vol = sum(b.volume for b in morning_bars)
    afternoon_vol = sum(b.volume for b in afternoon_bars)
    otc = features["open_to_close_return"]
    if otc is not None and total_vol > 0:
        # Positive when price direction aligns with afternoon volume dominance.
        vol_skew = (afternoon_vol - morning_vol) / total_vol
        features["price_volume_confirmation"] = (1.0 if otc >= 0 else -1.0) * vol_skew

    mret = features["morning_return"]
    aret = features["afternoon_return"]
    if mret is not None and aret is not None:
        features["morning_vs_afternoon_divergence"] = mret - aret
        # Reversal: morning and afternoon have opposite signs.
        if mret * aret < 0:
            features["intraday_reversal"] = abs(aret) / (abs(mret) + abs(aret))
        else:
            features["intraday_reversal"] = 0.0

    fret = features["first_hour_return"]
    lret = features["last_hour_return"]
    if fret is not None and lret is not None:
        features["intraday_momentum"] = fret + lret
    elif otc is not None:
        features["intraday_momentum"] = otc

    limitations.append(f"feature_set={FEATURE_SET_VERSION}")
    return IntradayFeatureSnapshotV1(
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=eod_known_at(as_of, bars[-1]),
        interval=interval,
        coverage_status=coverage,
        features=features,
        bars_used=len(bars),
        limitations=tuple(limitations),
    )
