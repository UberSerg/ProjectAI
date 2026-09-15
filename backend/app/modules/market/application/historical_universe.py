"""Historical equity universe contract V1 (survivorship-aware eligibility).

Version: ``historical_equity_universe_v1``.

Eligibility windows are **derived from daily candles**, not from inventing
listing registries:

- ``eligible_from`` = first ``1d`` candle date → quality ``DERIVED_FROM_FIRST_CANDLE``
- ``eligible_to`` = last ``1d`` candle date when the instrument is inactive /
  delisted → quality ``DERIVED_FROM_LAST_CANDLE``; otherwise ``None`` with
  quality ``UNKNOWN`` (still listed / open-ended)

Does not mutate Dataset V2, Prediction, Shadow fills, or ``research_fi_v1``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, UniverseMembership
from app.modules.market.application.research_universe import RESEARCH_EQUITY_V1

HISTORICAL_EQUITY_UNIVERSE_V1 = "historical_equity_universe_v1"

QUALITY_FIRST_CANDLE = "DERIVED_FROM_FIRST_CANDLE"
QUALITY_LAST_CANDLE = "DERIVED_FROM_LAST_CANDLE"
QUALITY_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HistoricalEligibility:
    instrument_id: int
    eligible_from: date
    eligible_to: date | None
    eligible_from_quality: str
    eligible_to_quality: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def includes(self, as_of: date) -> bool:
        if as_of < self.eligible_from:
            return False
        if self.eligible_to is not None and as_of > self.eligible_to:
            return False
        return True


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _cohort_instrument_ids(
    session: Session,
    *,
    instrument_ids: Iterable[int] | None,
    use_research_cohort: bool,
) -> list[int]:
    if instrument_ids is not None:
        return sorted({int(i) for i in instrument_ids})

    if use_research_cohort:
        research_ids = list(
            session.scalars(
                select(UniverseMembership.instrument_id).where(
                    UniverseMembership.universe_code == RESEARCH_EQUITY_V1
                )
            )
        )
        if research_ids:
            return sorted({int(i) for i in research_ids})

    # Fallback: all equities that have at least one daily candle.
    rows = session.execute(
        select(Instrument.id)
        .join(Candle, Candle.instrument_id == Instrument.id)
        .where(Instrument.asset_class == "equity", Candle.timeframe == "1d")
        .distinct()
    ).scalars()
    return sorted({int(i) for i in rows})


def build_historical_equity_universe(
    session: Session,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
    instrument_ids: Sequence[int] | None = None,
    use_research_cohort: bool = True,
) -> list[HistoricalEligibility]:
    """Build eligibility windows for the research equity cohort (or all candle equities)."""
    if version != HISTORICAL_EQUITY_UNIVERSE_V1:
        raise ValueError(f"Unsupported historical universe version: {version}")

    ids = _cohort_instrument_ids(
        session,
        instrument_ids=instrument_ids,
        use_research_cohort=use_research_cohort,
    )
    if not ids:
        return []

    instruments = {
        int(row.id): row
        for row in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    candle_bounds = {
        int(instrument_id): (_as_date(first), _as_date(last))
        for instrument_id, first, last in session.execute(
            select(
                Candle.instrument_id,
                func.min(Candle.timestamp),
                func.max(Candle.timestamp),
            )
            .where(Candle.instrument_id.in_(ids), Candle.timeframe == "1d")
            .group_by(Candle.instrument_id)
        )
    }

    out: list[HistoricalEligibility] = []
    for iid in ids:
        bounds = candle_bounds.get(iid)
        if bounds is None or bounds[0] is None:
            continue
        first_d, last_d = bounds
        assert first_d is not None
        instrument = instruments.get(iid)
        inactive = False
        if instrument is not None:
            inactive = (not bool(instrument.is_active)) or (instrument.active_to is not None)

        if inactive and last_d is not None:
            eligible_to = last_d
            to_quality = QUALITY_LAST_CANDLE
        else:
            eligible_to = None
            to_quality = QUALITY_UNKNOWN

        provenance = {
            "version": version,
            "eligible_from_basis": "min(market.candles.timestamp) where timeframe=1d",
            "eligible_to_basis": (
                "max(market.candles.timestamp) where timeframe=1d and instrument inactive/delisted"
                if eligible_to is not None
                else "open_ended_while_active"
            ),
            "instrument_is_active": None if instrument is None else bool(instrument.is_active),
            "instrument_active_to": (
                None
                if instrument is None or instrument.active_to is None
                else instrument.active_to.isoformat()
            ),
            "first_candle": first_d.isoformat(),
            "last_candle": None if last_d is None else last_d.isoformat(),
        }
        out.append(
            HistoricalEligibility(
                instrument_id=iid,
                eligible_from=first_d,
                eligible_to=eligible_to,
                eligible_from_quality=QUALITY_FIRST_CANDLE,
                eligible_to_quality=to_quality,
                provenance=provenance,
            )
        )
    return out


def universe_as_of(
    session: Session,
    as_of: date,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
    instrument_ids: Sequence[int] | None = None,
    use_research_cohort: bool = True,
) -> list[int]:
    """Instrument ids eligible on ``as_of`` under the historical universe contract."""
    rows = build_historical_equity_universe(
        session,
        version=version,
        instrument_ids=instrument_ids,
        use_research_cohort=use_research_cohort,
    )
    return [row.instrument_id for row in rows if row.includes(as_of)]


def summarize_historical_universe(
    session: Session,
    *,
    version: str = HISTORICAL_EQUITY_UNIVERSE_V1,
) -> dict[str, Any]:
    """Compact evidence blob for Data Readiness."""
    rows = build_historical_equity_universe(session, version=version)
    if not rows:
        return {"version": version, "members": 0, "instrument_count": 0}
    froms = [r.eligible_from for r in rows]
    tos = [r.eligible_to for r in rows if r.eligible_to is not None]
    return {
        "version": version,
        "members": len(rows),
        "instrument_count": len(rows),
        "earliest_eligible_from": min(froms).isoformat(),
        "latest_eligible_from": max(froms).isoformat(),
        "closed_windows": len(tos),
        "open_ended": sum(1 for r in rows if r.eligible_to is None),
        "quality_from": QUALITY_FIRST_CANDLE,
        "quality_to_when_inactive": QUALITY_LAST_CANDLE,
    }
