"""SQLite backfill checkpoint. No network and no PostgreSQL."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.modules.historical.infrastructure.checkpoint_store import (
    CheckpointStore,
    assert_stage_request,
)


def test_schema_has_checkpoint_and_seen_hash_tables(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path):
        pass

    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        checkpoints = connection.execute("PRAGMA table_info(checkpoints)").fetchall()
        seen_hashes = connection.execute("PRAGMA table_info(seen_hashes)").fetchall()

    assert [row[0] for row in tables] == ["checkpoints", "seen_hashes"]
    assert [(row[1], row[2], row[3], row[5]) for row in checkpoints] == [
        ("source_id", "TEXT", 1, 1),
        ("partition", "TEXT", 1, 2),
        ("cursor", "TEXT", 1, 0),
        ("stage", "TEXT", 1, 0),
        ("accepted", "INTEGER", 1, 0),
        ("quarantined", "INTEGER", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ]
    assert [(row[1], row[2], row[3], row[5]) for row in seen_hashes] == [
        ("source_id", "TEXT", 1, 1),
        ("partition", "TEXT", 1, 2),
        ("content_hash", "TEXT", 1, 3),
        ("committed", "INTEGER", 1, 0),
        ("complete", "INTEGER", 1, 0),
    ]


def test_stage_request_refuses_unknown_stage_and_oversized_counts() -> None:
    with pytest.raises(ValueError, match="unknown backfill stage"):
        assert_stage_request(1, stage="archive")
    with pytest.raises(ValueError, match="positive"):
        assert_stage_request(0, stage="pilot")

    assert_stage_request(100, stage="pilot")
    with pytest.raises(ValueError, match="exceeds"):
        assert_stage_request(101, stage="pilot")

    assert_stage_request(1_000, stage="stage_1000")
    with pytest.raises(ValueError, match="exceeds"):
        assert_stage_request(1_001, stage="stage_1000")

    assert_stage_request(10_000, stage="stage_10000")
    with pytest.raises(ValueError, match="exceeds"):
        assert_stage_request(10_001, stage="stage_10000")


def test_admit_stops_at_the_stage_limit_without_keeping_the_extra_hash(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        for index in range(100):
            stored = store.admit("CBR-01", f"hash-{index}", f"cursor-{index}", True, "pilot")
        assert stored.accepted == 100
        with pytest.raises(ValueError, match="exceeds"):
            store.admit("CBR-01", "hash-100", "cursor-100", True, "pilot")
        assert store.load("CBR-01") == "cursor-99"

        past_pilot = store.admit("MOEX-04", "hash-100", "cursor-100", True, "stage_1000")
        assert past_pilot.accepted == 1

    with sqlite3.connect(path) as connection:
        extra = connection.execute(
            "SELECT COUNT(*) FROM seen_hashes WHERE source_id = ? AND content_hash = ?",
            ("CBR-01", "hash-100"),
        ).fetchone()
        kept = connection.execute(
            "SELECT accepted, cursor FROM checkpoints WHERE source_id = ?",
            ("CBR-01",),
        ).fetchone()
    assert extra[0] == 0
    assert kept == (100, "cursor-99")


def test_reopened_database_resumes_and_ignores_a_duplicate_hash(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as first:
        assert first.load("CBR-01") is None
        accepted = first.admit("CBR-01", "abc", "2024-01-02", True, "pilot")
        quarantined = first.admit("CBR-01", "bad", "2024-01-03", False, "pilot")
        assert accepted.accepted == 1
        assert quarantined.accepted == 1
        assert quarantined.quarantined == 1

    with CheckpointStore(path) as second:
        assert second.load("CBR-01") == "2024-01-03"
        repeated = second.admit("CBR-01", "abc", "2024-01-04", True, "pilot")
        repeated_bad = second.admit("CBR-01", "bad", "2024-01-05", True, "pilot")
        fresh = second.admit("CBR-01", "def", "2024-01-06", True, "pilot")

    assert repeated.accepted == 1
    assert repeated.quarantined == 1
    assert repeated.cursor == "2024-01-04"
    assert repeated_bad.accepted == 1
    assert repeated_bad.quarantined == 1
    assert fresh.accepted == 2
    assert fresh.quarantined == 1
    assert fresh.cursor == "2024-01-06"

    with sqlite3.connect(path) as connection:
        hashes = connection.execute(
            "SELECT content_hash FROM seen_hashes WHERE source_id = ? ORDER BY content_hash",
            ("CBR-01",),
        ).fetchall()
        row = connection.execute(
            "SELECT cursor, accepted, quarantined FROM checkpoints WHERE source_id = ?",
            ("CBR-01",),
        ).fetchone()
    assert [item[0] for item in hashes] == ["abc", "bad", "def"]
    assert row == ("2024-01-06", 2, 1)


def test_sources_do_not_share_a_content_hash(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        first = store.admit("CBR-01", "abc", "cbr-cursor", True, "pilot")
        second = store.admit("MOEX-04", "abc", "moex-cursor", False, "pilot")
        assert first.accepted == 1
        assert second.quarantined == 1
        assert store.load("CBR-01") == "cbr-cursor"
        assert store.load("MOEX-04") == "moex-cursor"


def test_advance_after_commit_uses_this_run_not_the_lifetime(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        for index in range(100):
            store.admit("CBR-03", f"hash-{index}", f"cursor-{index}", True, "pilot")
        with pytest.raises(ValueError, match="exceeds"):
            store.advance_after_commit(
                "CBR-03",
                "hash-over",
                "cursor-over",
                True,
                "pilot",
                run_new_items=101,
            )
        continued = store.advance_after_commit(
            "CBR-03",
            "hash-next-run",
            "cursor-next-run",
            True,
            "pilot",
            run_new_items=1,
        )
        replay = store.advance_after_commit(
            "CBR-03",
            "hash-next-run",
            "cursor-rewound",
            True,
            "pilot",
            run_new_items=0,
        )

    assert continued.accepted == 101
    assert continued.cursor == "cursor-next-run"
    assert replay.accepted == 101
    assert replay.cursor == "cursor-next-run"
    with CheckpointStore(path) as reopened:
        assert reopened.load("CBR-03") == "cursor-next-run"
        with sqlite3.connect(path) as connection:
            extra = connection.execute(
                "SELECT COUNT(*) FROM seen_hashes WHERE source_id = ? AND content_hash = ?",
                ("CBR-03", "hash-over"),
            ).fetchone()
        assert extra is not None
        assert extra[0] == 0
