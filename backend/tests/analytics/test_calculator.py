"""Unit tests for DailyFeatureCalculator — manual expected values."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.analytics.application.calculator import CandleObservation, DailyFeatureCalculator


def _obs(closes: list[float], volumes: list[float | None] | None = None) -> list[CandleObservation]:
    volumes = volumes or [1000.0] * len(closes)
    base = date(2024, 1, 1)
    out: list[CandleObservation] = []
    for i, close in enumerate(closes):
        out.append(
            CandleObservation(
                date=date(base.year, base.month, base.day + i),
                close=close,
                volume=volumes[i] if i < len(volumes) else 1000.0,
            )
        )
    return out


@pytest.fixture
def calc() -> DailyFeatureCalculator:
    return DailyFeatureCalculator()


def test_return_1d_manual(calc: DailyFeatureCalculator) -> None:
    records = calc.calculate(_obs([100, 102, 101, 105, 110]), date_from=date(2024, 1, 2))
    by_date = {r.date: r for r in records}
    assert by_date[date(2024, 1, 2)].return_1d == pytest.approx(0.02)
    assert by_date[date(2024, 1, 3)].return_1d == pytest.approx(101 / 102 - 1)
    assert by_date[date(2024, 1, 5)].return_5d is None


def test_return_20d_requires_history(calc: DailyFeatureCalculator) -> None:
    closes = [100 + i for i in range(15)]
    records = calc.calculate(_obs(closes), date_from=date(2024, 1, 15))
    assert records[-1].return_20d is None
    assert "return_20d" in records[-1].quality_flags.get("insufficient_history", [])


def test_log_return_invalid_close(calc: DailyFeatureCalculator) -> None:
    records = calc.calculate(_obs([100, 0, 105]), date_from=date(2024, 1, 2))
    assert records[0].quality_flags.get("invalid_close") is True
    assert records[1].log_return_1d is None
    assert records[1].quality_flags.get("invalid_prior_close") is True


def test_volatility_ddof1(calc: DailyFeatureCalculator) -> None:
    # 6 closes → 5 log returns; vol_5d needs 5 log returns at index 5
    closes = [100, 101, 102, 101, 103, 104]
    records = calc.calculate(_obs(closes), date_from=date(2024, 1, 6))
    last = records[-1]
    assert last.volatility_5d is not None
    assert last.volatility_20d is None


def test_drawdown_at_peak(calc: DailyFeatureCalculator) -> None:
    closes = [100.0] * 25
    records = calc.calculate(_obs(closes), date_from=date(2024, 1, 25))
    assert records[-1].drawdown_20d == pytest.approx(0.0)


def test_volume_zscore_baseline_excludes_current(calc: DailyFeatureCalculator) -> None:
    volumes = [900.0 + (i % 5) * 10 for i in range(21)] + [5000.0]
    closes = [100.0] * 22
    records = calc.calculate(_obs(closes, volumes), date_from=date(2024, 1, 22))
    z = records[-1].volume_zscore_20d
    assert z is not None
    assert z > 0


def test_no_look_ahead(calc: DailyFeatureCalculator) -> None:
    base = _obs([100, 102, 101, 105, 110, 108, 112, 115, 118, 120])
    altered = _obs([100, 102, 101, 105, 110, 999, 999, 999, 999, 999])
    target = date(2024, 1, 5)
    a = next(r for r in calc.calculate(base, date_from=target, date_to=target) if r.date == target)
    b = next(r for r in calc.calculate(altered, date_from=target, date_to=target) if r.date == target)
    assert a.return_1d == b.return_1d
    assert a.return_5d == b.return_5d
    assert a.volatility_5d == b.volatility_5d
    assert a.drawdown_20d == b.drawdown_20d
    assert a.volume_zscore_20d == b.volume_zscore_20d


def test_trading_observation_window(calc: DailyFeatureCalculator) -> None:
    """Friday return_1d uses previous trading day (Tuesday), not calendar Thursday."""
    obs = [
        CandleObservation(date=date(2024, 1, 1), close=100, volume=1000),  # Mon
        CandleObservation(date=date(2024, 1, 2), close=110, volume=1000),  # Tue
        CandleObservation(date=date(2024, 1, 5), close=121, volume=1000),  # Fri
    ]
    records = calc.calculate(obs, date_from=date(2024, 1, 5))
    fri = records[-1]
    assert fri.return_1d == pytest.approx(121 / 110 - 1)
    assert fri.return_2d == pytest.approx(121 / 100 - 1)


def test_price_discontinuity_flag(calc: DailyFeatureCalculator) -> None:
    obs = _obs([100, 102, 101, 105])
    d = date(2024, 1, 3)
    records = calc.calculate(obs, discontinuity_dates={d}, date_from=d)
    row = records[0]
    assert row.quality_flags.get("price_discontinuity") is True
