"""H3 history planner — no live network."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.modules.market.application.history_ranges import missing_coverage_ranges, plan_source_ranges


def _map(*, external_id: str, board: str, valid_from, valid_to, instrument_id: int = 1, id: int = 1):
    return SimpleNamespace(
        id=id,
        instrument_id=instrument_id,
        external_id=external_id,
        board=board,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_intersection_clips_to_proven_window() -> None:
    plans = plan_source_ranges(
        [_map(external_id="SBER", board="TQBR", valid_from=date(2013, 3, 25), valid_to=None)],
        date(2014, 1, 1),
        date(2020, 1, 1),
    )
    assert len(plans) == 1
    assert plans[0].board == "TQBR"
    assert plans[0].effective_from == date(2014, 1, 1)
    assert plans[0].effective_to == date(2020, 1, 1)


def test_later_listed_does_not_plan_before_valid_from() -> None:
    plans = plan_source_ranges(
        [_map(external_id="T", board="TQBR", valid_from=date(2024, 11, 28), valid_to=None)],
        date(2014, 1, 1),
        date(2015, 12, 31),
    )
    assert plans == []


def test_unknown_start_is_not_a_fallback() -> None:
    plans = plan_source_ranges(
        [_map(external_id="X", board="TQBR", valid_from=None, valid_to=None)],
        date(2014, 1, 1),
        date(2015, 1, 1),
    )
    assert plans == []


def test_multiple_windows_leave_gap() -> None:
    plans = plan_source_ranges(
        [
            _map(id=1, external_id="SBER", board="EQBR", valid_from=date(2011, 11, 21), valid_to=date(2013, 3, 25)),
            _map(id=2, external_id="SBER", board="TQBR", valid_from=date(2014, 6, 9), valid_to=None),
        ],
        date(2012, 1, 1),
        date(2015, 1, 1),
    )
    assert [(p.board, p.effective_from, p.effective_to) for p in plans] == [
        ("EQBR", date(2012, 1, 1), date(2013, 3, 24)),
        ("TQBR", date(2014, 6, 9), date(2015, 1, 1)),
    ]


def test_exclusive_valid_to_is_not_requested() -> None:
    plans = plan_source_ranges(
        [_map(external_id="SBER", board="EQBR", valid_from=date(2011, 11, 21), valid_to=date(2013, 3, 25))],
        date(2013, 3, 25),
        date(2013, 4, 1),
    )
    assert plans == []


def test_missing_coverage_skips_already_loaded_interior() -> None:
    assert missing_coverage_ranges(date(2015, 1, 1), date(2026, 1, 1), date(2014, 1, 1), date(2026, 1, 1)) == [
        (date(2014, 1, 1), date(2014, 12, 31))
    ]
    assert missing_coverage_ranges(date(2014, 1, 1), date(2026, 1, 1), date(2014, 1, 1), date(2026, 1, 1)) == []
