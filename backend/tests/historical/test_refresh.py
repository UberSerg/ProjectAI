"""Incremental refresh and parser-version reprocessing. No network."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.historical.application.refresh import (
    RefreshCursor,
    VersionedRecord,
    plan_refresh,
    reprocess,
)

CURSOR_AT = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
LATER = CURSOR_AT + timedelta(hours=2)
EARLIER = CURSOR_AT - timedelta(hours=1)


def _record(
    parser_version: str,
    *,
    content_hash: str = "abc",
    first_observed_at: datetime = CURSOR_AT,
    generation: int = 1,
) -> VersionedRecord:
    return VersionedRecord(
        content_hash=content_hash,
        parser_version=parser_version,
        first_observed_at=first_observed_at,
        generation=generation,
    )


def test_plan_starts_after_the_cursor() -> None:
    plan = plan_refresh(RefreshCursor(first_observed_at=CURSOR_AT), now=LATER)
    assert plan.after == CURSOR_AT
    assert plan.until == LATER
    assert plan.first_observed_at == LATER
    assert plan.empty is False
    assert plan.covers(CURSOR_AT) is False
    assert plan.covers(LATER) is True
    assert plan.covers(CURSOR_AT + timedelta(seconds=1)) is True


def test_plan_does_not_move_first_observed_at_backward() -> None:
    plan = plan_refresh(RefreshCursor(first_observed_at=CURSOR_AT), now=EARLIER)
    assert plan.empty is True
    assert plan.after == CURSOR_AT
    assert plan.until == CURSOR_AT
    assert plan.first_observed_at == CURSOR_AT
    assert plan.first_observed_at > EARLIER
    assert plan.covers(EARLIER) is False
    assert plan.covers(CURSOR_AT) is False


def test_plan_at_the_cursor_instant_is_empty() -> None:
    plan = plan_refresh(RefreshCursor(first_observed_at=CURSOR_AT), now=CURSOR_AT)
    assert plan.empty is True
    assert plan.first_observed_at == CURSOR_AT


def test_plan_rejects_a_naive_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_refresh(RefreshCursor(first_observed_at=CURSOR_AT), now=datetime(2026, 10, 12, 13, 0))


def test_reprocess_keeps_the_old_parser_generation() -> None:
    original = _record("cbr_keyrate_v1")
    stored = [original]
    batch = reprocess(stored, new_parser_version="cbr_keyrate_v2")
    assert stored == [original]
    assert original.parser_version == "cbr_keyrate_v1"
    assert batch.retained[0] is original
    assert batch.retained[0].parser_version == "cbr_keyrate_v1"
    assert len(batch.produced) == 1
    assert batch.produced[0] is not original
    assert batch.produced[0].parser_version == "cbr_keyrate_v2"
    assert batch.produced[0].content_hash == original.content_hash
    assert batch.produced[0].generation == 2
    assert batch.produced[0].first_observed_at == original.first_observed_at
    assert [row.parser_version for row in batch.records] == ["cbr_keyrate_v1", "cbr_keyrate_v2"]


def test_same_content_hash_and_parser_version_is_a_noop() -> None:
    original = _record("cbr_keyrate_v1")
    first = reprocess((original,), new_parser_version="cbr_keyrate_v1")
    assert first.produced == ()
    assert first.retained == (original,)
    assert first.records == (original,)

    second = reprocess(first.records, new_parser_version="cbr_keyrate_v2")
    assert [row.parser_version for row in second.records] == ["cbr_keyrate_v1", "cbr_keyrate_v2"]
    again = reprocess(second.records, new_parser_version="cbr_keyrate_v2")
    assert again.produced == ()
    assert again.retained == second.records
    assert any(row.parser_version == "cbr_keyrate_v1" for row in again.records)


def test_changed_parser_version_is_a_new_generation() -> None:
    first = _record("cbr_keyrate_v1", generation=1)
    second = _record("cbr_keyrate_v2", generation=2)
    batch = reprocess((first, second), new_parser_version="cbr_keyrate_v3")
    assert batch.retained == (first, second)
    assert first.parser_version == "cbr_keyrate_v1"
    assert second.parser_version == "cbr_keyrate_v2"
    assert len(batch.produced) == 1
    assert batch.produced[0].parser_version == "cbr_keyrate_v3"
    assert batch.produced[0].generation == 3
    assert [row.parser_version for row in batch.records] == [
        "cbr_keyrate_v1",
        "cbr_keyrate_v2",
        "cbr_keyrate_v3",
    ]


def test_reprocess_does_not_duplicate_an_existing_parser_version() -> None:
    older = _record("cbr_keyrate_v1")
    current = _record("cbr_keyrate_v2", generation=2)
    batch = reprocess((older, current), new_parser_version="cbr_keyrate_v2")
    assert batch.produced == ()
    assert batch.records == (older, current)


def test_each_content_hash_gets_its_own_generation() -> None:
    left = _record("v1", content_hash="left")
    right = _record("v1", content_hash="right")
    batch = reprocess((left, right), new_parser_version="v2")
    assert batch.retained == (left, right)
    assert [row.content_hash for row in batch.produced] == ["left", "right"]
    assert {row.parser_version for row in batch.produced} == {"v2"}


def test_duplicate_hash_emits_one_generation_and_keeps_every_old_row() -> None:
    early = _record("v1", first_observed_at=CURSOR_AT)
    late = _record("v1", first_observed_at=LATER)
    batch = reprocess((late, early), new_parser_version="v2")
    assert batch.retained == (late, early)
    assert len(batch.produced) == 1
    assert batch.produced[0].first_observed_at == CURSOR_AT
    assert batch.produced[0].first_observed_at <= early.first_observed_at
    assert batch.produced[0].generation == 2
    assert [row.parser_version for row in batch.records] == ["v1", "v1", "v2"]


def test_reprocess_of_an_empty_batch_is_empty() -> None:
    batch = reprocess((), new_parser_version="v2")
    assert batch.retained == ()
    assert batch.produced == ()
    assert batch.records == ()


def test_reprocess_rejects_a_blank_parser_version() -> None:
    with pytest.raises(ValueError, match="new_parser_version"):
        reprocess((_record("v1"),), new_parser_version="  ")
