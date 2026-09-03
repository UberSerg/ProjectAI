"""PIT mechanical price/volume adjustment from SPLIT / REVERSE_SPLIT only.

Does not adjust dividends. Does not rewrite market.candles.
A future action (effective_date > as_of) must not change history at as_of.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import CorporateAction
from app.modules.market.application.split_events import SPLIT_FEED_EVENT_TYPES, split_adjustment_factor


@dataclass(frozen=True, slots=True)
class MechanicalAction:
    instrument_id: int
    event_date: date
    event_type: str
    factor: Decimal


def factor_from_payload(payload: dict[str, Any] | None) -> Decimal:
    data = payload or {}
    if data.get("adjustment_factor") not in (None, ""):
        factor = Decimal(str(data["adjustment_factor"]))
        if factor <= 0:
            raise ValueError("adjustment_factor must be > 0")
        return factor
    before = Decimal(str(data["split_before"]))
    after = Decimal(str(data["split_after"]))
    return split_adjustment_factor(before, after)


def actions_as_of(actions: list[MechanicalAction], as_of: date) -> list[MechanicalAction]:
    """Only realized mechanical events: effective_date <= as_of. No future leakage."""
    return [item for item in actions if item.event_date <= as_of]


def cumulative_factor(actions: list[MechanicalAction], obs_date: date) -> Decimal:
    """Product of factors for events with obs_date < event_date.

    Caller must pass only actions already filtered to effective_date <= as_of.
    Converts a raw observation on date obs_date onto the share basis of as_of.
    """
    factor = Decimal("1")
    for action in actions:
        if obs_date < action.event_date:
            factor *= action.factor
    return factor


def adjust_price(price: float | None, factor: Decimal) -> float | None:
    if price is None:
        return None
    return float(Decimal(str(price)) / factor)


def adjust_volume(volume: float | None, factor: Decimal) -> float | None:
    """Share-count basis: historical volume is scaled by the same factor as price is divided."""
    if volume is None:
        return None
    return float(Decimal(str(volume)) * factor)


def adjust_ohlcv(
    *,
    open_: float | None,
    high: float | None,
    low: float | None,
    close: float | None,
    volume: float | None,
    obs_date: date,
    actions: list[MechanicalAction],
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    factor = cumulative_factor(actions, obs_date)
    return (
        adjust_price(open_, factor),
        adjust_price(high, factor),
        adjust_price(low, factor),
        adjust_price(close, factor),
        adjust_volume(volume, factor),
    )


def load_mechanical_actions(session: Session, instrument_id: int) -> list[MechanicalAction]:
    rows = session.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES),
        )
        .order_by(CorporateAction.event_date)
    )
    actions: list[MechanicalAction] = []
    for row in rows:
        actions.append(
            MechanicalAction(
                instrument_id=row.instrument_id,
                event_date=row.event_date,
                event_type=row.event_type,
                factor=factor_from_payload(row.payload),
            )
        )
    return actions
