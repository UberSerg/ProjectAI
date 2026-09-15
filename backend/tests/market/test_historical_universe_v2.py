"""Historical equity universe V2 — MOEX board evidence over candle fallback."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V1,
    HISTORICAL_EQUITY_UNIVERSE_V2,
    QUALITY_FIRST_CANDLE,
    QUALITY_MOEX_HISTORY_FROM,
    QUALITY_MOEX_LISTED_FROM,
    HistoricalEligibility,
    build_historical_equity_universe,
)


def test_eligibility_includes_window() -> None:
    row = HistoricalEligibility(
        instrument_id=1,
        eligible_from=date(2022, 1, 1),
        eligible_to=date(2023, 6, 1),
        eligible_from_quality=QUALITY_MOEX_LISTED_FROM,
        eligible_to_quality="MOEX_BOARD_LISTED_TILL",
    )
    assert row.includes(date(2022, 1, 1))
    assert row.includes(date(2023, 6, 1))
    assert not row.includes(date(2021, 12, 31))
    assert not row.includes(date(2023, 6, 2))


def test_v2_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        build_historical_equity_universe(MagicMock(), version="nope", instrument_ids=[1])


def test_v1_still_supported_constant() -> None:
    assert HISTORICAL_EQUITY_UNIVERSE_V1 != HISTORICAL_EQUITY_UNIVERSE_V2
    assert QUALITY_FIRST_CANDLE.startswith("DERIVED")
    assert QUALITY_MOEX_LISTED_FROM.startswith("MOEX")
    assert QUALITY_MOEX_HISTORY_FROM.startswith("MOEX")


def test_universe_as_of_filters_future_listing() -> None:
    """Pure unit: future listing absent before eligible_from."""
    rows = [
        HistoricalEligibility(
            instrument_id=100,
            eligible_from=date(2024, 7, 8),
            eligible_to=None,
            eligible_from_quality=QUALITY_MOEX_LISTED_FROM,
            eligible_to_quality="UNKNOWN",
        ),
        HistoricalEligibility(
            instrument_id=200,
            eligible_from=date(2013, 3, 25),
            eligible_to=None,
            eligible_from_quality=QUALITY_MOEX_HISTORY_FROM,
            eligible_to_quality="UNKNOWN",
        ),
    ]
    as_of = date(2020, 1, 1)
    present = [r.instrument_id for r in rows if r.includes(as_of)]
    assert present == [200]
    as_of2 = date(2024, 8, 1)
    present2 = [r.instrument_id for r in rows if r.includes(as_of2)]
    assert set(present2) == {100, 200}
