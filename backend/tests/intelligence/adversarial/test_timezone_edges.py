"""Timezone / midnight crossover adversarial cases for known_at gate."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from app.modules.intelligence.contracts.provenance import known_at_allows
from app.modules.intelligence.contracts.snapshots_domain import (
    IntradayFeatureSnapshotV1,
    MacroSnapshotV1,
)
from tests.intelligence.adversarial._helpers import utc_midnight

MSK = timezone(timedelta(hours=3))


def test_utc_datetime_on_as_of_day_allowed() -> None:
    as_of = date(2026, 8, 27)
    assert known_at_allows(as_of, datetime(2026, 8, 27, 23, 59, tzinfo=UTC))
    assert known_at_allows(as_of, utc_midnight(as_of))


def test_next_utc_day_blocked_even_if_still_msk_evening() -> None:
    """2026-08-27 23:30 MSK == 2026-08-27 20:30 UTC — still same calendar day in UTC.

    Critical edge: 2026-08-28 00:30 MSK == 2026-08-27 21:30 UTC.
    Gate uses calendar date of the timestamp after converting via .date() on aware dt
    (local calendar of the tzinfo). Attack: use MSK early morning as if visible on
    prior UTC as_of day — must be blocked when known_at.date() is 2026-08-28.
    """
    as_of = date(2026, 8, 27)
    msk_next_morning = datetime(2026, 8, 28, 0, 30, tzinfo=MSK)
    assert msk_next_morning.date() == date(2026, 8, 28)
    assert not known_at_allows(as_of, msk_next_morning)

    # Same instant in UTC is still 2026-08-27 — allowed only if stored as UTC date 27.
    utc_same_instant = msk_next_morning.astimezone(UTC)
    assert utc_same_instant.date() == date(2026, 8, 27)
    # Contract is date-only on the stored tz's .date(); storage policy must be consistent.
    # Red team: do not mix TZ calendars — if persisted as MSK wall date 28, deny.
    assert known_at_allows(as_of, utc_same_instant) != known_at_allows(
        as_of, msk_next_morning
    )


def test_as_of_datetime_uses_calendar_date() -> None:
    as_of_dt = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    assert known_at_allows(as_of_dt, date(2026, 8, 27))
    assert not known_at_allows(as_of_dt, date(2026, 8, 28))


def test_intraday_missing_bars_are_not_zero_features() -> None:
    snap = IntradayFeatureSnapshotV1(
        instrument_id=1,
        as_of=date(2026, 8, 27),
        known_at=date(2026, 8, 27),
        interval="60m",
        coverage_status="NOT_READY",
        features={"ret_1h": None, "volume_z": None},
        bars_used=0,
        limitations=("missing_intraday_bars",),
    )
    assert snap.bars_used == 0
    assert snap.features["ret_1h"] is None
    assert "missing_intraday_bars" in snap.limitations


def test_stale_macro_known_at_blocks_use() -> None:
    as_of = date(2026, 10, 1)
    macro = MacroSnapshotV1(
        as_of=as_of,
        known_at=date(2024, 1, 1),
        status="PARTIAL",
        observations={"key_rate": 16.0},
        limitations=("stale_macro_data",),
        sources=("CBR",),
    )
    # Staleness is a risk/committee concern; PIT still allows old known_at.
    assert known_at_allows(as_of, macro.known_at)
    assert "stale_macro_data" in macro.limitations
    # Future macro print must not leak.
    future = MacroSnapshotV1(
        as_of=as_of,
        known_at=date(2026, 10, 15),
        status="PARTIAL",
        observations={"key_rate": 14.0},
    )
    assert not known_at_allows(as_of, future.known_at)
