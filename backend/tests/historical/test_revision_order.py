"""Source order, not the import clock, decides which fact revision is current."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.historical.application.import_facts import (
    FactRevisionStore,
    ImportAction,
    SourceRevision,
)
from app.modules.historical.domain.evidence import ParsedObservation, RecordQuality

_T1 = datetime(2024, 3, 1, 9, 0, tzinfo=UTC)
_T2 = datetime(2024, 8, 1, 9, 0, tzinfo=UTC)


def _obs(**overrides: object) -> ParsedObservation:
    base: dict[str, object] = {
        "metric_id": "REVENUE",
        "source_id": "FNS-01",
        "content_hash": "hash-revenue-2023",
        "normalization_version": "v1",
        "quality_status": RecordQuality.ACCEPTED,
        "value": 100.0,
        "unit": "RUB",
        "currency": "RUB",
        "period": "FY:2023",
        "period_end": date(2023, 12, 31),
        "reporting_standard": "RAS",
        "issuer_identity": {"inn": "7700000001"},
        "evidence": "statement-row",
        "limitations": (),
        "extra": {},
    }
    base.update(overrides)
    return ParsedObservation(**base)  # type: ignore[arg-type]


def _revision(
    identifier: str,
    sequence: int,
    observed: datetime,
) -> SourceRevision:
    return SourceRevision(
        revision_identifier=identifier,
        first_observed_at=observed,
        revision_sequence=sequence,
    )


def test_older_revision_imported_later_does_not_become_current(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    sequence_two = _obs(content_hash="hash-seq-2", value=200.0, normalization_version="v1")
    sequence_one = _obs(content_hash="hash-seq-1", value=100.0, normalization_version="v1")

    store.import_observation(sequence_two, _revision("rev-2", 2, _T1))
    older = store.import_observation(sequence_one, _revision("rev-1", 1, _T2))

    assert older.action is ImportAction.INSERTED
    assert older.superseded_row_ids == ()
    assert store.stored_row_count() == 2
    rows = store.revisions_for(sequence_two)
    assert len(rows) == 2
    current = store.current_for(sequence_two)
    assert current is not None
    assert current.revision_sequence == 2
    assert current.value == 200.0
    assert current.superseded is False
    assert current.first_observed_at == _T1
    stored_older = next(row for row in rows if row.revision_sequence == 1)
    assert stored_older.superseded is True
    assert stored_older.value == 100.0
    assert stored_older.first_observed_at == _T2
    kept_ids = {row.row_id for row in rows}
    kept_v1 = next(row for row in rows if row.revision_sequence == 2)

    generated = store.import_observation(
        _obs(content_hash="hash-seq-2-v2", value=200.0, normalization_version="v2"),
        _revision("rev-2", 2, _T1),
    )
    assert generated.action is ImportAction.INSERTED
    after_generation = store.revisions_for(sequence_two)
    assert store.stored_row_count() == 3
    assert kept_ids <= {row.row_id for row in after_generation}
    surviving_v1 = next(row for row in after_generation if row.row_id == kept_v1.row_id)
    assert surviving_v1.normalization_version == "v1"
    assert surviving_v1.value == 200.0
    stored_v2 = next(row for row in after_generation if row.normalization_version == "v2")
    assert stored_v2.revision_sequence == 2
    assert stored_v2.value == 200.0

    replay = store.import_observation(sequence_two, _revision("rev-2", 2, _T1))
    assert replay.action is ImportAction.SKIPPED
    assert store.stored_row_count() == 3
    assert {row.row_id for row in store.revisions_for(sequence_two)} >= kept_ids | {stored_v2.row_id}
