"""Forward Outcome Evaluator V0 — maturity and mechanical semantics."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.prediction.application.forward_outcome import HORIZON, _spearman


def _obs(n: int, start: date = date(2026, 1, 2), start_close: float = 100.0) -> list[PriceObservation]:
    return [
        PriceObservation(date=start + timedelta(days=i), close=start_close + i, candle_id=i + 1)
        for i in range(n)
    ]


def test_19_observations_remain_pending_semantics() -> None:
    """as_of + 19 future obs is not mature for horizon 20."""
    # 1 as_of + 19 future = 20 total rows → future_count=19
    closes = _obs(20)
    as_of = closes[0].date
    future = sum(1 for o in closes if o.date > as_of)
    assert future == 19
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(closes, as_of=as_of, price_basis="mechanical_adjusted")
    assert result.label_valid["20d"] is False
    assert result.labels.forward_return_20d is None


def test_20_observations_mature() -> None:
    closes = _obs(21)
    as_of = closes[0].date
    future = sum(1 for o in closes if o.date > as_of)
    assert future == 20
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(closes, as_of=as_of, price_basis="mechanical_adjusted")
    assert result.label_valid["20d"] is True
    assert result.labels.forward_return_20d is not None
    expected = closes[20].close / closes[0].close - 1.0
    assert abs(float(result.labels.forward_return_20d) - expected) < 1e-12


def test_mechanical_split_normalized_not_invalid() -> None:
    start = date(2026, 1, 2)
    closes = _obs(21, start=start, start_close=100.0)
    # Simulate raw drop after 2:1 split on day 10 (index 10)
    closes[10] = PriceObservation(date=closes[10].date, close=55.0, candle_id=11)
    for i in range(11, 21):
        closes[i] = PriceObservation(date=closes[i].date, close=55.0 + (i - 10), candle_id=i + 1)
    actions = [
        MechanicalAction(
            instrument_id=1,
            event_date=closes[10].date,
            event_type="SPLIT",
            factor=Decimal("0.5"),
        )
    ]
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(
        closes,
        as_of=start,
        discontinuity_dates={closes[10].date},
        mechanical_actions=actions,
        price_basis="mechanical_adjusted",
    )
    assert result.label_valid["20d"] is True
    assert result.label_flags.get("mechanical_ca_normalized_20d") is True


def test_reverse_split_normalized() -> None:
    start = date(2026, 1, 2)
    closes = _obs(21, start=start, start_close=50.0)
    closes[10] = PriceObservation(date=closes[10].date, close=105.0, candle_id=11)
    for i in range(11, 21):
        closes[i] = PriceObservation(date=closes[i].date, close=105.0 + (i - 10), candle_id=i + 1)
    actions = [
        MechanicalAction(
            instrument_id=1,
            event_date=closes[10].date,
            event_type="REVERSE_SPLIT",
            factor=Decimal("2.0"),
        )
    ]
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(
        closes,
        as_of=start,
        discontinuity_dates={closes[10].date},
        mechanical_actions=actions,
        price_basis="mechanical_adjusted",
    )
    assert result.label_valid["20d"] is True
    assert result.label_flags.get("mechanical_ca_normalized_20d") is True


def test_unexplained_discontinuity_invalid() -> None:
    start = date(2026, 1, 2)
    closes = _obs(21, start=start)
    closes[10] = PriceObservation(date=closes[10].date, close=1.0, candle_id=11)
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(
        closes,
        as_of=start,
        discontinuity_dates={closes[10].date},
        mechanical_actions=[],
        price_basis="mechanical_adjusted",
    )
    assert result.label_valid["20d"] is False
    assert result.labels.forward_return_20d is None


def test_no_dividend_adjustment_path() -> None:
    """Dividends are not mechanical actions; unexplained jump stays invalid."""
    start = date(2026, 1, 2)
    closes = _obs(21, start=start)
    closes[5] = PriceObservation(date=closes[5].date, close=80.0, candle_id=6)
    calc = ForwardReturnLabelCalculator([HORIZON])
    result = calc.calculate(
        closes,
        as_of=start,
        discontinuity_dates={closes[5].date},
        mechanical_actions=[],  # no DIVIDEND type exists in H4A
        price_basis="mechanical_adjusted",
    )
    assert result.label_valid["20d"] is False


def test_spearman_and_top_bottom_helpers() -> None:
    ic = _spearman([0.2, 0.1, 0.0, -0.1], [0.15, 0.05, 0.01, -0.2])
    assert ic is not None
    assert ic > 0.5
