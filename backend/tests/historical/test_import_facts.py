"""Idempotent SQLite import of parsed observations and source revisions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.modules.historical.application.import_facts import (
    FactRevisionStore,
    ImportAction,
    SkipReason,
    SourceRevision,
    fact_key_for,
    import_facts,
)
from app.modules.historical.application.isolation import FORBIDDEN_WRITE_TARGETS
from app.modules.historical.domain.evidence import (
    ParsedObservation,
    PublishedAtPrecision,
    RecordQuality,
)

_OBSERVED = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
_PUBLISHED = datetime(2024, 4, 2, 12, 0, tzinfo=UTC)


def _obs(**overrides: object) -> ParsedObservation:
    base: dict[str, object] = {
        "metric_id": "REVENUE",
        "source_id": "FNS-01",
        "content_hash": "hash-revenue-2023",
        "normalization_version": "fns_ras_v1",
        "quality_status": RecordQuality.ACCEPTED,
        "value": 100.0,
        "unit": "RUB",
        "currency": "RUB",
        "period": "FY:2023",
        "period_end": date(2023, 12, 31),
        "reporting_standard": "RAS",
        "issuer_identity": {"inn": "7700000001", "secid": "LKOH"},
        "evidence": "statement-row",
        "limitations": (),
        "extra": {},
    }
    base.update(overrides)
    return ParsedObservation(**base)  # type: ignore[arg-type]


def _revision(identifier: str = "rev-1", **overrides: object) -> SourceRevision:
    base: dict[str, object] = {
        "revision_identifier": identifier,
        "first_observed_at": _OBSERVED,
        "published_at": _PUBLISHED,
        "published_at_precision": PublishedAtPrecision.DATE_ONLY,
    }
    base.update(overrides)
    return SourceRevision(**base)  # type: ignore[arg-type]


def _raw(path: object, row_id: int) -> dict[str, object]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM fact_revisions WHERE row_id = ?",
            (row_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return dict(row)


def test_fact_key_uses_source_metric_period_and_issuer() -> None:
    left = fact_key_for(_obs())
    assert left != fact_key_for(_obs(source_id="FNS-02"))
    assert left != fact_key_for(_obs(metric_id="EBITDA"))
    assert left != fact_key_for(_obs(period_end=date(2024, 12, 31)))
    assert left != fact_key_for(_obs(issuer_identity={"inn": "7700000002"}))
    assert left == fact_key_for(
        _obs(issuer_identity={"secid": "LKOH", "inn": "7700000001"}),
    )


def test_new_revision_is_appended_beside_the_previous_row(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    original = _obs(content_hash="hash-1", value=100.0)
    corrected = _obs(content_hash="hash-2", value=110.0)
    outcomes = import_facts(
        path,
        (
            (original, _revision("2023-original", revision_sequence=1)),
            (corrected, _revision("2024-correction", revision_sequence=2)),
        ),
    )

    assert outcomes[0].action is ImportAction.INSERTED
    assert outcomes[0].counted_as_accepted is True
    assert outcomes[1].superseded_row_ids == (outcomes[0].row_id,)
    before = _raw(path, outcomes[0].row_id)
    assert before["superseded"] == 1
    assert before["content_hash"] == "hash-1"
    assert before["value"] == 100.0
    assert before["revision_identifier"] == "2023-original"
    assert before["first_observed_at"] == _OBSERVED.isoformat()

    store = FactRevisionStore(path)
    rows = store.revisions_for(original)
    assert [row.row_id for row in rows] == [outcomes[0].row_id, outcomes[1].row_id]
    assert rows[0].superseded is True
    assert rows[0].value == 100.0
    assert rows[1].superseded is False
    assert rows[1].revision_identifier == "2024-correction"
    assert rows[1].value == 110.0
    assert store.current_for(original) == rows[1]
    assert store.stored_row_count() == 2
    assert store.accepted_row_count() == 2


def test_same_content_hash_is_a_noop(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    observation = _obs()
    first = FactRevisionStore(path)
    inserted = first.import_observation(observation, _revision("rev-1"))
    before = _raw(path, inserted.row_id)

    second = FactRevisionStore(path)
    skipped = second.import_observation(
        observation,
        _revision(
            "rev-1",
            first_observed_at=datetime(2020, 1, 1, tzinfo=UTC),
        ),
    )
    after = _raw(path, inserted.row_id)

    assert skipped.action is ImportAction.SKIPPED
    assert skipped.skip_reason is SkipReason.CONTENT_HASH
    assert skipped.counted_as_accepted is False
    assert skipped.row_id == inserted.row_id
    assert skipped.superseded_row_ids == ()
    assert after == before
    assert second.stored_row_count() == 1
    assert second.accepted_row_count() == 1
    assert second.current_for(observation) is not None
    assert second.current_for(observation).first_observed_at == _OBSERVED  # type: ignore[union-attr]


def test_same_content_hash_with_another_revision_id_does_not_supersede(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    observation = _obs()
    store.import_observation(observation, _revision("rev-1"))
    skipped = store.import_observation(observation, _revision("rev-2"))

    assert skipped.action is ImportAction.SKIPPED
    assert skipped.skip_reason is SkipReason.CONTENT_HASH
    rows = store.revisions_for(observation)
    assert len(rows) == 1
    assert rows[0].revision_identifier == "rev-1"
    assert rows[0].superseded is False


def test_same_revision_identifier_does_not_duplicate_or_overwrite(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    store.import_observation(_obs(content_hash="hash-1", value=100.0), _revision("r1", revision_sequence=1))
    store.import_observation(_obs(content_hash="hash-2", value=110.0), _revision("r2", revision_sequence=2))
    skipped = store.import_observation(
        _obs(content_hash="hash-3", value=999.0),
        _revision("r1", revision_sequence=1),
    )

    assert skipped.action is ImportAction.SKIPPED
    assert skipped.skip_reason is SkipReason.REVISION_IDENTIFIER
    assert skipped.counted_as_accepted is False
    rows = store.revisions_for(_obs())
    assert len(rows) == 2
    assert rows[0].content_hash == "hash-1"
    assert rows[0].value == 100.0
    assert rows[0].superseded is True
    assert rows[1].content_hash == "hash-2"
    assert rows[1].value == 110.0
    assert rows[1].superseded is False


def test_period_end_is_not_stored_as_published_at(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    period = date(2023, 12, 31)
    observation = _obs(period_end=period)
    store = FactRevisionStore(path)
    outcome = store.import_observation(
        observation,
        _revision(
            published_at=None,
            published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        ),
    )

    row = store.current_for(observation)
    assert outcome.counted_as_accepted is True
    assert row is not None
    assert row.period_end == period
    assert row.published_at is None
    assert row.published_at_precision is PublishedAtPrecision.PERIOD_ONLY
    assert row.first_observed_at == _OBSERVED
    assert _raw(path, row.row_id)["published_at"] is None


def test_explicit_publication_stays_distinct_from_period_end(tmp_path: object) -> None:
    period = date(2024, 12, 20)
    published = datetime(2024, 12, 20, 13, 30, tzinfo=UTC)
    observation = _obs(period_end=period, content_hash="same-calendar-day")
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    outcome = store.import_observation(
        observation,
        _revision(
            "same-day",
            published_at=published,
            published_at_precision=PublishedAtPrecision.DATE_ONLY,
        ),
    )

    row = store.current_for(observation)
    assert outcome.counted_as_accepted is True
    assert row is not None
    assert row.period_end == period
    assert row.published_at == published
    assert row.first_observed_at == _OBSERVED


def test_clock_problems_quarantine_without_rewriting_timestamps(tmp_path: object) -> None:
    period = date(2024, 12, 20)
    published = datetime(2024, 12, 20, 13, 30, tzinfo=UTC)
    observed = datetime(2024, 1, 1, tzinfo=UTC)
    observation = _obs(period_end=period, content_hash="bad-clock")
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    outcome = store.import_observation(
        observation,
        SourceRevision(
            revision_identifier="bad-clock",
            first_observed_at=observed,
            published_at=published,
            published_at_precision=PublishedAtPrecision.TIMESTAMP,
        ),
    )

    row = store.current_for(observation)
    assert outcome.counted_as_accepted is False
    assert outcome.quality_status is RecordQuality.QUARANTINE
    assert row is not None
    assert row.first_observed_at == observed
    assert row.published_at == published
    assert row.period_end == period
    assert "period_end_must_not_equal_publication_timestamp" not in row.limitations
    assert "first_observed_at_precedes_published_at" in row.limitations
    assert store.accepted_row_count() == 0
    assert store.quarantined_row_count() == 1


def test_quarantine_rows_are_stored_but_not_accepted(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    accepted = _obs(metric_id="REVENUE", content_hash="accepted")
    quarantined = _obs(
        metric_id="EBITDA",
        content_hash="quarantine",
        value=5.0,
        quality_status=RecordQuality.QUARANTINE,
        evidence=None,
    )
    outcomes = import_facts(
        path,
        (
            (accepted, _revision("shared-document")),
            (quarantined, _revision("shared-document")),
        ),
    )

    assert [item.counted_as_accepted for item in outcomes] == [True, False]
    store = FactRevisionStore(path)
    assert store.accepted_row_count() == 1
    assert store.quarantined_row_count() == 1
    stored = store.revisions_for(quarantined)
    assert len(stored) == 1
    assert stored[0].quality_status is RecordQuality.QUARANTINE
    assert stored[0].superseded is False


def test_quarantine_revision_keeps_the_accepted_row(tmp_path: object) -> None:
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    store.import_observation(_obs(content_hash="hash-1", value=100.0), _revision("r1", revision_sequence=1))
    quarantined = _obs(
        content_hash="hash-2",
        value=5.0,
        quality_status=RecordQuality.QUARANTINE,
        evidence=None,
    )
    outcome = store.import_observation(quarantined, _revision("r2", revision_sequence=2))

    assert outcome.counted_as_accepted is False
    rows = store.revisions_for(_obs())
    assert len(rows) == 2
    assert rows[0].quality_status is RecordQuality.ACCEPTED
    assert rows[0].value == 100.0
    assert rows[0].superseded is True
    assert rows[1].quality_status is RecordQuality.QUARANTINE
    assert rows[1].superseded is False
    assert store.accepted_row_count() == 1
    assert store.quarantined_row_count() == 1


def test_accepted_fact_without_evidence_is_quarantined(tmp_path: object) -> None:
    observation = _obs(evidence=None, content_hash="missing-evidence")
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    outcome = store.import_observation(observation, _revision())

    assert observation.quality_status is RecordQuality.ACCEPTED
    assert outcome.counted_as_accepted is False
    assert outcome.quality_status is RecordQuality.QUARANTINE
    row = store.revisions_for(observation)[0]
    assert "accepted_fact_requires_evidence" in row.limitations
    assert store.accepted_row_count() == 0
    assert store.quarantined_row_count() == 1


def test_same_document_hash_can_fill_two_fact_keys(tmp_path: object) -> None:
    revenue = _obs(metric_id="REVENUE", content_hash="document-hash", value=100.0)
    ebitda = _obs(metric_id="EBITDA", content_hash="document-hash", value=40.0)
    outcomes = import_facts(
        tmp_path / "facts.sqlite",  # type: ignore[operator]
        (
            (revenue, _revision("bfo-1")),
            (ebitda, _revision("bfo-1")),
        ),
    )

    assert all(item.counted_as_accepted for item in outcomes)
    assert outcomes[0].fact_key != outcomes[1].fact_key
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    assert store.accepted_row_count() == 2
    assert store.current_for(revenue) is not None
    assert store.current_for(revenue).superseded is False  # type: ignore[union-attr]
    assert store.current_for(ebitda) is not None
    assert store.current_for(ebitda).superseded is False  # type: ignore[union-attr]


def test_another_issuer_is_not_superseded(tmp_path: object) -> None:
    store = FactRevisionStore(tmp_path / "facts.sqlite")  # type: ignore[operator]
    left = _obs(content_hash="left", issuer_identity={"inn": "7700000001"})
    right = _obs(
        content_hash="right",
        issuer_identity={"inn": "7700000002"},
        value=80.0,
    )
    store.import_observation(left, _revision("r1"))
    store.import_observation(right, _revision("r2"))

    assert store.current_for(left) is not None
    assert store.current_for(left).superseded is False  # type: ignore[union-attr]
    assert store.current_for(right) is not None
    assert store.current_for(right).superseded is False  # type: ignore[union-attr]
    assert store.stored_row_count() == 2


def test_naive_clock_is_rejected_and_writes_nothing(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.import_observation(
            _obs(),
            SourceRevision(
                revision_identifier="naive",
                first_observed_at=datetime(2026, 10, 13),
            ),
        )

    assert store.stored_row_count() == 0


def test_prior_revision_cannot_be_deleted_or_overwritten(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    inserted = store.import_observation(_obs(), _revision())
    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="not deleted"):
            connection.execute("DELETE FROM fact_revisions")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE fact_revisions SET first_observed_at = ? WHERE row_id = ?",
                ("2020-01-01T00:00:00+00:00", inserted.row_id),
            )
        connection.rollback()
    finally:
        connection.close()

    row = FactRevisionStore(path).revisions_for(_obs())[0]
    assert row.row_id == inserted.row_id
    assert row.first_observed_at == _OBSERVED
    assert row.value == 100.0
    assert row.superseded is False
    assert row.content_hash == "hash-revenue-2023"


def test_sqlite_schema_excludes_live_decision_tables(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    import_facts(path, ((_obs(), _revision()),))
    connection = sqlite3.connect(path)
    try:
        script = "\n".join(
            row[0]
            for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
            if row[0]
        )
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    finally:
        connection.close()

    assert "fact_revisions" in names
    for forbidden in FORBIDDEN_WRITE_TARGETS:
        assert forbidden not in script
        assert forbidden not in names


def test_new_parser_generation_keeps_the_original_row(tmp_path: object) -> None:
    path = tmp_path / "facts.sqlite"  # type: ignore[operator]
    store = FactRevisionStore(path)
    original = store.import_observation(_obs(normalization_version="fns_ras_v1"), _revision("rev-1"))
    generated = store.import_observation(
        _obs(normalization_version="fns_ras_v2", value=101.0),
        _revision("rev-1"),
    )

    assert generated.action is ImportAction.INSERTED
    assert original.row_id in generated.superseded_row_ids
    rows = store.revisions_for(_obs())
    assert len(rows) == 2
    assert rows[0].normalization_version == "fns_ras_v1"
    assert rows[0].value == 100.0
    assert rows[0].superseded is True
    assert rows[1].normalization_version == "fns_ras_v2"
    assert rows[1].value == 101.0
    assert rows[1].superseded is False
    assert store.stored_row_count() == 2
    assert store.accepted_row_count() == 2
    assert store.current_accepted_row_count() == 1
