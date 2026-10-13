"""Durable backfill cursor for a real historical dataset.

The in-memory tuple in ``application.checkpoint`` stays for the small gate
tests. This store is the replacement that survives a process restart: open
the same caller-supplied SQLite file and ``load`` returns the saved cursor.
A content hash is inserted with ``INSERT OR IGNORE`` and is counted once.
Each ``(source_id, partition)`` pair has its own cursor. An empty partition
is the legacy source-level cursor.

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

_CHECKPOINTS_COLUMNS = """
    source_id TEXT NOT NULL,
    partition TEXT NOT NULL,
    cursor TEXT NOT NULL,
    stage TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    quarantined INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, partition)
"""

_SEEN_HASHES_COLUMNS = """
    source_id TEXT NOT NULL,
    partition TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    committed INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    PRIMARY KEY (source_id, partition, content_hash)
"""

_DDL = f"""
CREATE TABLE IF NOT EXISTS checkpoints ({_CHECKPOINTS_COLUMNS}
);

CREATE TABLE IF NOT EXISTS seen_hashes ({_SEEN_HASHES_COLUMNS}
);
"""

_LEGACY_PARTITION = ""


@dataclass(frozen=True, slots=True)
class StoredCheckpoint:
    source_id: str
    cursor: str
    stage: str
    accepted: int
    quarantined: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentProgress:
    """How far one content hash has been committed inside a partition."""

    committed: int
    complete: bool


def _document_advanced(before: DocumentProgress | None, after: DocumentProgress | None) -> bool:
    """True when this call committed more of an unfinished document."""
    if after is None:
        return False
    if before is None:
        return True
    if before.complete:
        return False
    return after.committed > before.committed or (after.complete and not before.complete)


def assert_stage_request(requested: int, *, stage: str) -> None:
    """Refuse an unknown stage or a count outside that stage's cap."""
    if stage not in STAGE_LIMITS:
        raise ValueError(f"unknown backfill stage: {stage}")
    if requested <= 0:
        raise ValueError("backfill limit must be positive")
    limit = STAGE_LIMITS[stage]
    if requested > limit:
        raise ValueError(f"requested {requested} exceeds {stage} limit {limit}")


def _checkpoint_columns(connection: sqlite3.Connection) -> list[str] | None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
    ).fetchone()
    if exists is None:
        return None
    rows = connection.execute("PRAGMA table_info(checkpoints)").fetchall()
    return [str(row["name"]) for row in rows]


def _migrate_to_partitions(connection: sqlite3.Connection) -> None:
    """Copy source-level rows into the partitioned schema and keep the old bytes.

    The previous tables stay addressable as ``checkpoints_v2`` and
    ``seen_hashes_v2`` after the names are swapped. Nothing is dropped.
    Legacy hashes are complete documents with no stored offset.
    """
    connection.execute(f"CREATE TABLE checkpoints_v2 ({_CHECKPOINTS_COLUMNS})")
    connection.execute(f"CREATE TABLE seen_hashes_v2 ({_SEEN_HASHES_COLUMNS})")
    connection.execute(
        """
        INSERT INTO checkpoints_v2 (
            source_id, partition, cursor, stage, accepted, quarantined, updated_at
        )
        SELECT source_id, '', cursor, stage, accepted, quarantined, updated_at
        FROM checkpoints
        """
    )
    connection.execute(
        """
        INSERT INTO seen_hashes_v2 (
            source_id, partition, content_hash, committed, complete
        )
        SELECT source_id, '', content_hash, 0, 1
        FROM seen_hashes
        """
    )
    connection.execute("ALTER TABLE checkpoints RENAME TO checkpoints_holding")
    connection.execute("ALTER TABLE checkpoints_v2 RENAME TO checkpoints")
    connection.execute("ALTER TABLE checkpoints_holding RENAME TO checkpoints_v2")
    connection.execute("ALTER TABLE seen_hashes RENAME TO seen_hashes_holding")
    connection.execute("ALTER TABLE seen_hashes_v2 RENAME TO seen_hashes")
    connection.execute("ALTER TABLE seen_hashes_holding RENAME TO seen_hashes_v2")


