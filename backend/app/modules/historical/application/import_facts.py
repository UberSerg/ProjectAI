"""Idempotent import of parsed observations and source revisions.

The caller supplies a SQLite file path. Nothing here opens PostgreSQL, the
network, or a paid LLM, and nothing writes the live decision tables.

A fact key is ``source_id + metric_id + period_end + issuer identity``.
The same content hash for that key is a no-op. A new revision identifier
inserts another row and marks the previous row superseded. Prior rows stay
in the file: their content is not deleted or overwritten, and
``first_observed_at`` is not moved earlier. ``period_end`` is never stored
as ``published_at``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.modules.historical.application.isolation import assert_research_only_target
from app.modules.historical.domain.evidence import (
    ParsedObservation,
    PublishedAtPrecision,
    RecordQuality,
)

_FACT_TABLE = "fact_revisions"

_SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS {_FACT_TABLE} (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_key TEXT NOT NULL,
        source_id TEXT NOT NULL,
        metric_id TEXT NOT NULL,
        period_end TEXT,
        issuer_identity_key TEXT NOT NULL,
        issuer_identity_json TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        revision_identifier TEXT NOT NULL,
        normalization_version TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        value REAL,
        unit TEXT,
        currency TEXT,
        period TEXT,
        reporting_standard TEXT,
        evidence TEXT,
        limitations_json TEXT NOT NULL,
        extra_json TEXT NOT NULL,
        published_at TEXT,
        published_at_precision TEXT NOT NULL,
        first_observed_at TEXT NOT NULL,
        superseded INTEGER NOT NULL CHECK (superseded IN (0, 1)),
        UNIQUE (fact_key, content_hash),
        UNIQUE (fact_key, revision_identifier)
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS {_FACT_TABLE}_by_fact
    ON {_FACT_TABLE} (fact_key, superseded, row_id)
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS {_FACT_TABLE}_no_delete
    BEFORE DELETE ON {_FACT_TABLE}
    BEGIN
        SELECT RAISE(ABORT, 'fact revisions are not deleted');
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS {_FACT_TABLE}_content_immutable
    BEFORE UPDATE ON {_FACT_TABLE}
    FOR EACH ROW
    WHEN NEW.row_id IS NOT OLD.row_id
        OR NEW.fact_key IS NOT OLD.fact_key
        OR NEW.source_id IS NOT OLD.source_id
        OR NEW.metric_id IS NOT OLD.metric_id
        OR NEW.period_end IS NOT OLD.period_end
        OR NEW.issuer_identity_key IS NOT OLD.issuer_identity_key
        OR NEW.issuer_identity_json IS NOT OLD.issuer_identity_json
        OR NEW.content_hash IS NOT OLD.content_hash
        OR NEW.revision_identifier IS NOT OLD.revision_identifier
        OR NEW.normalization_version IS NOT OLD.normalization_version
        OR NEW.quality_status IS NOT OLD.quality_status
        OR NEW.value IS NOT OLD.value
        OR NEW.unit IS NOT OLD.unit
        OR NEW.currency IS NOT OLD.currency
        OR NEW.period IS NOT OLD.period
        OR NEW.reporting_standard IS NOT OLD.reporting_standard
        OR NEW.evidence IS NOT OLD.evidence
        OR NEW.limitations_json IS NOT OLD.limitations_json
        OR NEW.extra_json IS NOT OLD.extra_json
        OR NEW.published_at IS NOT OLD.published_at
        OR NEW.published_at_precision IS NOT OLD.published_at_precision
        OR NEW.first_observed_at IS NOT OLD.first_observed_at
    BEGIN
        SELECT RAISE(ABORT, 'fact revision content is immutable');
    END
    """,
)


class ImportAction(StrEnum):
    INSERTED = "inserted"
    SKIPPED = "skipped"


class SkipReason(StrEnum):
    CONTENT_HASH = "content_hash"
    REVISION_IDENTIFIER = "revision_identifier"


