"""Partitioned SQLite checkpoints. No network and no PostgreSQL."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.modules.historical.infrastructure.checkpoint_store import (
    CheckpointStore,
    DocumentProgress,
)

_LEGACY_DDL = """
CREATE TABLE checkpoints (
    source_id TEXT NOT NULL PRIMARY KEY,
    cursor TEXT NOT NULL,
    stage TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    quarantined INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE seen_hashes (
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (source_id, content_hash)
);
"""


def test_partitions_keep_independent_cursors(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        store.advance_after_commit(
            "MOEX-04",
            "sber-hash-1",
            "sber-1",
            True,
            "pilot",
            run_new_items=1,
            partition="TQBR:SBER",
        )
        store.advance_after_commit(
            "MOEX-04",
            "lkoh-hash-1",
            "lkoh-1",
            True,
            "pilot",
            run_new_items=1,
            partition="TQBR:LKOH",
        )
        assert store.load("MOEX-04") is None
        assert store.load("MOEX-04", partition="TQBR:SBER") == "sber-1"
        assert store.load("MOEX-04", partition="TQBR:LKOH") == "lkoh-1"

    with CheckpointStore(path) as reopened:
        reopened.advance_after_commit(
            "MOEX-04",
            "sber-hash-2",
            "sber-2",
            True,
            "pilot",
            run_new_items=1,
            partition="TQBR:SBER",
        )
        assert reopened.load("MOEX-04", partition="TQBR:LKOH") == "lkoh-1"
        assert reopened.load("MOEX-04", partition="TQBR:SBER") == "sber-2"


def test_same_content_hash_does_not_move_the_other_partition(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        sber = store.advance_after_commit(
            "MOEX-04",
            "shared-hash",
            "sber-1",
            True,
            "pilot",
            run_new_items=1,
            partition="TQBR:SBER",
        )
        lkoh = store.advance_after_commit(
            "MOEX-04",
            "shared-hash",
            "lkoh-1",
            False,
            "pilot",
            run_new_items=1,
            partition="TQBR:LKOH",
        )
        assert sber.accepted == 1
        assert sber.cursor == "sber-1"
        assert lkoh.quarantined == 1
        assert lkoh.cursor == "lkoh-1"
        replay = store.advance_after_commit(
            "MOEX-04",
            "shared-hash",
            "sber-rewound",
            True,
            "pilot",
            run_new_items=0,
            partition="TQBR:SBER",
        )
        assert replay.accepted == 1
        assert replay.quarantined == 0
        assert replay.cursor == "sber-1"
        assert store.load("MOEX-04", partition="TQBR:LKOH") == "lkoh-1"
        assert store.load("MOEX-04", partition="TQBR:SBER") == "sber-1"


def test_partial_document_progress_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with CheckpointStore(path) as store:
        assert store.document_progress("MOEX-04", "doc-hash", partition="TQBR:SBER") is None
        started = store.advance_after_commit(
            "MOEX-04",
            "doc-hash",
            "sber-partial",
            True,
            "pilot",
            run_new_items=1,
            partition="TQBR:SBER",
            document_offset=3,
            document_complete=False,
        )
        assert started.accepted == 1
        assert store.document_progress("MOEX-04", "doc-hash", partition="TQBR:SBER") == DocumentProgress(
            committed=3,
            complete=False,
        )
        finished = store.advance_after_commit(
            "MOEX-04",
            "doc-hash",
            "sber-done",
            True,
            "pilot",
            run_new_items=0,
            partition="TQBR:SBER",
            document_offset=8,
            document_complete=True,
        )
        assert finished.accepted == 1
        assert finished.cursor == "sber-done"
        replay = store.advance_after_commit(
            "MOEX-04",
            "doc-hash",
            "sber-rewound",
            True,
            "pilot",
            run_new_items=0,
            partition="TQBR:SBER",
            document_offset=8,
            document_complete=True,
        )
        assert replay.cursor == "sber-done"
        assert store.document_progress("MOEX-04", "doc-hash", partition="TQBR:SBER") == DocumentProgress(
            committed=8,
            complete=True,
        )

    with CheckpointStore(path) as reopened:
        assert reopened.document_progress("MOEX-04", "doc-hash", partition="TQBR:SBER") == DocumentProgress(
            committed=8,
            complete=True,
        )
        assert reopened.load("MOEX-04", partition="TQBR:SBER") == "sber-done"


def test_legacy_schema_keeps_the_saved_cursor(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(_LEGACY_DDL)
        connection.execute(
            """
            INSERT INTO checkpoints (
                source_id, cursor, stage, accepted, quarantined, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("MOEX-04", "legacy-cursor", "pilot", 4, 1, "2024-05-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO seen_hashes (source_id, content_hash) VALUES (?, ?)",
            ("MOEX-04", "legacy-hash"),
        )

    with CheckpointStore(path) as store:
        assert store.load("MOEX-04") == "legacy-cursor"
        assert store.document_progress("MOEX-04", "legacy-hash") == DocumentProgress(committed=0, complete=True)

    with CheckpointStore(path) as reopened:
        assert reopened.load("MOEX-04") == "legacy-cursor"

    with sqlite3.connect(path) as connection:
        current = connection.execute(
            """
            SELECT cursor, accepted, quarantined
            FROM checkpoints
            WHERE source_id = ? AND partition = ''
            """,
            ("MOEX-04",),
        ).fetchone()
        preserved = connection.execute(
            "SELECT cursor, accepted, quarantined FROM checkpoints_v2 WHERE source_id = ?",
            ("MOEX-04",),
        ).fetchone()
        preserved_hash = connection.execute(
            "SELECT content_hash FROM seen_hashes_v2 WHERE source_id = ?",
            ("MOEX-04",),
        ).fetchone()
    assert current == ("legacy-cursor", 4, 1)
    assert preserved == ("legacy-cursor", 4, 1)
    assert preserved_hash == ("legacy-hash",)
