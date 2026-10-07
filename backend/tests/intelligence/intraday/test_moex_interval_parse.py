"""MOEX interval candle parsing — no live network."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.infrastructure.market.moex_interval_candles import (
    MOEX_INTERVAL_CODES,
    parse_moex_begin_msk,
    parse_moex_interval_candle_rows,
    parse_moex_interval_candles,
)

MSK = ZoneInfo("Europe/Moscow")


def _payload() -> dict:
    return {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": [
                [
                    100.0,
                    101.0,
                    102.0,
                    99.5,
                    1_000_000.0,
                    10_000,
                    "2024-06-03 10:00:00",
                    "2024-06-03 10:59:59",
                ],
                [
                    101.0,
                    100.5,
                    101.5,
                    100.0,
                    800_000.0,
                    8_000,
                    "2024-06-03 11:00:00",
                    "2024-06-03 11:59:59",
                ],
            ],
        }
    }


def test_interval_codes_exclude_15m() -> None:
    assert MOEX_INTERVAL_CODES["60m"] == 60
    assert MOEX_INTERVAL_CODES["10m"] == 10
    assert "15m" not in MOEX_INTERVAL_CODES


def test_parse_begin_as_moscow() -> None:
    dt = parse_moex_begin_msk("2024-06-03 10:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.astimezone(MSK).hour == 10
    assert dt.astimezone(UTC).hour == 7  # MSK = UTC+3


def test_parse_candles_ohlcv() -> None:
    bars = parse_moex_interval_candles(_payload())
    assert len(bars) == 2
    assert bars[0].close == Decimal("101.0")
    assert bars[0].volume == Decimal("10000")
    assert bars[0].timestamp.tzinfo is not None


def test_parse_rows_keeps_turnover_value() -> None:
    rows = parse_moex_interval_candle_rows(_payload())
    assert rows[0]["value"] == Decimal("1000000.0")
    assert rows[0]["begin_msk"].hour == 10