@dataclass(frozen=True, slots=True)
class SourceRevision:
    """Publication identity of one source snapshot.

    ``published_at`` is supplied by the caller. The importer does not copy
    ``period_end`` into it. ``first_observed_at`` is the clock of this
    observation and must already be timezone-aware.
    """

    revision_identifier: str
    first_observed_at: datetime
    published_at: datetime | None = None
    published_at_precision: PublishedAtPrecision = PublishedAtPrecision.UNKNOWN


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    action: ImportAction
    skip_reason: SkipReason | None
    fact_key: str
    content_hash: str
    revision_identifier: str
    quality_status: RecordQuality
    counted_as_accepted: bool
    superseded_row_ids: tuple[int, ...]
    row_id: int


@dataclass(frozen=True, slots=True)
class StoredRevision:
    row_id: int
    fact_key: str
    source_id: str
    metric_id: str
    period_end: date | None
    issuer_identity_key: str
    issuer_identity: dict[str, str]
    content_hash: str
    revision_identifier: str
    normalization_version: str
    quality_status: RecordQuality
    value: float | None
    unit: str | None
    currency: str | None
    period: str | None
    reporting_standard: str | None
    evidence: str | None
    limitations: tuple[str, ...]
    published_at: datetime | None
    published_at_precision: PublishedAtPrecision
    first_observed_at: datetime
    superseded: bool


def issuer_identity_key(identity: Mapping[str, str]) -> str:
    """Stable identity key. Dict order does not change the result."""
    pairs = sorted((str(key), str(value)) for key, value in identity.items())
    return json.dumps(pairs, ensure_ascii=True, separators=(",", ":"))