class CheckpointStore:
    """One SQLite file. Each process opens its own connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        try:
            self._ensure_schema()
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CheckpointStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        columns = _checkpoint_columns(self._connection)
        if columns is None or "partition" in columns:
            self._connection.executescript(_DDL)
            return
        _migrate_to_partitions(self._connection)

    def load(self, source_id: str, *, partition: str = _LEGACY_PARTITION) -> str | None:
        """Return the saved cursor, or ``None`` when this partition has no row."""
        row = self._connection.execute(
            """
            SELECT cursor
            FROM checkpoints
            WHERE source_id = ? AND partition = ?
            """,
            (source_id, partition),
        ).fetchone()
        if row is None:
            return None
        return str(row["cursor"])

    def document_progress(
        self,
        source_id: str,
        content_hash: str,
        *,
        partition: str = _LEGACY_PARTITION,
    ) -> DocumentProgress | None:
        """Return committed progress for one hash, or ``None`` when it is unseen."""
        row = self._connection.execute(
            """
            SELECT committed, complete
            FROM seen_hashes
            WHERE source_id = ? AND partition = ? AND content_hash = ?
            """,
            (source_id, partition, content_hash),
        ).fetchone()
        if row is None:
            return None
        return DocumentProgress(committed=int(row["committed"]), complete=bool(row["complete"]))

    def admit(
        self,
        source_id: str,
        content_hash: str,
        next_cursor: str,
        accepted: bool,
        stage: str,
    ) -> StoredCheckpoint:
        """Advance the legacy cursor. A hash already stored does not change the counts."""
        assert_stage_request(1, stage=stage)
        try:
            _current, accepted_count, quarantined_count = self._counts(source_id, _LEGACY_PARTITION)
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO seen_hashes (
                    source_id, partition, content_hash, committed, complete
                )
                VALUES (?, ?, ?, 0, 1)
                """,
                (source_id, _LEGACY_PARTITION, content_hash),
            )
            if inserted.rowcount == 1:
                if accepted:
                    accepted_count += 1
                else:
                    quarantined_count += 1
                assert_stage_request(accepted_count + quarantined_count, stage=stage)
            updated_at = self._save_checkpoint(
                source_id,
                _LEGACY_PARTITION,
                next_cursor,
                stage,
                accepted_count,
                quarantined_count,
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
        partition: str = _LEGACY_PARTITION,
        document_offset: int | None = None,
        document_complete: bool = True,
    ) -> StoredCheckpoint:
        """Move one partition cursor after the caller has committed the facts.

        ``run_new_items`` is the size of this bounded run. A later run may
        continue past rows already stored by an earlier run. A hash that is
        already stored does not change the counts and does not replace the
        cursor. An incomplete document keeps ``committed`` at
        ``document_offset``; a later call may raise that offset and mark the
        same hash complete.
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
            current, accepted_count, quarantined_count = self._counts(source_id, partition)
            before = self.document_progress(source_id, content_hash, partition=partition)
            if self._insert_hash(
                source_id,
                partition,
                content_hash,
                document_offset=document_offset,
                document_complete=document_complete,
            ):
                if accepted:
                    accepted_count += 1
                else:
                    quarantined_count += 1
            elif current is not None and not _document_advanced(
                before,
                self.document_progress(source_id, content_hash, partition=partition),
            ):
                next_cursor = str(current["cursor"])
            updated_at = self._save_checkpoint(
                source_id,
                partition,
                next_cursor,
                stage,
                accepted_count,
                quarantined_count,
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

    def _counts(self, source_id: str, partition: str) -> tuple[sqlite3.Row | None, int, int]:
        current = self._connection.execute(
            """
            SELECT cursor, accepted, quarantined
            FROM checkpoints
            WHERE source_id = ? AND partition = ?
            """,
            (source_id, partition),
        ).fetchone()
        accepted_count = int(current["accepted"]) if current is not None else 0
        quarantined_count = int(current["quarantined"]) if current is not None else 0
        return current, accepted_count, quarantined_count

    def _save_checkpoint(
        self,
        source_id: str,
        partition: str,
        cursor: str,
        stage: str,
        accepted: int,
        quarantined: int,
    ) -> str:
        updated_at = datetime.now(UTC).isoformat()
        self._connection.execute(
            """
            INSERT INTO checkpoints (
                source_id, partition, cursor, stage, accepted, quarantined, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, partition) DO UPDATE SET
                cursor = excluded.cursor,
                stage = excluded.stage,
                accepted = excluded.accepted,
                quarantined = excluded.quarantined,
                updated_at = excluded.updated_at
            """,
            (source_id, partition, cursor, stage, accepted, quarantined, updated_at),
        )
        return updated_at

    def _insert_hash(
        self,
        source_id: str,
        partition: str,
        content_hash: str,
        *,
        document_offset: int | None,
        document_complete: bool,
    ) -> bool:
        """Insert the hash once. Return True when this call stored it.

        A repeat may raise ``committed`` and set ``complete`` to 1. It does
        not lower an offset and does not clear a completed document.
        """
        complete_flag = 1 if document_complete else 0
        committed = 0 if document_offset is None else document_offset
        inserted = self._connection.execute(
            """
            INSERT OR IGNORE INTO seen_hashes (
                source_id, partition, content_hash, committed, complete
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_id, partition, content_hash, committed, complete_flag),
        )
        if inserted.rowcount == 1:
            return True
        if document_offset is None:
            self._connection.execute(
                """
                UPDATE seen_hashes
                SET complete = CASE WHEN ? = 1 THEN 1 ELSE complete END
                WHERE source_id = ? AND partition = ? AND content_hash = ?
                """,
                (complete_flag, source_id, partition, content_hash),
            )
            return False
        self._connection.execute(
            """
            UPDATE seen_hashes
            SET committed = CASE WHEN ? > committed THEN ? ELSE committed END,
                complete = CASE WHEN ? = 1 THEN 1 ELSE complete END
            WHERE source_id = ? AND partition = ? AND content_hash = ?
            """,
            (
                document_offset,
                document_offset,
                complete_flag,
                source_id,
                partition,
                content_hash,
            ),
        )
        return False
