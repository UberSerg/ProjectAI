"""PIT labels stay on the fact row that was actually imported."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.modules.historical.application.import_facts import (
    FactRevisionStore,
    SourceRevision,
    fact_key,
    issuer_identity_key,
)
from app.modules.historical.application.pit_policy import apply_pit_policy
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)

_OBSERVED = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
_PUBLISHED = datetime(2024, 4, 2, 12, 0, tzinfo=UTC)
_PERIOD_END = date(2023, 12, 31)
_PROXY_LIMIT = "pit_proxy_excluded_from_verified_replay"
_RESEARCH_LIMIT = "research_only_excluded_from_strict_replay"

_LEGACY_SCHEMA = """
CREATE TABLE fact_revisions (
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
    UNIQUE (fact_key, content_hash, normalization_version),
    UNIQUE (fact_key, revision_identifier, normalization_version)
);
CREATE TRIGGER fact_revisions_no_delete
BEFORE DELETE ON fact_revisions
BEGIN
    SELECT RAISE(ABORT, 'fact revisions are not deleted');
END;
CREATE TRIGGER fact_revisions_content_immutable
BEFORE UPDATE ON fact_revisions
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
END;
"""


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
        "period_end": _PERIOD_END,
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


def _artifact(**overrides: object) -> HistoricalArtifact:
    base: dict[str, object] = {
        "source_id": "FNS-01",
        "source_url": "https://bo.nalog.ru/download/bfo/123",
        "external_document_id": "bfo-123",
        "document_type": "financial_statement",
        "content_hash": "hash-revenue-2023",
        "parser_version": "fns_ras_v1",
        "fetch_status": FetchStatus.OK,
        "first_observed_at": _OBSERVED,
        "period_end": _PERIOD_END,
        "published_at": None,
        "published_at_precision": PublishedAtPrecision.UNKNOWN,
        "historical_availability_evidence": "trade_date_is_not_publication",
        "historical_pit_quality": PitQuality.PIT_PROXY,
        "quality_status": RecordQuality.ACCEPTED,
    }
    base.update(overrides)
    return HistoricalArtifact(**base)  # type: ignore[arg-type]


def _path(tmp_path: object, name: str = "facts.sqlite") -> object:
    return tmp_path / name  # type: ignore[operator]


def _raw(path: object, row_id: int) -> dict[str, object]:
    connection = sqlite3.connect(path)  # type: ignore[arg-type]
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


def _master_sql(path: object, name: str) -> str:
    connection = sqlite3.connect(path)  # type: ignore[arg-type]
    try:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None and row[0] is not None
    return str(row[0])


def _column_names(path: object) -> set[str]:
    connection = sqlite3.connect(path)  # type: ignore[arg-type]
    try:
        rows = connection.execute("PRAGMA table_info(fact_revisions)").fetchall()
    finally:
        connection.close()
    return {str(row[1]) for row in rows}


def test_import_persists_each_pit_label_without_rewriting_published_at(tmp_path: object) -> None:
    path = _path(tmp_path)
    published = {
        "PIT_VERIFIED": datetime(2024, 4, 2, 12, 0, tzinfo=UTC),
        "PIT_PROXY": datetime(2024, 5, 15, 8, 0, tzinfo=UTC),
        "RESEARCH_ONLY": None,
    }
    evidence = {
        "PIT_VERIFIED": "archive_manifest",
        "PIT_PROXY": "trade_date_is_not_publication",
        "RESEARCH_ONLY": None,
    }
    metrics = {
        "PIT_VERIFIED": "REVENUE",
        "PIT_PROXY": "EBITDA",
        "RESEARCH_ONLY": "NET_INCOME",
    }
    store = FactRevisionStore(path)  # type: ignore[arg-type]
    observations = []
    for label in ("PIT_VERIFIED", "PIT_PROXY", "RESEARCH_ONLY"):
        observation = _obs(
            metric_id=metrics[label],
            content_hash=f"hash-{label}",
            value=100.0 if label != "RESEARCH_ONLY" else 80.0,
        )
        stamp = published[label]
        precision = PublishedAtPrecision.DATE_ONLY if stamp is not None else PublishedAtPrecision.UNKNOWN
        store.import_observation(
            observation,
            _revision(
                f"rev-{label}",
                published_at=stamp,
                published_at_precision=precision,
                historical_pit_quality=label,
                pit_evidence=evidence[label],
            ),
        )
        observations.append(observation)

    for observation, label in zip(observations, ("PIT_VERIFIED", "PIT_PROXY", "RESEARCH_ONLY"), strict=True):
        row = store.current_for(observation)
        stamp = published[label]
        assert row is not None
        assert row.historical_pit_quality == label
        assert row.pit_evidence == evidence[label]
        assert row.period_end == _PERIOD_END
        assert row.published_at == stamp
        if stamp is not None:
            assert row.published_at is not None
            assert row.published_at.date() != _PERIOD_END
        raw = _raw(path, row.row_id)
        assert raw["historical_pit_quality"] == label
        assert raw["published_at"] == (None if stamp is None else stamp.isoformat())
        if stamp is None:
            assert raw["published_at"] is None
            assert raw["period_end"] == _PERIOD_END.isoformat()


def test_null_published_at_stays_null(tmp_path: object) -> None:
    path = _path(tmp_path)
    observation = _obs()
    store = FactRevisionStore(path)  # type: ignore[arg-type]
    outcome = store.import_observation(
        observation,
        _revision(
            published_at=None,
            published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
            historical_pit_quality="PIT_PROXY",
            pit_evidence="no_publication_clock",
        ),
    )

    row = store.current_for(observation)
    assert row is not None
    assert outcome.row_id == row.row_id
    assert row.period_end == _PERIOD_END
    assert row.published_at is None
    assert row.published_at_precision is PublishedAtPrecision.PERIOD_ONLY
    assert row.historical_pit_quality == "PIT_PROXY"
    raw = _raw(path, row.row_id)
    assert raw["published_at"] is None
    assert raw["period_end"] == "2023-12-31"
    assert raw["historical_pit_quality"] == "PIT_PROXY"


def test_verified_mode_quarantines_proxy_without_calling_it_verified(tmp_path: object) -> None:
    published = datetime(2024, 5, 15, 8, 0, tzinfo=UTC)
    artifact = _artifact(
        published_at=published,
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
        historical_pit_quality=PitQuality.PIT_PROXY,
    )
    observation = _obs(content_hash="hash-proxy")
    gated = apply_pit_policy(observation, artifact, mode="verified")

    assert gated.quality_status is RecordQuality.QUARANTINE
    assert _PROXY_LIMIT in gated.limitations
    assert _RESEARCH_LIMIT not in gated.limitations
    assert observation.quality_status is RecordQuality.ACCEPTED
    assert artifact.historical_pit_quality is PitQuality.PIT_PROXY
    assert artifact.published_at == published
    again = apply_pit_policy(gated, artifact, mode="verified")
    assert again.limitations.count(_PROXY_LIMIT) == 1

    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    store.import_observation(
        gated,
        SourceRevision(
            revision_identifier="rev-proxy",
            first_observed_at=artifact.first_observed_at,
            published_at=artifact.published_at,
            published_at_precision=artifact.published_at_precision,
            historical_pit_quality=artifact.historical_pit_quality.value,
            pit_evidence=artifact.historical_availability_evidence,
        ),
    )
    row = store.current_for(gated)
    assert row is not None
    assert row.quality_status is RecordQuality.QUARANTINE
    assert row.historical_pit_quality == "PIT_PROXY"
    assert row.historical_pit_quality != "PIT_VERIFIED"
    assert row.published_at == published
    assert row.period_end == _PERIOD_END
    assert row.published_at.date() != row.period_end  # type: ignore[union-attr]


def test_verified_mode_quarantines_research_only_without_relabeling(tmp_path: object) -> None:
    artifact = _artifact(
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        historical_availability_evidence=None,
        published_at=None,
    )
    observation = _obs(content_hash="hash-research")
    gated = apply_pit_policy(observation, artifact, mode="verified")

    assert gated.quality_status is RecordQuality.QUARANTINE
    assert _RESEARCH_LIMIT in gated.limitations
    assert _PROXY_LIMIT not in gated.limitations
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.published_at is None

    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    store.import_observation(
        gated,
        _revision(
            "rev-research",
            published_at=None,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_pit_quality=artifact.historical_pit_quality.value,
            pit_evidence=None,
        ),
    )
    row = store.current_for(gated)
    assert row is not None
    assert row.historical_pit_quality == "RESEARCH_ONLY"
    assert row.published_at is None


def test_verified_mode_leaves_pit_verified_accepted() -> None:
    published = datetime(2024, 4, 2, 12, 0, tzinfo=UTC)
    artifact = _artifact(
        historical_pit_quality=PitQuality.PIT_VERIFIED,
        published_at=published,
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
        historical_availability_evidence="archive_manifest",
    )
    observation = _obs()
    gated = apply_pit_policy(observation, artifact, mode="verified")

    assert gated is observation
    assert gated.quality_status is RecordQuality.ACCEPTED
    assert artifact.historical_pit_quality is PitQuality.PIT_VERIFIED
    assert artifact.published_at == published
    assert artifact.period_end == _PERIOD_END


def test_research_mode_keeps_proxy_accepted_and_stored_as_proxy(tmp_path: object) -> None:
    published = datetime(2024, 5, 15, 8, 0, tzinfo=UTC)
    artifact = _artifact(
        published_at=published,
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
        historical_pit_quality=PitQuality.PIT_PROXY,
    )
    observation = _obs(content_hash="hash-research-proxy")
    gated = apply_pit_policy(observation, artifact, mode="research")

    assert gated is observation
    assert gated.quality_status is RecordQuality.ACCEPTED
    assert artifact.historical_pit_quality is PitQuality.PIT_PROXY
    assert artifact.published_at == published

    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    outcome = store.import_observation(
        gated,
        SourceRevision(
            revision_identifier="rev-research-proxy",
            first_observed_at=artifact.first_observed_at,
            published_at=artifact.published_at,
            published_at_precision=artifact.published_at_precision,
            historical_pit_quality=artifact.historical_pit_quality.value,
            pit_evidence=artifact.historical_availability_evidence,
        ),
    )
    row = store.current_for(gated)
    assert outcome.counted_as_accepted is True
    assert row is not None
    assert row.quality_status is RecordQuality.ACCEPTED
    assert row.historical_pit_quality == "PIT_PROXY"
    assert row.pit_evidence == "trade_date_is_not_publication"
    assert row.published_at == published
    assert row.period_end == _PERIOD_END


def test_research_mode_quarantines_research_only_without_relabeling(tmp_path: object) -> None:
    artifact = _artifact(
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        historical_availability_evidence=None,
        published_at=None,
    )
    gated = apply_pit_policy(_obs(content_hash="hash-research-only"), artifact, mode="research")

    assert gated.quality_status is RecordQuality.QUARANTINE
    assert _RESEARCH_LIMIT in gated.limitations
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.published_at is None

    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    store.import_observation(
        gated,
        _revision(
            "rev-research-only",
            published_at=None,
            historical_pit_quality="RESEARCH_ONLY",
            pit_evidence=None,
        ),
    )
    row = store.current_for(gated)
    assert row is not None
    assert row.historical_pit_quality == "RESEARCH_ONLY"
    assert row.published_at is None
    assert row.period_end == _PERIOD_END


def test_unknown_pit_mode_raises() -> None:
    artifact = _artifact(published_at=None)
    observation = _obs()
    with pytest.raises(ValueError, match="mode"):
        apply_pit_policy(observation, artifact, mode="champion")
    assert artifact.historical_pit_quality is PitQuality.PIT_PROXY
    assert artifact.published_at is None
    assert observation.quality_status is RecordQuality.ACCEPTED


def test_backfill_pit_fills_null_once_and_trigger_blocks_relabel(tmp_path: object) -> None:
    path = _path(tmp_path)
    store = FactRevisionStore(path)  # type: ignore[arg-type]
    table_sql = _master_sql(path, "fact_revisions")
    trigger_sql = _master_sql(path, "fact_revisions_content_immutable")
    assert "historical_pit_quality" in table_sql
    assert "pit_evidence" in table_sql
    assert "historical_pit_quality" in trigger_sql
    assert "pit_evidence" in trigger_sql

    observation = _obs()
    inserted = store.import_observation(observation, _revision(historical_pit_quality=None, pit_evidence=None))
    blank = store.revisions_for(observation)[0]
    assert blank.historical_pit_quality is None
    assert blank.pit_evidence is None
    assert _raw(path, inserted.row_id)["historical_pit_quality"] is None

    assert store.backfill_pit(inserted.row_id, "PIT_PROXY", "trade_date_is_not_publication") is True
    filled = store.revisions_for(observation)[0]
    assert filled.historical_pit_quality == "PIT_PROXY"
    assert filled.pit_evidence == "trade_date_is_not_publication"

    assert store.backfill_pit(inserted.row_id, "PIT_VERIFIED", "forged_archive") is False
    sticky = store.revisions_for(observation)[0]
    assert sticky.historical_pit_quality == "PIT_PROXY"
    assert sticky.pit_evidence == "trade_date_is_not_publication"

    connection = sqlite3.connect(path)  # type: ignore[arg-type]
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE fact_revisions SET historical_pit_quality = ? WHERE row_id = ?",
                ("PIT_VERIFIED", inserted.row_id),
            )
        connection.rollback()
    finally:
        connection.close()
    assert store.revisions_for(observation)[0].historical_pit_quality == "PIT_PROXY"


def test_rejected_pit_label_writes_nothing(tmp_path: object) -> None:
    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="PIT_VERIFIED"):
        store.import_observation(_obs(), _revision(historical_pit_quality="VERIFIED"))
    assert store.stored_row_count() == 0
    with pytest.raises(ValueError, match="PIT_VERIFIED"):
        store.backfill_pit(1, "PIT_VERIFIED_NOW", "forged")


def test_new_normalization_version_keeps_the_original_pit_label(tmp_path: object) -> None:
    store = FactRevisionStore(_path(tmp_path))  # type: ignore[arg-type]
    original = _obs(normalization_version="fns_ras_v1")
    store.import_observation(
        original,
        _revision("rev-1", historical_pit_quality="PIT_PROXY", pit_evidence="session_date"),
    )
    store.import_observation(
        _obs(normalization_version="fns_ras_v2", value=101.0),
        _revision("rev-1", historical_pit_quality="PIT_VERIFIED", pit_evidence="archive_manifest"),
    )

    rows = store.revisions_for(original)
    assert [row.normalization_version for row in rows] == ["fns_ras_v1", "fns_ras_v2"]
    assert rows[0].historical_pit_quality == "PIT_PROXY"
    assert rows[0].pit_evidence == "session_date"
    assert rows[0].value == 100.0
    assert rows[0].superseded is True
    assert rows[1].historical_pit_quality == "PIT_VERIFIED"
    assert rows[1].value == 101.0
    assert rows[1].superseded is False
    assert store.stored_row_count() == 2


def test_existing_database_gains_pit_columns_without_rebuilding(tmp_path: object) -> None:
    path = _path(tmp_path, "legacy.sqlite")
    identity = {"inn": "7700000001", "secid": "LKOH"}
    key = fact_key(
        source_id="FNS-01",
        metric_id="REVENUE",
        period_end=_PERIOD_END,
        issuer_identity=identity,
    )
    connection = sqlite3.connect(path)  # type: ignore[arg-type]
    try:
        connection.executescript(_LEGACY_SCHEMA)
        connection.execute(
            """
            INSERT INTO fact_revisions (
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
                NULL, ?, ?, 0
            )
            """,
            (
                key,
                "FNS-01",
                "REVENUE",
                _PERIOD_END.isoformat(),
                issuer_identity_key(identity),
                json.dumps({"inn": "7700000001", "secid": "LKOH"}),
                "hash-revenue-2023",
                "rev-legacy",
                "fns_ras_v1",
                RecordQuality.ACCEPTED.value,
                100.0,
                "RUB",
                "RUB",
                "FY:2023",
                "RAS",
                "statement-row",
                "[]",
                "{}",
                PublishedAtPrecision.UNKNOWN.value,
                _OBSERVED.isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    before_trigger = _master_sql(path, "fact_revisions_content_immutable")
    assert "historical_pit_quality" not in before_trigger
    assert "pit_evidence" not in before_trigger

    store = FactRevisionStore(path)  # type: ignore[arg-type]
    assert _column_names(path) >= {"historical_pit_quality", "pit_evidence"}
    assert _master_sql(path, "fact_revisions_content_immutable") == before_trigger
    assert store.stored_row_count() == 1

    observation = _obs()
    legacy = store.revisions_for(observation)
    assert len(legacy) == 1
    assert legacy[0].row_id == 1
    assert legacy[0].value == 100.0
    assert legacy[0].content_hash == "hash-revenue-2023"
    assert legacy[0].published_at is None
    assert legacy[0].period_end == _PERIOD_END
    assert legacy[0].historical_pit_quality is None
    assert legacy[0].superseded is False
    assert _raw(path, 1)["published_at"] is None

    assert store.backfill_pit(1, "PIT_PROXY", "legacy_proxy") is True
    assert store.backfill_pit(1, "PIT_VERIFIED", "forged_archive") is False
    filled = store.revisions_for(observation)[0]
    assert filled.historical_pit_quality == "PIT_PROXY"
    assert filled.pit_evidence == "legacy_proxy"
    assert filled.published_at is None

    store.import_observation(
        _obs(normalization_version="fns_ras_v2", value=101.0),
        _revision(
            "rev-legacy",
            published_at=None,
            historical_pit_quality="PIT_VERIFIED",
            pit_evidence="archive_manifest",
        ),
    )
    rows = store.revisions_for(observation)
    assert [row.normalization_version for row in rows] == ["fns_ras_v1", "fns_ras_v2"]
    assert rows[0].historical_pit_quality == "PIT_PROXY"
    assert rows[0].published_at is None
    assert rows[0].superseded is True
    assert rows[1].historical_pit_quality == "PIT_VERIFIED"
    assert rows[1].superseded is False
    assert _master_sql(path, "fact_revisions_content_immutable") == before_trigger

    FactRevisionStore(path)  # type: ignore[arg-type]
    assert store.stored_row_count() == 2
    assert _master_sql(path, "fact_revisions_content_immutable") == before_trigger
