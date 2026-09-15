"""Historical equity universe V3 — research cohort + delisted inventory."""

from __future__ import annotations

from datetime import date

from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V3,
    HistoricalUniverseMemberV3,
    _load_inventory_v3,
    universe_as_of_v3,
)


def test_inventory_seed_includes_urka_delisted() -> None:
    members = _load_inventory_v3()
    assert any(m.get("secid") == "URKA" for m in members)
    urka = next(m for m in members if m["secid"] == "URKA")
    assert urka["status"] == "DELISTED"
    assert urka["eligible_to"] == "2022-12-13"


def test_v3_member_as_of_rules() -> None:
    urka = HistoricalUniverseMemberV3(
        secid="URKA",
        instrument_id=None,
        eligible_from=date(2013, 3, 25),
        eligible_to=date(2022, 12, 13),
        eligible_from_quality="MOEX_BOARD_LISTED_FROM",
        eligible_to_quality="MOEX_BOARD_LISTED_TILL",
        status="DELISTED",
        in_current_research_cohort=False,
    )
    assert urka.includes(date(2022, 6, 1))
    assert not urka.includes(date(2023, 1, 1))
    assert HISTORICAL_EQUITY_UNIVERSE_V3.endswith("v3")


def test_universe_as_of_v3_callable_signature() -> None:
    # Smoke that symbol is importable; DB integration covered live.
    assert callable(universe_as_of_v3)
