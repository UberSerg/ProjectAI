"""Bounded backfill orchestration. The page callback is a fake: no network."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from app.modules.historical.application.orchestrate import (
    BoundedRun,
    PageRecord,
    run_bounded,
)
from app.modules.historical.application.registry import registered_sources, require_registered

Fetch = Callable[[str], Sequence[PageRecord]]


def _refuse_fetch(_cursor: str) -> list[PageRecord]:
    raise AssertionError("fetch_page must not run")


def _catalog(count: int, *, page_size: int) -> tuple[Fetch, list[str]]:
    rows = [
        PageRecord(content_hash=f"h{index}", next_cursor=str(index + 1))
        for index in range(count)
    ]
    calls: list[str] = []

    def fetch_page(cursor: str) -> list[PageRecord]:
        calls.append(cursor)
        start = int(cursor) if cursor else 0
        return rows[start : start + page_size]

    return fetch_page, calls


def test_unknown_source_raises_before_fetch() -> None:
    with pytest.raises(ValueError, match="unknown historical source: ROS-02"):
        run_bounded("ROS-02", stage="pilot", requested=101, fetch_page=_refuse_fetch)
    with pytest.raises(ValueError, match="unknown historical source"):
        require_registered("NOT-A-SOURCE")


@pytest.mark.parametrize(
    "source_id",
    [item.source_id for item in registered_sources() if item.pilot_status == "BLOCKED"],
)
def test_blocked_sources_are_refused_for_backfill(source_id: str) -> None:
    assert source_id in {
        "MOEX-06",
        "DISC-01",
        "DISC-02",
        "INT-01",
        "INT-02",
        "FNS-03",
        "CBR-05",
        "IR-07",
    }
    with pytest.raises(ValueError, match=f"BLOCKED source: {source_id}"):
        run_bounded(source_id, stage="pilot", requested=1, fetch_page=_refuse_fetch)


def test_blocked_source_is_refused_before_the_stage_limit() -> None:
    with pytest.raises(ValueError, match="BLOCKED source: MOEX-06"):
        run_bounded("MOEX-06", stage="pilot", requested=101, fetch_page=_refuse_fetch)


@pytest.mark.parametrize(
    ("stage", "requested"),
    [("pilot", 101), ("stage_1000", 1001), ("stage_10000", 10_001)],
)
def test_requested_above_the_stage_limit_is_refused(stage: str, requested: int) -> None:
    with pytest.raises(ValueError, match="exceeds"):
        run_bounded("CBR-01", stage=stage, requested=requested, fetch_page=_refuse_fetch)


def test_unknown_stage_and_non_positive_request_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown backfill stage"):
        run_bounded("CBR-01", stage="archive", requested=1, fetch_page=_refuse_fetch)
    with pytest.raises(ValueError, match="positive"):
        run_bounded("MOEX-04", stage="pilot", requested=0, fetch_page=_refuse_fetch)


def test_pilot_stops_at_one_hundred_even_when_more_rows_exist() -> None:
    fetch_page, calls = _catalog(250, page_size=40)
    result = run_bounded("CBR-01", stage="pilot", requested=100, fetch_page=fetch_page)
    assert result.accepted == 100
    assert result.content_hashes == tuple(f"h{index}" for index in range(100))
    assert result.cursor == "100"
    assert result.skipped == 0
    assert calls == ["", "40", "80"]


def test_stage_1000_stops_at_one_thousand() -> None:
    fetch_page, calls = _catalog(1005, page_size=400)
    result = run_bounded("MOEX-01", stage="stage_1000", requested=1000, fetch_page=fetch_page)
    assert result.accepted == 1000
    assert result.cursor == "1000"
    assert len(calls) == 3


def test_short_page_stops_when_the_callback_is_exhausted() -> None:
    fetch_page, calls = _catalog(3, page_size=2)
    result = run_bounded("FNS-01", stage="pilot", requested=100, fetch_page=fetch_page)
    assert result == BoundedRun(
        source_id="FNS-01",
        stage="pilot",
        cursor="3",
        accepted=3,
        skipped=0,
        content_hashes=("h0", "h1", "h2"),
    )
    assert calls == ["", "2", "3"]


def test_seen_hashes_do_not_count_again() -> None:
    fetch_page, _calls = _catalog(5, page_size=5)
    asked: list[str] = []

    def seen(digest: str) -> bool:
        asked.append(digest)
        return digest in {"h0", "h2"}

    result = run_bounded(
        "ROS-01",
        stage="pilot",
        requested=10,
        fetch_page=fetch_page,
        seen=seen,
    )
    assert result.accepted == 3
    assert result.skipped == 2
    assert result.content_hashes == ("h1", "h3", "h4")
    assert asked == ["h0", "h1", "h2", "h3", "h4"]


def test_repeated_hash_inside_the_run_counts_once() -> None:
    def fetch_page(cursor: str) -> list[PageRecord]:
        if cursor == "":
            return [PageRecord("h0", "1")]
        if cursor == "1":
            return [PageRecord("h0", "2"), PageRecord("h1", "3")]
        return []

    result = run_bounded(
        "NEWS-02",
        stage="pilot",
        requested=10,
        fetch_page=fetch_page,
        seen=lambda _digest: False,
    )
    assert result.accepted == 2
    assert result.skipped == 1
    assert result.content_hashes == ("h0", "h1")
    assert result.cursor == "3"


def test_resume_cursor_is_passed_to_the_callback() -> None:
    fetch_page, calls = _catalog(6, page_size=2)
    result = run_bounded(
        "MOEX-04",
        stage="stage_1000",
        requested=2,
        fetch_page=fetch_page,
        cursor="2",
    )
    assert calls == ["2"]
    assert result.cursor == "4"
    assert result.content_hashes == ("h2", "h3")


def test_partial_source_can_run_and_registry_entries_stay() -> None:
    fetch_page, _calls = _catalog(1, page_size=1)
    result = run_bounded("CBR-06", stage="pilot", requested=1, fetch_page=fetch_page)
    assert result.accepted == 1
    by_id = {item.source_id: item.pilot_status for item in registered_sources()}
    assert by_id["CBR-01"] == "READY"
    assert by_id["MOEX-06"] == "BLOCKED"
    assert by_id["DISC-01"] == "BLOCKED"
    assert by_id["INT-01"] == "BLOCKED"
    assert by_id["CBR-04"] == "READY"
    assert by_id["CBR-05"] == "BLOCKED"
    assert "ROS-02" not in by_id


def test_runner_source_does_not_touch_network_or_storage() -> None:
    from pathlib import Path

    import app.modules.historical.application.orchestrate as orchestrate

    text = Path(orchestrate.__file__).read_text(encoding="utf-8")
    for banned in ("httpx", "requests", "urllib", "socket", "psycopg", "sqlalchemy", "polza"):
        assert banned not in text
