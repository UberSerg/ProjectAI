"""Bulk staging ingest for External Deep History V0.

COPY into an UNLOGGED temp table per chunk, then INSERT ... ON CONFLICT DO NOTHING
into market.external_candles_daily. Bounded transaction per chunk, idempotent by
file sha256. Never writes market.candles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.market_history.domain.types import (
    PARSER_VERSION,
    SOURCE_CODE,
    SourceStatus,
)
from app.modules.market_history.infrastructure.models import ExternalSource
from app.modules.market_history.infrastructure.parser import (
    FileFingerprint,
    ParsedRow,
    file_fingerprint,
    iter_chunks,
)

logger = get_logger(__name__, component="market_history")

DEFAULT_BATCH_ROWS = 50_000

_TEMP_TABLE = "tmp_external_candles_chunk"

_CREATE_TEMP = text(
    f"""
    CREATE TEMP TABLE IF NOT EXISTS {_TEMP_TABLE} (
        source_symbol TEXT,
        trade_date DATE,
        open NUMERIC(20, 8),
        high NUMERIC(20, 8),
        low NUMERIC(20, 8),
        close NUMERIC(20, 8),
        volume NUMERIC(28, 8),
        value NUMERIC(28, 8),
        reject_reason TEXT
    ) ON COMMIT DROP;
    """
)

_INSERT_FROM_TEMP = text(
    f"""
    INSERT INTO market.external_candles_daily (
        source_id, source_symbol, trade_date, open, high, low, close, volume, value, reject_reason
    )
    SELECT
        :source_id, t.source_symbol, t.trade_date, t.open, t.high, t.low,
        t.close, t.volume, t.value, t.reject_reason
    FROM (
        SELECT DISTINCT ON (source_symbol, trade_date) *
        FROM {_TEMP_TABLE}
        ORDER BY source_symbol, trade_date
    ) AS t
    ON CONFLICT (source_id, source_symbol, trade_date) DO NOTHING;
    """
)

_COPY_SQL = (
    f"COPY {_TEMP_TABLE} "
    "(source_symbol, trade_date, open, high, low, close, volume, value, reject_reason) "
    "FROM STDIN"
)


@dataclass(slots=True)
class IngestResult:
    source_id: int | None = None
    status: str = "SUCCESS"
    rows_read: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    rows_malformed: int = 0
    rows_inserted: int = 0
    rows_skipped_conflict: int = 0
    chunks: int = 0
    elapsed_sec: float = 0.0
    fingerprint: FileFingerprint | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_per_sec(self) -> float:
        if self.elapsed_sec <= 0:
            return 0.0
        return round(self.rows_read / self.elapsed_sec, 1)

    def balances(self) -> bool:
        return self.rows_read == self.rows_valid + self.rows_rejected + self.rows_malformed

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "rows_read": self.rows_read,
            "rows_valid": self.rows_valid,
            "rows_rejected": self.rows_rejected,
            "rows_malformed": self.rows_malformed,
            "rows_inserted": self.rows_inserted,
            "rows_skipped_conflict": self.rows_skipped_conflict,
            "row_accounting_balanced": self.balances(),
            "chunks": self.chunks,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "rows_per_sec": self.rows_per_sec,
            "file_name": self.fingerprint.file_name if self.fingerprint else None,
            "file_sha256": self.fingerprint.sha256 if self.fingerprint else None,
            "warnings": self.warnings,
        }


def find_source(session: Session, *, sha256: str | None = None) -> ExternalSource | None:
    stmt = select(ExternalSource).where(ExternalSource.source_code == SOURCE_CODE)
    if sha256 is not None:
        stmt = select(ExternalSource).where(ExternalSource.file_sha256 == sha256)
    return session.scalar(stmt)


def register_source(
    session: Session, fingerprint: FileFingerprint, *, metadata: dict[str, Any] | None = None
) -> tuple[ExternalSource, bool]:
    """Get-or-create the source row keyed by sha256. Returns ``(source, created)``.

    The business key is ``file_name`` + ``file_sha256``; the host absolute path is
    only kept as non-authoritative metadata.
    """
    existing = session.scalar(
        select(ExternalSource).where(ExternalSource.file_sha256 == fingerprint.sha256)
    )
    if existing is not None:
        return existing, False

    conflicting = session.scalar(
        select(ExternalSource).where(ExternalSource.source_code == SOURCE_CODE)
    )
    if conflicting is not None:
        raise ValueError(
            f"source_code {SOURCE_CODE} is already registered with a different file "
            f"(sha256 {conflicting.file_sha256[:12]}...); refusing to silently replace it"
        )

    source = ExternalSource(
        source_code=SOURCE_CODE,
        file_name=fingerprint.file_name,
        file_size=fingerprint.file_size,
        file_sha256=fingerprint.sha256,
        parser_version=PARSER_VERSION,
        status=SourceStatus.REGISTERED.value,
        metadata_=metadata or {},
    )
    session.add(source)
    session.flush()
    return source, True


def _copy_rows(session: Session, rows: list[ParsedRow]) -> None:
    """Stream a chunk into the temp table via psycopg COPY."""
    raw = session.connection().connection
    driver_conn = getattr(raw, "driver_connection", raw)
    with driver_conn.cursor() as cursor, cursor.copy(_COPY_SQL) as copy:
        for row in rows:
            copy.write_row(
                (
                    row.source_symbol,
                    row.trade_date,
                    row.open,
                    row.high,
                    row.low,
                    row.close,
                    row.volume,
                    row.value,
                    row.reject_reason,
                )
            )


def _existing_row_count(session: Session, source_id: int) -> int:
    return int(
        session.execute(
            text(
                "SELECT count(*) FROM market.external_candles_daily WHERE source_id = :source_id"
            ),
            {"source_id": source_id},
        ).scalar_one()
    )


def ingest_file(
    session: Session,
    path: Path,
    *,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    limit: int | None = None,
    force: bool = False,
) -> IngestResult:
    """Stage the CSV. Re-running with the same sha256 yields NO_CHANGES."""
    if not path.exists():
        raise FileNotFoundError(f"external history file not found: {path}")

    fingerprint = file_fingerprint(path)
    result = IngestResult(fingerprint=fingerprint)
    source, created = register_source(
        session, fingerprint, metadata={"host_path_hint": str(path)}
    )
    result.source_id = source.id

    already_staged = _existing_row_count(session, source.id)
    if not created and already_staged > 0 and not force:
        result.status = "NO_CHANGES"
        result.rows_inserted = 0
        result.warnings.append(
            f"file sha256 already staged with {already_staged} rows; use --force to re-scan"
        )
        return result

    started = time.perf_counter()
    before = already_staged
    for rows, malformed in iter_chunks(path, chunk_rows=batch_rows, limit=limit):
        result.chunks += 1
        result.rows_read += len(rows) + len(malformed)
        result.rows_malformed += len(malformed)
        result.rows_valid += sum(1 for r in rows if r.is_valid)
        result.rows_rejected += sum(1 for r in rows if not r.is_valid)
        if not rows:
            continue
        session.execute(_CREATE_TEMP)
        _copy_rows(session, rows)
        session.execute(_INSERT_FROM_TEMP, {"source_id": source.id})
        # Bounded transaction per chunk: temp table is ON COMMIT DROP.
        session.commit()

    after = _existing_row_count(session, source.id)
    result.rows_inserted = after - before
    result.rows_skipped_conflict = max(
        0, (result.rows_valid + result.rows_rejected) - result.rows_inserted
    )
    result.elapsed_sec = time.perf_counter() - started

    if not result.balances():
        result.warnings.append("row accounting does not balance")

    source.status = SourceStatus.INGESTED.value
    source.imported_at = datetime.now(UTC)
    source.parser_version = PARSER_VERSION
    source.updated_at = datetime.now(UTC)
    session.add(source)
    session.commit()

    logger.info(
        "external_deep_history_ingest source_id=%s rows_read=%s inserted=%s rows_per_sec=%.1f",
        source.id,
        result.rows_read,
        result.rows_inserted,
        result.rows_per_sec,
    )
    return result
