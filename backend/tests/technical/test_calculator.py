"""Unit tests for TechnicalFeatureCalculator — SMA/EMA/RSI/ATR exact semantics."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.modules.technical.application.calculator import OhlcObservation, TechnicalFeatureCalculator


def _obs(closes: list[float], start: date | None = None) -> list[OhlcObservation]:
    start = start or date(2024, 1, 2)
    out: list[OhlcObservation] = []
    for i, c in enumerate(closes):
        d = start + timedelta(days=i)
        # Flat OHLC around close for simple ATR cases; tests override when needed.
        out.append(OhlcObservation(date=d, open=c, high=c, low=c, close=c))
    return out


def test_sma20_exact_and_distance() -> None:
    closes = [float(i) for i in range(1, 25)]  # 1..24
    calc = TechnicalFeatureCalculator()
    records = calc.calculate(_obs(closes))
    # First 19 insufficient
    assert records[18].sma20 is None
    assert records[18].sma20_distance is None
    # Index 19 = mean(1..20) = 10.5
    assert records[19].sma20 == 10.5
    assert abs(records[19].sma20_distance - (20.0 / 10.5 - 1.0)) < 1e-12
    # Index 20 = mean(2..21) = 11.5
    assert records[20].sma20 == 11.5


def test_ema20_against_hand_computed() -> None:
    # Hand-computed ewm(span=20, adjust=False): alpha=2/21
    closes = [100.0 + i for i in range(25)]
    alpha = 2.0 / 21.0
    ema = closes[0]
    expected: list[float | None] = []
    for i, c in enumerate(closes):
        if i == 0:
            ema = c
        else:
            ema = (1.0 - alpha) * ema + alpha * c
        expected.append(None if i < 19 else ema)

    calc = TechnicalFeatureCalculator()
    records = calc.calculate(_obs(closes))
    for i, rec in enumerate(records):
        if expected[i] is None:
            assert rec.ema20 is None
        else:
            assert rec.ema20 is not None
            assert abs(rec.ema20 - expected[i]) < 1e-10
            assert abs(rec.ema20_distance - (closes[i] / expected[i] - 1.0)) < 1e-10


def test_rsi_wilder_normal_all_gains_losses_flat_insufficient() -> None:
    calc = TechnicalFeatureCalculator()

    # Insufficient: fewer than 15 closes
    short = calc.calculate(_obs([10.0] * 10))
    assert all(r.rsi14 is None for r in short)

    # All gains after base: steadily rising → RSI → 100
    rising = [100.0 + i for i in range(30)]
    rec_up = calc.calculate(_obs(rising))
    assert rec_up[14].rsi14 is not None
    assert rec_up[-1].rsi14 == 100.0

    # All losses → RSI → 0
    falling = [100.0 - i for i in range(30)]
    rec_dn = calc.calculate(_obs(falling))
    assert rec_dn[-1].rsi14 == 0.0

    # Flat → first RSI = 50 (avg_gain=avg_loss=0)
    flat = [50.0] * 30
    rec_flat = calc.calculate(_obs(flat))
    assert rec_flat[14].rsi14 == 50.0
    assert rec_flat[-1].rsi14 == 50.0

    # Known short sequence: hand Wilder for period=14 on synthetic alternating
    # Verify first RSI equals formula from first 14 deltas.
    closes = [float(x) for x in range(100, 130)]
    deltas = np.diff(closes)
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    avg_g = float(np.mean(gains[:14]))
    avg_l = float(np.mean(losses[:14]))
    if avg_l == 0 and avg_g > 0:
        expected_first = 100.0
    elif avg_g == 0 and avg_l > 0:
        expected_first = 0.0
    elif avg_g == 0 and avg_l == 0:
        expected_first = 50.0
    else:
        rs = avg_g / avg_l
        expected_first = 100.0 - 100.0 / (1.0 + rs)
    rec = calc.calculate(_obs(closes))
    assert abs(rec[14].rsi14 - expected_first) < 1e-10


def test_atr_true_range_and_wilder() -> None:
    calc = TechnicalFeatureCalculator()
    start = date(2024, 1, 1)
    # Build OHLC with gap up / gap down / flat
    rows = [
        OhlcObservation(start, 10, 12, 9, 11),  # TR = 3
        OhlcObservation(start + timedelta(days=1), 14, 15, 13, 14),  # gap up from 11: max(2,4,2)=4
        OhlcObservation(start + timedelta(days=2), 10, 11, 8, 9),  # gap down from 14: max(3,3,6)=6
        OhlcObservation(start + timedelta(days=3), 9, 9, 9, 9),  # flat TR=max(0,0,0)=0 vs prev 9
    ]
    # Pad to 14 bars with flat TR = high-low = 1
    for i in range(4, 20):
        c = 9.0
        rows.append(
            OhlcObservation(
                start + timedelta(days=i),
                open=c,
                high=c + 0.5,
                low=c - 0.5,
                close=c,
            )
        )

    # Manual TR[0]
    assert rows[0].high - rows[0].low == 3
    # Manual TR[1]
    tr1 = max(15 - 13, abs(15 - 11), abs(13 - 11))
    assert tr1 == 4
    tr2 = max(11 - 8, abs(11 - 14), abs(8 - 14))
    assert tr2 == 6

    records = calc.calculate(rows)
    assert records[12].atr14 is None  # need 14 bars → first at index 13
    assert records[13].atr14 is not None
    # First ATR = mean(TR[0:14])
    trs = []
    prev_c = None
    for i, r in enumerate(rows[:14]):
        if i == 0:
            trs.append(r.high - r.low)
        else:
            trs.append(max(r.high - r.low, abs(r.high - prev_c), abs(r.low - prev_c)))
        prev_c = r.close
    assert abs(records[13].atr14 - (sum(trs) / 14)) < 1e-10
    assert records[13].atr14_pct is not None
    assert abs(records[13].atr14_pct - records[13].atr14 / rows[13].close) < 1e-10


def test_no_lookahead_features() -> None:
    base = [100.0 + (i % 7) for i in range(40)]
    calc = TechnicalFeatureCalculator()
    a = calc.calculate(_obs(base + [200.0, 300.0, 400.0]), date_to=date(2024, 1, 2) + timedelta(days=39))
    b_closes = base + [1.0, 2.0, 3.0]
    b = calc.calculate(_obs(b_closes), date_to=date(2024, 1, 2) + timedelta(days=39))
    # Compare last overlapping date (index 39)
    assert a[-1].date == b[-1].date
    assert a[-1].sma20 == b[-1].sma20
    assert a[-1].ema20 == b[-1].ema20
    assert a[-1].rsi14 == b[-1].rsi14
    assert a[-1].atr14 == b[-1].atr14


def test_discontinuity_marks_invalid() -> None:
    closes = [100.0 + i * 0.1 for i in range(30)]
    calc = TechnicalFeatureCalculator()
    disc = {date(2024, 1, 2) + timedelta(days=25)}
    records = calc.calculate(_obs(closes), discontinuity_dates=disc)
    # Records near/after discontinuity window should carry flag
    flagged = [r for r in records if r.quality_flags.get("price_discontinuity")]
    assert flagged
    assert any(not r.is_valid for r in flagged)


def test_incremental_equivalence_tail() -> None:
    closes = [100.0 + np.sin(i / 3) * 2 + i * 0.05 for i in range(80)]
    obs = _obs(closes)
    calc = TechnicalFeatureCalculator()
    full = {r.date: r for r in calc.calculate(obs)}
    # Simulate incremental: compute on first 60, then on all (full history strategy)
    first = calc.calculate(obs[:60])
    second = calc.calculate(obs)  # full reload
    for r in first:
        f = full[r.date]
        assert r.ema20 == f.ema20 or (r.ema20 is None and f.ema20 is None)
        if r.ema20 is not None:
            assert abs(r.ema20 - f.ema20) < 1e-12
    last = second[-1]
    assert abs(last.ema20 - full[last.date].ema20) < 1e-12
    assert abs(last.rsi14 - full[last.date].rsi14) < 1e-12
    assert abs(last.atr14 - full[last.date].atr14) < 1e-12