def fact_key(
    *,
    source_id: str,
    metric_id: str,
    period_end: date | None,
    issuer_identity: Mapping[str, str],
) -> str:
    period = "" if period_end is None else period_end.isoformat()
    return json.dumps(
        [source_id, metric_id, period, issuer_identity_key(issuer_identity)],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def fact_key_for(observation: ParsedObservation) -> str:
    return fact_key(
        source_id=observation.source_id,
        metric_id=observation.metric_id,
        period_end=observation.period_end,
        issuer_identity=observation.issuer_identity,
    )


class FactRevisionStore:
    """Append-only fact revisions in one caller-owned SQLite file."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        assert_research_only_target(_FACT_TABLE)
        with self._connect() as connection:
            for statement in _SCHEMA:
                connection.execute(statement)

    def import_observation(
        self,
        observation: ParsedObservation,
        revision: SourceRevision,
    ) -> ImportOutcome:
        return self.import_all(((observation, revision),))[0]

    def import_all(
        self,
        items: Sequence[tuple[ParsedObservation, SourceRevision]],
    ) -> tuple[ImportOutcome, ...]:
        """Import observations in order. One transaction covers the batch."""
        batch = tuple(items)
        if not batch:
            return ()
        prepared = tuple(
            (_validate(observation, revision), observation, revision) for observation, revision in batch
        )
        with self._connect(write=True) as connection:
            return tuple(
                self._import_one(connection, observation, revision, identifier)
                for identifier, observation, revision in prepared
            )

    def revisions_for(self, observation: ParsedObservation) -> tuple[StoredRevision, ...]:
        """Every stored revision of this fact, oldest row first."""
        key = fact_key_for(observation)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM {_FACT_TABLE}
                WHERE fact_key = ?
                ORDER BY row_id
                """,
                (key,),
            ).fetchall()
        return tuple(_stored_from_row(row) for row in rows)

    def current_for(self, observation: ParsedObservation) -> StoredRevision | None:
        key = fact_key_for(observation)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM {_FACT_TABLE}
                WHERE fact_key = ? AND superseded = 0
                ORDER BY row_id
                """,
                (key,),
            ).fetchall()
        if not rows:
            return None
        return _stored_from_row(rows[-1])

    def stored_row_count(self) -> int:
        return self._count("1 = 1")

    def accepted_row_count(self) -> int:
        """Stored ACCEPTED rows, including revisions later marked superseded."""
        return self._count("quality_status = ?", (RecordQuality.ACCEPTED.value,))

    def quarantined_row_count(self) -> int:
        return self._count("quality_status = ?", (RecordQuality.QUARANTINE.value,))

    def _count(self, where: str, params: tuple[object, ...] = ()) -> int:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM {_FACT_TABLE} WHERE {where}",
                params,
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def _import_one(
        self,
        connection: sqlite3.Connection,
        observation: ParsedObservation,
        revision: SourceRevision,
        identifier: str,
    ) -> ImportOutcome:
        key = fact_key_for(observation)
        existing_hash = connection.execute(
            f"""
            SELECT row_id, quality_status, revision_identifier
            FROM {_FACT_TABLE}
            WHERE fact_key = ? AND content_hash = ?
            """,
            (key, observation.content_hash),
        ).fetchone()
        if existing_hash is not None:
            return _skipped(
                reason=SkipReason.CONTENT_HASH,
                fact_key=key,
                content_hash=observation.content_hash,
                revision_identifier=identifier,
                quality_status=RecordQuality(existing_hash["quality_status"]),
                row_id=int(existing_hash["row_id"]),
            )

        existing_revision = connection.execute(
            f"""
            SELECT row_id, quality_status
            FROM {_FACT_TABLE}
            WHERE fact_key = ? AND revision_identifier = ?
            """,
            (key, identifier),
        ).fetchone()
        if existing_revision is not None:
            return _skipped(
                reason=SkipReason.REVISION_IDENTIFIER,
                fact_key=key,
                content_hash=observation.content_hash,
                revision_identifier=identifier,
                quality_status=RecordQuality(existing_revision["quality_status"]),
                row_id=int(existing_revision["row_id"]),
            )

        quality, limitations = _stored_quality(observation, revision)
        published_at = revision.published_at.isoformat() if revision.published_at is not None else None
        cursor = connection.execute(
            f"""
            INSERT INTO {_FACT_TABLE} (
                fact_key, source_id, metric_id, period_end, issuer_identity_key,
                issuer_identity_json, content_hash, revision_identifier,
                normalization_version, quality_status, value, unit, currency,
                period, reporting_standard, evidence, limitations_json, extra_json,
                published_at, published_at_precision, first_observed_at, superseded
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, 0
            )
            """,
            (
                key,
                observation.source_id,
                observation.metric_id,
                None if observation.period_end is None else observation.period_end.isoformat(),
                issuer_identity_key(observation.issuer_identity),
                _dump_mapping(observation.issuer_identity),
                observation.content_hash,
                identifier,
                observation.normalization_version,
                quality.value,
                observation.value,
                observation.unit,
                observation.currency,
                observation.period,
                observation.reporting_standard,
                observation.evidence,
                _dump(list(limitations)),
                _dump(observation.extra),
                published_at,
                revision.published_at_precision.value,
                revision.first_observed_at.isoformat(),
            ),
        )
        new_id = cursor.lastrowid
        if new_id is None:
            raise RuntimeError("fact revision insert did not return a row id")
        previous = connection.execute(
            f"""
            SELECT row_id FROM {_FACT_TABLE}
            WHERE fact_key = ? AND superseded = 0 AND row_id != ?
            ORDER BY row_id
            """,
            (key, new_id),
        ).fetchall()
        superseded_row_ids = tuple(int(row["row_id"]) for row in previous)
        if superseded_row_ids:
            connection.execute(
                f"""
                UPDATE {_FACT_TABLE}
                SET superseded = 1
                WHERE fact_key = ? AND superseded = 0 AND row_id != ?
                """,
                (key, new_id),
            )
        return ImportOutcome(
            action=ImportAction.INSERTED,
            skip_reason=None,
            fact_key=key,
            content_hash=observation.content_hash,
            revision_identifier=identifier,
            quality_status=quality,
            counted_as_accepted=quality is RecordQuality.ACCEPTED,
            superseded_row_ids=superseded_row_ids,
            row_id=int(new_id),
        )

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()


def import_facts(
    database_path: str | Path,
    items: Sequence[tuple[ParsedObservation, SourceRevision]],
) -> tuple[ImportOutcome, ...]:
    """Import each observation with its source revision into ``database_path``."""
    return FactRevisionStore(database_path).import_all(items)


def _validate(observation: ParsedObservation, revision: SourceRevision) -> str:
    if not observation.source_id or not observation.metric_id or not observation.content_hash:
        raise ValueError("source_id, metric_id, and content_hash are required")
    identifier = revision.revision_identifier.strip()
    if not identifier:
        raise ValueError("revision_identifier is required")
    _require_aware(revision.first_observed_at, "first_observed_at")
    if revision.published_at is not None:
        _require_aware(revision.published_at, "published_at")
    return identifier


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


def _stored_quality(
    observation: ParsedObservation,
    revision: SourceRevision,
) -> tuple[RecordQuality, tuple[str, ...]]:
    limitations = list(observation.limitations)
    problems = [*observation.quality_errors(), *_chronology_problems(observation, revision)]
    for problem in problems:
        if problem not in limitations:
            limitations.append(problem)
    if observation.quality_status is RecordQuality.QUARANTINE or problems:
        return RecordQuality.QUARANTINE, tuple(limitations)
    return observation.quality_status, tuple(limitations)


def _chronology_problems(
    observation: ParsedObservation,
    revision: SourceRevision,
) -> tuple[str, ...]:
    problems: list[str] = []
    published_at = revision.published_at
    if published_at is not None and revision.first_observed_at < published_at:
        problems.append("first_observed_at_precedes_published_at")
    return tuple(problems)


def _skipped(
    *,
    reason: SkipReason,
    fact_key: str,
    content_hash: str,
    revision_identifier: str,
    quality_status: RecordQuality,
    row_id: int,
) -> ImportOutcome:
    return ImportOutcome(
        action=ImportAction.SKIPPED,
        skip_reason=reason,
        fact_key=fact_key,
        content_hash=content_hash,
        revision_identifier=revision_identifier,
        quality_status=quality_status,
        counted_as_accepted=False,
        superseded_row_ids=(),
        row_id=row_id,
    )


def _stored_from_row(row: sqlite3.Row) -> StoredRevision:
    observed = _parse_datetime(row["first_observed_at"])
    if observed is None:
        raise RuntimeError("fact revision is missing first_observed_at")
    identity = json.loads(row["issuer_identity_json"])
    limitations = json.loads(row["limitations_json"])
    return StoredRevision(
        row_id=int(row["row_id"]),
        fact_key=str(row["fact_key"]),
        source_id=str(row["source_id"]),
        metric_id=str(row["metric_id"]),
        period_end=_parse_date(row["period_end"]),
        issuer_identity_key=str(row["issuer_identity_key"]),
        issuer_identity={str(key): str(value) for key, value in identity.items()},
        content_hash=str(row["content_hash"]),
        revision_identifier=str(row["revision_identifier"]),
        normalization_version=str(row["normalization_version"]),
        quality_status=RecordQuality(row["quality_status"]),
        value=None if row["value"] is None else float(row["value"]),
        unit=row["unit"],
        currency=row["currency"],
        period=row["period"],
        reporting_standard=row["reporting_standard"],
        evidence=row["evidence"],
        limitations=tuple(str(item) for item in limitations),
        published_at=_parse_datetime(row["published_at"]),
        published_at_precision=PublishedAtPrecision(row["published_at_precision"]),
        first_observed_at=observed,
        superseded=bool(row["superseded"]),
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _dump_mapping(identity: Mapping[str, str]) -> str:
    payload = {str(key): str(value) for key, value in identity.items()}
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _dump(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


__all__ = [
    "FactRevisionStore",
    "ImportAction",
    "ImportOutcome",
    "SkipReason",
    "SourceRevision",
    "StoredRevision",
    "fact_key",
    "fact_key_for",
    "import_facts",
    "issuer_identity_key",
]
