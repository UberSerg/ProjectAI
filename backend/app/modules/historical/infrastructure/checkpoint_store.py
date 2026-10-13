"""Durable backfill cursor for a real historical dataset.

The in-memory tuple in ``application.checkpoint`` stays for the small gate
tests. This store is the replacement that survives a process restart: open
the same caller-supplied SQLite file and ``load`` returns the saved cursor.
A content hash is inserted with ``INSERT OR IGNORE`` and is counted once.

The file is not PostgreSQL and does not write prospective memory, signals,
committee decisions, shadow orders, or broker executions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Same caps as application.checkpoint.STAGE_LIMITS. That module stays the
# in-memory gate; this store enforces the caps for a dataset on disk.
STAGE_LIMITS: dict[str, int] = {
    "pilot": 100,
    "stage_1000": 1_000,
    "stage_10000": 10_000,
}

_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    source_id TEXT NOT NULL PRIMARY KEY,
    cursor TEXT NOT NULL,
    stage TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    quarantined INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_hashes (
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (source_id, content_hash)
);
"""


@dataclass(frozen=True, slots=True)
class StoredCheckpoint:
    source_id: str
    cursor: str
    stage: str
    accepted: int
    quarantined: int
    updated_at: str


def assert_stage_request(requested: int, *, stage: str) -> None:
    """Refuse an unknown stage or a count outside that stage's cap."""
    if stage not in STAGE_LIMITS:
        raise ValueError(f"unknown backfill stage: {stage}")
    if requested <= 0:
        raise ValueError("backfill limit must be positive")
    limit = STAGE_LIMITS[stage]
    if requested > limit:
        raise ValueError(f"requested {requested} exceeds {stage} limit {limit}")


class CheckpointStore:
    """One SQLite file. Each process opens its own connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_DDL)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CheckpointStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def load(self, source_id: str) -> str | None:
        """Return the saved cursor, or ``None`` when this source has no row."""
        row = self._connection.execute(
            "SELECT cursor FROM checkpoints WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row["cursor"])

    def admit(
        self,
        source_id: str,
        content_hash: str,
        next_cursor: str,
        accepted: bool,
        stage: str,
    ) -> StoredCheckpoint:
        """Advance the cursor. A hash already stored does not change the counts."""
        assert_stage_request(1, stage=stage)
        try:
            current = self._connection.execute(
                """
                SELECT accepted, quarantined
                FROM checkpoints
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            accepted_count = int(current["accepted"]) if current is not None else 0
            quarantined_count = int(current["quarantined"]) if current is not None else 0
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO seen_hashes (source_id, content_hash)
                VALUES (?, ?)
                """,
                (source_id, content_hash),
            )
            if inserted.rowcount == 1:
                if accepted:
                    accepted_count += 1
                else:
                    quarantined_count += 1
                assert_stage_request(accepted_count + quarantined_count, stage=stage)
            updated_at = datetime.now(UTC).isoformat()
            self._connection.execute(
                """
                INSERT INTO checkpoints (
                    source_id, cursor, stage, accepted, quarantined, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    cursor = excluded.cursor,
                    stage = excluded.stage,
                    accepted = excluded.accepted,
                    quarantined = excluded.quarantined,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    next_cursor,
                    stage,
                    accepted_count,
                    quarantined_count,
                    updated_at,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return StoredCheckpoint(
            source_id=source_id,
            cursor=next_cursor,
            stage=stage,
            accepted=accepted_count,
            quarantined=quarantined_count,
            updated_at=updated_at,
        )

    def advance_after_commit(
        self,
        source_id: str,
        content_hash: str,
        next_cursor: str,
        accepted: bool,
        stage: str,
        *,
        run_new_items: int,
    ) -> StoredCheckpoint:
        """Move the cursor after the caller has committed the facts.

        ``run_new_items`` is the size of this bounded run. A later run may
        continue past rows already stored by an earlier run. A hash that is
        already stored does not change the counts.
        """
        if stage not in STAGE_LIMITS:
            raise ValueError(f"unknown backfill stage: {stage}")
        if run_new_items < 0:
            raise ValueError("run_new_items must be zero or positive")
        limit = STAGE_LIMITS[stage]
        if run_new_items > limit:
            raise ValueError(f"requested {run_new_items} exceeds {stage} limit {limit}")
        if not content_hash or not next_cursor:
            raise ValueError("content hash and cursor are required")
        try:
            current = self._connection.execute(
                """
                SELECT cursor, accepted, quarantined
                FROM checkpoints
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            accepted_count = int(current["accepted"]) if current is not None else 0
            quarantined_count = int(current["quarantined"]) if current is not None else 0
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO seen_hashes (source_id, content_hash)
                VALUES (?, ?)
                """,
                (source_id, content_hash),
            )
            if inserted.rowcount == 1:
                if accepted:
                    accepted_count += 1
                else:
                    quarantined_count += 1
            elif current is not None:
                next_cursor = str(current["cursor"])
            updated_at = datetime.now(UTC).isoformat()
            self._connection.execute(
                """
                INSERT INTO checkpoints (
                    source_id, cursor, stage, accepted, quarantined, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    cursor = excluded.cursor,
                    stage = excluded.stage,
                    accepted = excluded.accepted,
                    quarantined = excluded.quarantined,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    next_cursor,
                    stage,
                    accepted_count,
                    quarantined_count,
                    updated_at,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return StoredCheckpoint(
            source_id=source_id,
            cursor=next_cursor,
            stage=stage,
            accepted=accepted_count,
            quarantined=quarantined_count,
            updated_at=updated_at,
        )
