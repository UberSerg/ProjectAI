"""PIT intraday feature aggregation — synthetic bars, no network."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.modules.intelligence.intraday.application.features import (
    IntervalBar,
    compute_intraday_features,
)
from app.modules.intelligence.intraday.constants import COVERAGE_MISSING, COVERAGE_READY

MSK = ZoneInfo("Europe/Moscow")


def _bar(hour: int, o: float, h: float, low: float, c: float, vol: float, day: date = date(2024, 6, 3)) -> IntervalBar:
    begin = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=MSK)
    return IntervalBar(
        begin_msk=begin,
        open=o,
        high=h,
        low=low,
        close=c,
        volume=vol,
        value=c * vol,
    )


def _full_session() -> list[IntervalBar]:
    # Monotone up morning, down afternoon — for divergence/reversal.
    specs = [
        (10, 100.0, 101.0, 99.5, 100.5, 1000),
        (11, 100.5, 102.0, 100.0, 101.5, 1100),
        (12, 101.5, 103.0, 101.0, 102.5, 1200),
        (13, 102.5, 104.0, 102.0, 103.0, 1300),
        (14, 103.0, 103.5, 101.0, 101.5, 1400),
        (15, 101.5, 102.0, 100.0, 100.5, 1500),
        (16, 100.5, 101.0, 99.0, 99.5, 1600),
        (17, 99.5, 100.0, 98.5, 99.0, 1700),
        (18, 99.0, 99.5, 98.0, 98.5, 1800),
    ]
    return [_bar(h, o, hi, lo, c, v) for h, o, hi, lo, c, v in specs]


def test_missing_day_is_explicit() -> None:
    snap = compute_intraday_features(
        instrument_id=44,
        as_of=date(2024, 6, 3),
        day_bars=[],
        prev_close=100.0,
        now_utc=datetime(2024, 6, 4, 12, 0, tzinfo=UTC),
    )
    assert snap.coverage_status == COVERAGE_MISSING
    assert snap.bars_used == 0
    assert snap.features["open_to_close_return"] is None


def test_full_session_features_and_no_nan_interpolation() -> None:
    snap = compute_intraday_features(
        instrument_id=44,
        as_of=date(2024, 6, 3),
        day_bars=_full_session(),
        prev_close=99.0,
        now_utc=datetime(2024, 6, 4, 12, 0, tzinfo=UTC),
    )
    assert snap.schema == "IntradayFeatureSnapshotV1"
    assert snap.coverage_status == COVERAGE_READY
    assert snap.bars_used == 9
    assert snap.features["overnight_gap"] is not None
    assert abs(float(snap.features["overnight_gap"]) - ((100.0 / 99.0) - 1.0)) < 1e-12
    assert snap.features["open_to_close_return"] is not None
    assert snap.features["first_hour_return"] is not None
    assert snap.features["last_hour_return"] is not None
    assert snap.features["morning_return"] is not None
    assert snap.features["afternoon_return"] is not None
    assert snap.features["realized_intraday_volatility"] is not None
    assert snap.features["close_vs_session_vwap"] is not None
    assert snap.features["volume_first_hour_share"] is not None
    assert snap.features["intraday_reversal"] is not None
    # Missing evening bars must not invent values — evening not required.
    assert "no_bars_for_as_of" not in snap.limitations


def test_partial_when_session_incomplete() -> None:
    bars = _full_session()[:3]
    snap = compute_intraday_features(
        instrument_id=44,
        as_of=date(2024, 6, 3),
        day_bars=bars,
        prev_close=100.0,
        now_utc=datetime(2024, 6, 3, 10, 30, tzinfo=UTC),  # still during session
    )
    assert snap.coverage_status == "PARTIAL"
    assert snap.features["first_hour_return"] is not None
    # Hours 14–18 absent → afternoon features None (no interpolation)
    assert snap.features["afternoon_return"] is None


def test_to_dict_roundtrip_keys() -> None:
    snap = compute_intraday_features(
        instrument_id=1,
        as_of=date(2024, 6, 3),
        day_bars=_full_session(),
        prev_close=100.0,
        now_utc=datetime(2024, 6, 4, tzinfo=UTC),
    )
    d = snap.to_dict()
    assert d["interval"] == "60m"
    assert "features" in d
    assert len(d["features"]) >= 20
