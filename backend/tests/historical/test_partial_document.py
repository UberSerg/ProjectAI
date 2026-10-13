"""A stage budget must not drop the unread tail of one raw body."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.historical.application.import_facts import FactRevisionStore
from app.modules.historical.application.pipeline import commit_fetched
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.infrastructure.checkpoint_store import CheckpointStore
from app.modules.historical.infrastructure.raw_store import RawArtifactStore, content_hash

_OBSERVED = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
_PUBLISHED = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
_NEXT_CURSOR = "2024-02-01"
_SOURCE = "CBR-03"


def _artifact(body: bytes) -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=_SOURCE,
        source_url="https://example.test/ruonia",
        external_document_id="RUONIA:2024-01",
        document_type="cbr_ruonia_xml",
        content_hash=content_hash(body),
        parser_version="cbr_rates_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=_OBSERVED,
        published_at=_PUBLISHED,
        published_at_precision=PublishedAtPrecision.DATE_ONLY,
        historical_availability_evidence="cbr_ruonia_DateUpdate",
        historical_pit_quality=PitQuality.PIT_PROXY,
        period_end=date(2024, 1, 8),
        quality_status=RecordQuality.ACCEPTED,
    )


def _observations(body: bytes) -> tuple[ParsedObservation, ...]:
    digest = content_hash(body)
    rows: list[ParsedObservation] = []
    for index in range(8):
        period = date(2024, 1, index + 1)
        rows.append(
            ParsedObservation(
                metric_id="macro.ruonia",
                source_id=_SOURCE,
                content_hash=digest,
                normalization_version="cbr_rates_v1",
                quality_status=RecordQuality.ACCEPTED,
                value=float(index + 1),
                unit="percent",
                period=period.isoformat(),
                period_end=period,
                evidence="ruonia row",
            )
        )
    return tuple(rows)


def _native_document_progress() -> bool:
    if not hasattr(CheckpointStore, "document_progress"):
        return False
    parameters = inspect.signature(CheckpointStore.advance_after_commit).parameters
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        return True
    needed = {"partition", "document_offset", "document_complete"}
    return needed <= set(parameters)


@dataclass(frozen=True, slots=True)
class _DocumentProgress:
    committed: int
    complete: bool


class _OffsetCheckpointStore(CheckpointStore):
    """Stand-in used only when ``CheckpointStore`` has no document offset yet."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_progress (
                source_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                partition TEXT NOT NULL,
                committed INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                PRIMARY KEY (source_id, content_hash, partition)
            );
            """
        )
        self._connection.commit()

    def document_progress(
        self,
        source_id: str,
        content_hash: str,
        *,
        partition: str = "",
    ) -> _DocumentProgress | None:
        row = self._connection.execute(
            """
            SELECT committed, complete
            FROM document_progress
            WHERE source_id = ? AND content_hash = ? AND partition = ?
            """,
            (source_id, content_hash, partition),
        ).fetchone()
        if row is None:
            return None
        return _DocumentProgress(int(row["committed"]), bool(row["complete"]))

    def advance_after_commit(
        self,
        source_id: str,
        content_hash: str,
        next_cursor: str,
        accepted: bool,
        stage: str,
        *,
        run_new_items: int,
        partition: str = "",
        document_offset: int = 0,
        document_complete: bool = False,
    ) -> object:
        stored = super().advance_after_commit(
            source_id,
            content_hash,
            next_cursor,
            accepted,
            stage,
            run_new_items=run_new_items,
        )
        self._connection.execute(
            "UPDATE checkpoints SET cursor = ? WHERE source_id = ?",
            (next_cursor, source_id),
        )
        self._connection.execute(
            """
            INSERT INTO document_progress (
                source_id, content_hash, partition, committed, complete
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_id, content_hash, partition) DO UPDATE SET
                committed = excluded.committed,
                complete = excluded.complete
            """,
            (
                source_id,
                content_hash,
                partition,
                document_offset,
                1 if document_complete else 0,
            ),
        )
        self._connection.commit()
        return stored


def _open_checkpoints(path: Path) -> CheckpointStore:
    if _native_document_progress():
        return CheckpointStore(path)
    return _OffsetCheckpointStore(path)


def test_partial_document_resumes_without_duplicate_facts(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    facts_path = tmp_path / "facts.sqlite"
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    body = b"<ruonia>partial-document</ruonia>"
    observations = _observations(body)
    artifact = _artifact(body)
    digest = content_hash(body)
    parsed_calls: list[int] = []

    def parse(_artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        assert raw == body
        parsed_calls.append(len(observations))
        return observations

    checkpoints = _open_checkpoints(checkpoint_path)
    first = commit_fetched(
        raw_store=RawArtifactStore(raw_root),
        facts=FactRevisionStore(facts_path),
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=parse,
        stage="pilot",
        run_new_items=97,
        next_cursor=_NEXT_CURSOR,
    )
    assert checkpoints.load(_SOURCE) == f"{digest[:12]}:3"
    checkpoints.close()

    assert first.inserted == 3
    assert first.skipped == 0
    assert first.document_complete is False
    assert first.document_offset == 3
    assert first.checkpoint_advanced is True
    assert first.cursor == f"{digest[:12]}:3"
    assert first.cursor not in {item.period_end.isoformat() for item in observations if item.period_end}
    facts = FactRevisionStore(facts_path)
    assert facts.stored_row_count() == 3
    assert facts.current_accepted_row_count() == 3
    for index in range(3):
        stored = facts.current_for(observations[index])
        assert stored is not None
        assert stored.value == float(index + 1)
    for index in range(3, 8):
        assert facts.current_for(observations[index]) is None

    checkpoints = _open_checkpoints(checkpoint_path)
    assert checkpoints.load(_SOURCE) == f"{digest[:12]}:3"
    second = commit_fetched(
        raw_store=RawArtifactStore(raw_root),
        facts=FactRevisionStore(facts_path),
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=parse,
        stage="pilot",
        run_new_items=0,
        next_cursor=_NEXT_CURSOR,
    )
    assert checkpoints.load(_SOURCE) == _NEXT_CURSOR
    checkpoints.close()

    assert second.inserted == 5
    assert second.skipped == 0
    assert second.document_complete is True
    assert second.document_offset == 8
    assert second.cursor == _NEXT_CURSOR
    facts = FactRevisionStore(facts_path)
    assert facts.stored_row_count() == 8
    assert facts.current_accepted_row_count() == 8
    assert [len(facts.revisions_for(observation)) for observation in observations] == [1, 1, 1, 1, 1, 1, 1, 1]

    checkpoints = _open_checkpoints(checkpoint_path)
    third = commit_fetched(
        raw_store=RawArtifactStore(raw_root),
        facts=FactRevisionStore(facts_path),
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=parse,
        stage="pilot",
        run_new_items=0,
        next_cursor=_NEXT_CURSOR,
    )
    assert third.inserted == 0
    assert third.skipped == 0
    assert checkpoints.load(_SOURCE) == _NEXT_CURSOR
    checkpoints.close()

    facts = FactRevisionStore(facts_path)
    assert facts.stored_row_count() == 8
    assert facts.current_accepted_row_count() == 8
    assert parsed_calls == [8, 8, 8]
