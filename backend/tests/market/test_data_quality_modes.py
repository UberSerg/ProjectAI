"""Data quality mode tests (no live network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.market.application.data_quality import (
    DataQualityContext,
    run_data_quality_checks,
)


def test_historical_requires_date_range() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="date_from"):
        run_data_quality_checks(session, DataQualityContext(mode="historical"))


def test_historical_backfill_does_not_emit_missing_recent_for_past_range() -> None:
    """Regression: past backfill range must not warn about wall-clock freshness."""
    session = MagicMock()
    instrument = SimpleNamespace(id=1, symbol="SBER", sources=[SimpleNamespace(source="MOEX")])
    candle = SimpleNamespace(
        id=10,
        instrument_id=1,
        timeframe="1d",
        timestamp=datetime(2024, 2, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1000"),
        source="MOEX",
    )

    call_n = {"n": 0}

    def scalars(_stmt):  # noqa: ANN001
        call_n["n"] += 1
        result = MagicMock()
        if call_n["n"] == 1:
            result.unique.return_value.all.return_value = [instrument]
        else:
            result.all.return_value = [candle]
        return result

    session.scalars.side_effect = scalars
    session.add = MagicMock()

    result = run_data_quality_checks(
        session,
        DataQualityContext(
            mode="historical",
            date_from=date(2024, 1, 1),
            date_to=date(2024, 2, 15),
        ),
    )

    assert result["mode"] == "historical"
    assert "missing_recent_data" not in result["by_type"]
    added_types = [call.args[0].issue_type for call in session.add.call_args_list]
    assert "missing_recent_data" not in added_types


def test_operational_emits_missing_recent_when_stale() -> None:
    session = MagicMock()
    instrument = SimpleNamespace(id=1, symbol="SBER", sources=[SimpleNamespace(source="MOEX")])
    stale_ts = datetime(2024, 2, 15, tzinfo=UTC)

    def scalars(_stmt):  # noqa: ANN001
        result = MagicMock()
        result.unique.return_value.all.return_value = [instrument]
        result.all.return_value = [
            SimpleNamespace(
                instrument_id=1,
                timestamp=stale_ts,
                open=Decimal("1"),
                high=Decimal("1"),
                low=Decimal("1"),
                close=Decimal("1"),
                volume=Decimal("1"),
            )
        ]
        return result

    session.scalars.side_effect = scalars
    session.scalar.return_value = stale_ts
    session.add = MagicMock()

    result = run_data_quality_checks(session, DataQualityContext(mode="operational"))
    assert result["mode"] == "operational"
    assert result["by_type"].get("missing_recent_data", 0) >= 1
