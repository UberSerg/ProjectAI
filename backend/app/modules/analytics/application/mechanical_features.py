"""Run DailyFeatureCalculator on PIT mechanical-adjusted observations."""

from __future__ import annotations

from datetime import date

from app.modules.analytics.application.calculator import (
    CandleObservation,
    DailyFeatureCalculator,
    InstrumentFeatureRecord,
)
from app.modules.market.application.mechanical_adjustment import (
    MechanicalAction,
    actions_as_of,
    adjust_ohlcv,
)


def uses_mechanical_price_basis(parameters: dict | None) -> bool:
    return (parameters or {}).get("price_basis") == "mechanical_adjusted"


def _unique_event_dates(actions: list[MechanicalAction]) -> list[date]:
    return sorted({item.event_date for item in actions})


def calculate_mechanical_adjusted_features(
    calculator: DailyFeatureCalculator,
    observations: list[CandleObservation],
    actions: list[MechanicalAction],
    *,
    discontinuity_dates: set[date] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[InstrumentFeatureRecord]:
    """Segment by event dates so X(t) uses only events with effective_date <= t."""
    if not observations:
        return []
    event_dates = _unique_event_dates(actions)
    if not event_dates:
        return calculator.calculate(
            observations,
            discontinuity_dates=discontinuity_dates,
            date_from=date_from,
            date_to=date_to,
        )

    # [date_from, first_event) then [E_k, E_{k+1}) with events effective_date <= E_k.
    segments: list[tuple[date | None, date | None, list[MechanicalAction]]] = [
        (date_from, _day_before(event_dates[0]), [])
    ]
    for index, event_date in enumerate(event_dates):
        next_date = event_dates[index + 1] if index + 1 < len(event_dates) else None
        applied = actions_as_of(actions, event_date)
        inclusive_to = date_to if next_date is None else _day_before(next_date)
        segments.append((event_date, inclusive_to, applied))

    by_date: dict[date, InstrumentFeatureRecord] = {}
    for start, inclusive_to, applied in segments:
        if start is not None and inclusive_to is not None and start > inclusive_to:
            continue
        adjusted = [_adjust_observation(item, applied) for item in observations]
        records = calculator.calculate(
            adjusted,
            discontinuity_dates=discontinuity_dates,
            date_from=start,
            date_to=inclusive_to,
        )
        for record in records:
            if date_from and record.date < date_from:
                continue
            if date_to and record.date > date_to:
                continue
            by_date[record.date] = record
    return [by_date[key] for key in sorted(by_date)]


def _adjust_observation(obs: CandleObservation, actions: list[MechanicalAction]) -> CandleObservation:
    _o, _h, _l, close, volume = adjust_ohlcv(
        open_=None,
        high=None,
        low=None,
        close=obs.close,
        volume=obs.volume,
        obs_date=obs.date,
        actions=actions,
    )
    return CandleObservation(
        date=obs.date,
        close=obs.close if close is None else close,
        volume=volume,
        source_updated_at=obs.source_updated_at,
    )


def _day_before(value: date) -> date:
    return date.fromordinal(value.toordinal() - 1)
