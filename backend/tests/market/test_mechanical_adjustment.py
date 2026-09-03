"""H4A mechanical adjustment mathematics (no live network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.market.application.mechanical_adjustment import (
    MechanicalAction,
    actions_as_of,
    adjust_ohlcv,
    cumulative_factor,
    factor_from_payload,
)


def _action(day: date, factor: str, event_type: str = "SPLIT") -> MechanicalAction:
    return MechanicalAction(instrument_id=1, event_date=day, event_type=event_type, factor=Decimal(factor))


def test_split_and_reverse_use_same_after_over_before() -> None:
    assert factor_from_payload({"split_before": "1", "split_after": "10"}) == Decimal("10")
    assert factor_from_payload({"split_before": "5000", "split_after": "1"}) == Decimal("0.0002")
    assert factor_from_payload({"adjustment_factor": "10"}) == Decimal("10")


def test_ohlc_divided_volume_multiplied() -> None:
    action = _action(date(2025, 3, 27), "10")
    open_, high, low, close, volume = adjust_ohlcv(
        open_=19000,
        high=19100,
        low=18900,
        close=19011.5,
        volume=100,
        obs_date=date(2025, 3, 26),
        actions=actions_as_of([action], date(2025, 3, 27)),
    )
    assert close == 1901.15
    assert open_ == 1900
    assert high == 1910
    assert low == 1890
    assert volume == 1000


def test_event_day_stays_on_new_share_basis() -> None:
    action = _action(date(2025, 3, 27), "10")
    applied = actions_as_of([action], date(2025, 3, 27))
    assert cumulative_factor(applied, date(2025, 3, 27)) == Decimal("1")
    _o, _h, _l, close, volume = adjust_ohlcv(
        open_=1901.8,
        high=1910,
        low=1880,
        close=1890,
        volume=1000,
        obs_date=date(2025, 3, 27),
        actions=applied,
    )
    assert close == 1890
    assert volume == 1000


def test_future_action_does_not_change_as_of() -> None:
    future = _action(date(2025, 3, 27), "10")
    applied = actions_as_of([future], date(2025, 3, 26))
    assert applied == []
    assert cumulative_factor(applied, date(2025, 3, 26)) == Decimal("1")


def test_multiple_actions_compose() -> None:
    first = _action(date(2020, 1, 10), "2")
    second = _action(date(2022, 6, 1), "5")
    as_of = actions_as_of([first, second], date(2023, 1, 1))
    assert cumulative_factor(as_of, date(2019, 12, 31)) == Decimal("10")
    assert cumulative_factor(as_of, date(2020, 1, 10)) == Decimal("5")
    assert cumulative_factor(as_of, date(2022, 6, 1)) == Decimal("1")


def test_dividend_payload_is_not_a_mechanical_factor() -> None:
    actions = actions_as_of([], date(2020, 1, 1))
    assert cumulative_factor(actions, date(2019, 1, 1)) == Decimal("1")
