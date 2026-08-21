"""Parser and incremental unit tests (no live network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from app.domain.ports.market_data import CandleBar
from app.infrastructure.market.cbr import parse_cbr_fx
from app.infrastructure.market.moex_iss import parse_moex_history
from app.modules.market.application.incremental import compute_incremental_range
from app.modules.market.application.ingest import deduplicate_records

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_compute_incremental_range_backfill_when_empty() -> None:
    result = compute_incremental_range(
        last_timestamp_date=None,
        default_from=date(2015, 1, 1),
        today=date(2015, 1, 10),
    )
    assert result == (date(2015, 1, 1), date(2015, 1, 10))


def test_compute_incremental_range_skips_when_current() -> None:
    assert (
        compute_incremental_range(
            last_timestamp_date=date(2024, 1, 10),
            default_from=date(2015, 1, 1),
            today=date(2024, 1, 10),
        )
        is None
    )


def test_deduplicate_records_keeps_last() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    first = CandleBar(ts, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), None)
    second = CandleBar(ts, Decimal("2"), Decimal("2"), Decimal("2"), Decimal("2"), None)
    assert deduplicate_records([first, second]) == [second]


def test_parse_moex_history_fixture() -> None:
    payload = {
        "history": {
            "columns": ["TRADEDATE", "OPEN", "HIGH", "LOW", "CLOSE", "LEGALCLOSEPRICE", "VOLUME"],
            "data": [["2024-01-03", 100, 110, 90, 105, 105, 1000]],
        }
    }
    bars = parse_moex_history(payload)
    assert len(bars) == 1
    assert bars[0].close == Decimal("105")


def test_parse_cbr_fx_fixture() -> None:
    xml = """<?xml version="1.0" encoding="windows-1251"?>
    <ValCurs>
      <Record Date="10.01.2024" Id="R01235">
        <Nominal>1</Nominal>
        <Value>90,4040</Value>
      </Record>
    </ValCurs>
    """
    points = parse_cbr_fx(xml)
    assert len(points) == 1
    assert points[0].value == Decimal("90.4040")
