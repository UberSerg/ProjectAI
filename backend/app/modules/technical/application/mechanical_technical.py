"""Run TechnicalFeatureCalculator on PIT mechanical-adjusted OHLCV."""

from __future__ import annotations

from datetime import date

from app.modules.market.application.mechanical_adjustment import (
    MechanicalAction,
    actions_as_of,
    adjust_ohlcv,
)
from app.modules.technical.application.calculator import (
    OhlcObservation,
    TechnicalFeatureCalculator,
    TechnicalFeatureRecord,
)


def uses_mechanical_price_basis(parameters: dict | None) -> bool:
    return (parameters or {}).get("price_basis") == "mechanical_adjusted"


def calculate_mechanical_adjusted_technical(
    calculator: TechnicalFeatureCalculator,
    observations: list[OhlcObservation],
    actions: list[MechanicalAction],
    *,
    discontinuity_dates: set[date] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[TechnicalFeatureRecord]:
    """Segment by event dates so X(t) uses only events with effective_date <= t."""
    if not observations:
        return []
    event_dates = sorted({item.event_date for item in actions})
    if not event_dates:
        return calculator.calculate(
            observations,
            discontinuity_dates=discontinuity_dates,
            date_from=date_from,
            date_to=date_to,
        )

    segments: list[tuple[date | None, date | None, list[MechanicalAction]]] = [
        (date_from, _day_before(event_dates[0]), [])
    ]
    for index, event_date in enumerate(event_dates):
        next_date = event_dates[index + 1] if index + 1 < len(event_dates) else None
        applied = actions_as_of(actions, event_date)
        inclusive_to = date_to if next_date is None else _day_before(next_date)
        segments.append((event_date, inclusive_to, applied))

    by_date: dict[date, TechnicalFeatureRecord] = {}
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


def _adjust_observation(obs: OhlcObservation, actions: list[MechanicalAction]) -> OhlcObservation:
    open_, high, low, close, volume = adjust_ohlcv(
        open_=obs.open,
        high=obs.high,
        low=obs.low,
        close=obs.close,
        volume=obs.volume,
        obs_date=obs.date,
        actions=actions,
    )
    return OhlcObservation(
        date=obs.date,
        open=obs.open if open_ is None else open_,
        high=obs.high if high is None else high,
        low=obs.low if low is None else low,
        close=obs.close if close is None else close,
        volume=volume,
        source_updated_at=obs.source_updated_at,
    )


def _day_before(value: date) -> date:
    return date.fromordinal(value.toordinal() - 1)
