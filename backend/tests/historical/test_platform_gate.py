"""Shared registration and backfill gate. No network."""

import pytest

from app.modules.historical.application.checkpoint import (
    BackfillCheckpoint,
    admit,
    assert_bounded,
)
from app.modules.historical.application.registry import registered_sources


def test_registry_matches_verified_pilots() -> None:
    by_id = {item.source_id: item.pilot_status for item in registered_sources()}
    assert by_id["CBR-01"] == "READY"
    assert by_id["CBR-03"] == "READY"
    assert by_id["CBR-04"] == "READY"
    assert by_id["MOEX-04"] == "READY"
    assert by_id["MOEX-05"] == "READY"
    assert by_id["MOEX-06"] == "BLOCKED"
    assert by_id["FNS-01"] == "READY"
    assert by_id["IR-05"] == "PARTIAL"
    assert by_id["ROS-01"] == "PARTIAL"
    assert by_id["INT-01"] == "BLOCKED"
    assert by_id["DISC-01"] == "BLOCKED"
    assert by_id["NEWS-02"] == "PARTIAL"
    assert "CBR-05" not in by_id


def test_backfill_refuses_an_unbounded_request() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        assert_bounded(101, stage="pilot")
    assert_bounded(100, stage="pilot")


def test_checkpoint_resumes_and_ignores_duplicate_hash() -> None:
    start = BackfillCheckpoint(source_id="CBR-01", cursor="2024-01-01", stage="pilot")
    once = admit(start, content_hash="abc", next_cursor="2024-01-02", accepted=True)
    twice = admit(once, content_hash="abc", next_cursor="2024-01-03", accepted=True)
    assert once.accepted == 1
    assert twice.accepted == 1
    assert twice.resume_cursor() == "2024-01-03"
    assert twice.content_hashes == ("abc",)
