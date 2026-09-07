"""Application helpers for gross total return coverage (read-only)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle
from app.modules.fundamentals.domain.total_return import (
    DividendCoverageReport,
    assess_dividend_coverage,
)
from app.modules.fundamentals.infrastructure.models import (
    DividendEvent,
    fundamentals_schema_ready,
)


def build_dividend_coverage_report(session: Session) -> DividendCoverageReport:
    """Honest coverage: empty dividend_events → NOT_READY (current live state)."""
    instruments = int(
        session.scalar(
            select(func.count(func.distinct(Candle.instrument_id))).where(Candle.timeframe == "1d")
        )
        or 0
    )
    if not fundamentals_schema_ready(session):
        return assess_dividend_coverage(
            instruments_with_price_history=instruments,
            dividend_events_stored=0,
            instruments_with_dividend_events=0,
            accepted_provider=False,
        )

    events = int(session.scalar(select(func.count()).select_from(DividendEvent)) or 0)
    with_div = int(
        session.scalar(
            select(func.count(func.distinct(DividendEvent.instrument_id))).where(
                DividendEvent.instrument_id.is_not(None)
            )
        )
        or 0
    )
    return assess_dividend_coverage(
        instruments_with_price_history=instruments,
        dividend_events_stored=events,
        instruments_with_dividend_events=with_div,
        accepted_provider=events > 0,
    )


def dividend_coverage_payload(session: Session) -> dict[str, Any]:
    return build_dividend_coverage_report(session).to_dict()
