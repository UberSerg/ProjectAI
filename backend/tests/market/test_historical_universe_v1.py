"""Historical equity universe V1 — survivorship eligibility from candles."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V1,
    HistoricalEligibility,
    build_historical_equity_universe,
    universe_as_of,
)


def _session_with_bounds(
    instruments: list[SimpleNamespace],
    bounds: dict[int, tuple[datetime, datetime]],
) -> MagicMock:
    session = MagicMock()

    def scalars(_stmt):  # noqa: ANN001
        return list(instruments)

    def execute(_stmt):  # noqa: ANN001
        return [(iid, first, last) for iid, (first, last) in bounds.items()]

    session.scalars.side_effect = scalars
    session.execute.side_effect = execute
    return session


def test_historical_eligibility_includes_boundaries() -> None:
    row = HistoricalEligibility(
        instrument_id=1,
        eligible_from=date(2020, 1, 10),
        eligible_to=date(2022, 6, 1),
        eligible_from_quality="DERIVED_FROM_FIRST_CANDLE",
        eligible_to_quality="DERIVED_FROM_LAST_CANDLE",
    )
    assert not row.includes(date(2020, 1, 9))
    assert row.includes(date(2020, 1, 10))
    assert row.includes(date(2022, 6, 1))
    assert not row.includes(date(2022, 6, 2))


def test_universe_as_of_future_instrument_absent_in_past() -> None:
    """Instrument whose first candle is in 2021 must be absent as_of 2020."""
    early = SimpleNamespace(id=1, is_active=True, active_to=None)
    late = SimpleNamespace(id=2, is_active=True, active_to=None)
    session = _session_with_bounds(
        [early, late],
        {
            1: (datetime(2019, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
            2: (datetime(2021, 6, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
        },
    )

    past = universe_as_of(
        session,
        date(2020, 1, 1),
        version=HISTORICAL_EQUITY_UNIVERSE_V1,
        instrument_ids=[1, 2],
    )
    assert past == [1]

    present = universe_as_of(
        session,
        date(2022, 1, 1),
        version=HISTORICAL_EQUITY_UNIVERSE_V1,
        instrument_ids=[1, 2],
    )
    assert present == [1, 2]


def test_listing_and_delisting_boundaries() -> None:
    active = SimpleNamespace(id=10, is_active=True, active_to=None)
    delisted = SimpleNamespace(id=11, is_active=False, active_to=date(2022, 3, 15))
    session = _session_with_bounds(
        [active, delisted],
        {
            10: (datetime(2020, 1, 2, tzinfo=UTC), datetime(2024, 5, 1, tzinfo=UTC)),
            11: (datetime(2018, 5, 1, tzinfo=UTC), datetime(2022, 3, 10, tzinfo=UTC)),
        },
    )

    rows = build_historical_equity_universe(session, instrument_ids=[10, 11])
    by_id = {r.instrument_id: r for r in rows}

    assert by_id[10].eligible_from == date(2020, 1, 2)
    assert by_id[10].eligible_to is None
    assert by_id[10].eligible_to_quality == "UNKNOWN"

    assert by_id[11].eligible_from == date(2018, 5, 1)
    assert by_id[11].eligible_to == date(2022, 3, 10)
    assert by_id[11].eligible_to_quality == "DERIVED_FROM_LAST_CANDLE"

    assert universe_as_of(session, date(2022, 3, 10), instrument_ids=[10, 11]) == [10, 11]
    assert universe_as_of(session, date(2022, 3, 11), instrument_ids=[10, 11]) == [10]


def test_unsupported_version_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        build_historical_equity_universe(MagicMock(), version="nope", instrument_ids=[1])
