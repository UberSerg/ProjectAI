"""Intraday market intelligence — 60m candles + PIT daily feature snapshots."""

from datetime import date
from typing import Any

from app.modules.intelligence.contracts.snapshots_domain import IntradayFeatureSnapshotV1
from app.modules.intelligence.intraday.constants import (
    FEATURE_SET_VERSION,
    PRIMARY_INTERVAL,
    SOURCE_MOEX,
)


def build_intraday_snapshot(
    *,
    instrument_id: int,
    as_of: date,
    session: Any | None = None,
) -> IntradayFeatureSnapshotV1 | None:
    if session is None:
        return None
    from app.infrastructure.market.models import Instrument
    from app.modules.intelligence.intraday.application.service import aggregate_as_of

    inst = session.get(Instrument, instrument_id)
    if inst is None or not inst.symbol:
        return None
    results = aggregate_as_of(session, [str(inst.symbol)], as_of, persist=False)
    if not results:
        return None
    return results[0].snapshot


__all__ = [
    "FEATURE_SET_VERSION",
    "PRIMARY_INTERVAL",
    "SOURCE_MOEX",
    "build_intraday_snapshot",
]
