"""MOEX intraday quote parsing — no live network."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.ports.intraday_market import MarketSessionStatus, QuoteFreshness
from app.infrastructure.market.moex_intraday import parse_board_securities_payload


def _payload() -> dict:
    return {
        "securities": {
            "columns": ["SECID", "BOARDID", "PREVPRICE", "STATUS", "PREVLEGALCLOSEPRICE"],
            "data": [
                ["SBER", "TQBR", 250.0, "A", 249.5],
                ["GAZP", "TQBR", 120.0, "A", 119.0],
            ],
        },
        "marketdata": {
            "columns": [
                "SECID",
                "BOARDID",
                "OPEN",
                "LAST",
                "BID",
                "OFFER",
                "VOLTODAY",
                "NUMTRADES",
                "UPDATETIME",
                "SYSTIME",
                "STATUS",
                "TIME",
                "TRADINGSTATUS",
            ],
            "data": [
                [
                    "SBER",
                    "TQBR",
                    251.0,
                    252.5,
                    252.0,
                    252.6,
                    1_000_000,
                    5000,
                    "10:05:00",
                    "2026-09-05 10:05:01",
                    "A",
                    "10:05:00",
                    "T",
                ],
                [
                    "GAZP",
                    "TQBR",
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                    "09:50:00",
                    "2026-09-05 09:50:00",
                    "A",
                    "09:50:00",
                    "B",
                ],
            ],
        },
    }


def test_parse_board_securities_open_and_last() -> None:
    observed = datetime(2026, 9, 5, 10, 6, tzinfo=UTC)
    quotes = parse_board_securities_payload(
        _payload(),
        board="TQBR",
        wanted={"SBER", "GAZP"},
        observed_at=observed,
    )
    by_secid = {q.secid: q for q in quotes}
    sber = by_secid["SBER"]
    assert sber.open_price == 251.0
    assert sber.last_price == 252.5
    assert sber.previous_close == 249.5
    assert sber.market_status is MarketSessionStatus.OPEN
    assert sber.freshness is QuoteFreshness.LIVE
    assert sber.board == "TQBR"

    gazp = by_secid["GAZP"]
    assert gazp.open_price is None
    assert gazp.market_status is MarketSessionStatus.PREOPEN
    assert gazp.freshness is QuoteFreshness.SESSION_NOT_STARTED


def test_parse_omits_unknown_secids() -> None:
    observed = datetime(2026, 9, 5, 10, 6, tzinfo=UTC)
    quotes = parse_board_securities_payload(
        _payload(),
        board="TQBR",
        wanted={"ZZZZ"},
        observed_at=observed,
    )
    assert quotes == []


def test_parse_does_not_invent_open() -> None:
    observed = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    payload = {
        "securities": {
            "columns": ["SECID", "BOARDID", "PREVPRICE", "STATUS", "PREVLEGALCLOSEPRICE"],
            "data": [["SBER", "TQBR", 250.0, "A", 249.5]],
        },
        "marketdata": {
            "columns": [
                "SECID",
                "BOARDID",
                "OPEN",
                "LAST",
                "BID",
                "OFFER",
                "VOLTODAY",
                "NUMTRADES",
                "UPDATETIME",
                "SYSTIME",
                "STATUS",
                "TIME",
                "TRADINGSTATUS",
            ],
            "data": [
                [
                    "SBER",
                    "TQBR",
                    None,
                    252.0,
                    251.0,
                    252.0,
                    10,
                    1,
                    "12:00:00",
                    "2026-09-05 12:00:00",
                    "A",
                    "12:00:00",
                    "T",
                ]
            ],
        },
    }
    quotes = parse_board_securities_payload(
        payload, board="TQBR", wanted={"SBER"}, observed_at=observed
    )
    assert len(quotes) == 1
    assert quotes[0].open_price is None
    assert quotes[0].last_price == 252.0
