"""Offline ingestion: raw bytes, facts, checkpoint. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.historical.application.import_facts import FactRevisionStore, ImportAction
from app.modules.historical.application.pipeline import RESEARCH_ONLY_EXCLUDED, commit_fetched
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.infrastructure.checkpoint_store import CheckpointStore
from app.modules.historical.infrastructure.raw_store import RawArtifactStore, RawIntegrityError, content_hash

_OBSERVED = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
_PUBLISHED = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)


def _artifact(body: bytes, **overrides: object) -> HistoricalArtifact:
    base: dict[str, object] = {
        "source_id": "CBR-03",
        "source_url": "https://example.test/ruonia",
        "external_document_id": "RUONIA:2024-01-15",
        "document_type": "cbr_ruonia_xml",
        "content_hash": content_hash(body),
        "parser_version": "cbr_rates_v1",
        "fetch_status": FetchStatus.OK,
        "first_observed_at": _OBSERVED,
        "published_at": _PUBLISHED,
        "published_at_precision": PublishedAtPrecision.DATE_ONLY,
        "historical_availability_evidence": "cbr_ruonia_DateUpdate",
        "historical_pit_quality": PitQuality.PIT_PROXY,
        "period_end": date(2024, 1, 15),
        "quality_status": RecordQuality.ACCEPTED,
    }
    base.update(overrides)
    return HistoricalArtifact(**base)  # type: ignore[arg-type]


def _observation(body: bytes, **overrides: object) -> ParsedObservation:
    base: dict[str, object] = {
        "metric_id": "macro.ruonia",
        "source_id": "CBR-03",
        "content_hash": content_hash(body),
        "normalization_version": "cbr_rates_v1",
        "quality_status": RecordQuality.ACCEPTED,
        "value": 16.0,
        "unit": "percent",
        "period": "2024-01-15",
        "period_end": date(2024, 1, 15),
        "evidence": "ruonia row",
        "limitations": (),
        "issuer_identity": {},
        "extra": {},
    }
    base.update(overrides)
    return ParsedObservation(**base)  # type: ignore[arg-type]


def _stores(tmp_path: object) -> tuple[RawArtifactStore, FactRevisionStore, CheckpointStore]:
    root = tmp_path / "store"  # type: ignore[operator]
    root.mkdir()
    return (
        RawArtifactStore(root / "raw"),
        FactRevisionStore(root / "facts.sqlite"),
        CheckpointStore(root / "checkpoints.sqlite"),
    )


def test_commit_stores_raw_before_parse_and_advances_only_after_import(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>16</ruonia>"
    seen: list[str] = []

    def parse(artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        assert raw_store.has(content_hash(raw))
        assert checkpoints.load(artifact.source_id) is None
        seen.append("parsed")
        return (_observation(body),)

    result = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(_artifact(body),),
        parse=parse,
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )

    assert seen == ["parsed"]
    assert result.checkpoint_advanced is True
    assert result.inserted == 1
    assert result.accepted_inserted == 1
    assert raw_store.get(result.content_hash) == body
    assert checkpoints.load("CBR-03") == "2024-01-15"
    assert facts.current_accepted_row_count() == 1
    stored = facts.current_for(_observation(body))
    assert stored is not None
    assert stored.first_observed_at == _OBSERVED
    assert stored.published_at == _PUBLISHED
    assert stored.period_end == date(2024, 1, 15)


def test_parse_failure_keeps_raw_and_does_not_advance(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>broken</ruonia>"

    def parse(_artifact: HistoricalArtifact, _raw: bytes) -> tuple[ParsedObservation, ...]:
        raise RuntimeError("parser crashed")

    with pytest.raises(RuntimeError, match="parser crashed"):
        commit_fetched(
            raw_store=raw_store,
            facts=facts,
            checkpoints=checkpoints,
            raw=body,
            artifacts=(_artifact(body),),
            parse=parse,
            stage="stage_1000",
            run_new_items=0,
            next_cursor="2024-01-15",
        )

    assert raw_store.get(content_hash(body)) == body
    assert checkpoints.load("CBR-03") is None
    assert facts.stored_row_count() == 0


def test_checkpoint_crash_replays_without_a_duplicate_fact(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>16</ruonia>"
    artifact = _artifact(body)

    def parse(_artifact: HistoricalArtifact, _raw: bytes) -> tuple[ParsedObservation, ...]:
        return (_observation(body),)

    original = checkpoints.advance_after_commit

    def crash(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("checkpoint crashed")

    checkpoints.advance_after_commit = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="checkpoint crashed"):
        commit_fetched(
            raw_store=raw_store,
            facts=facts,
            checkpoints=checkpoints,
            raw=body,
            artifacts=(artifact,),
            parse=parse,
            stage="stage_1000",
            run_new_items=0,
            next_cursor="2024-01-15",
        )
    assert facts.current_accepted_row_count() == 1
    assert checkpoints.load("CBR-03") is None

    checkpoints.advance_after_commit = original  # type: ignore[method-assign]
    replay = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=parse,
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )

    assert replay.inserted == 0
    assert replay.skipped == 1
    assert replay.accepted_inserted == 0
    assert replay.outcomes[0].action is ImportAction.SKIPPED
    assert facts.current_accepted_row_count() == 1
    assert facts.stored_row_count() == 1
    assert checkpoints.load("CBR-03") == "2024-01-15"


def test_http_success_without_rows_does_not_advance(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<empty/>"

    result = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(_artifact(body),),
        parse=lambda _artifact, _raw: (),
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )

    assert result.stop_reason == "no_observations"
    assert result.checkpoint_advanced is False
    assert raw_store.has(content_hash(body))
    assert checkpoints.load("CBR-03") is None
    assert facts.stored_row_count() == 0


def test_failed_fetch_is_stored_and_not_imported(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"not xml"
    artifact = _artifact(body, fetch_status=FetchStatus.FAILED)

    result = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=lambda _artifact, _raw: (_observation(body),),
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )

    assert result.stop_reason == "fetch_not_ok"
    assert checkpoints.load("CBR-03") is None
    assert facts.stored_row_count() == 0
    assert raw_store.get(content_hash(body)) == body


def test_research_only_does_not_become_an_accepted_fact(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<keyrate>16</keyrate>"
    artifact = _artifact(
        body,
        source_id="CBR-01",
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        published_at=None,
        historical_availability_evidence=None,
    )

    result = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=lambda _artifact, _raw: (_observation(body, source_id="CBR-01", metric_id="macro.key_rate"),),
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )

    assert result.accepted_inserted == 0
    assert result.quarantined_inserted == 1
    assert facts.current_accepted_row_count() == 0
    assert facts.current_quarantined_row_count() == 1
    stored = facts.revisions_for(_observation(body, source_id="CBR-01", metric_id="macro.key_rate"))
    assert RESEARCH_ONLY_EXCLUDED in stored[0].limitations


def test_new_parser_generation_replays_the_stored_body(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>16</ruonia>"
    artifact = _artifact(body)

    def parse(_artifact: HistoricalArtifact, _raw: bytes) -> tuple[ParsedObservation, ...]:
        return (_observation(body),)

    commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=body,
        artifacts=(artifact,),
        parse=parse,
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
    )
    stored_body = raw_store.get(content_hash(body))
    second = commit_fetched(
        raw_store=raw_store,
        facts=facts,
        checkpoints=checkpoints,
        raw=stored_body,
        artifacts=(artifact,),
        parse=parse,
        stage="stage_1000",
        run_new_items=0,
        next_cursor="2024-01-15",
        normalization_version="cbr_rates_v2",
    )

    assert second.inserted == 1
    rows = facts.revisions_for(_observation(body))
    assert [row.normalization_version for row in rows] == ["cbr_rates_v1", "cbr_rates_v2"]
    assert rows[0].superseded is True
    assert rows[0].value == 16.0
    assert rows[1].superseded is False
    assert facts.stored_row_count() == 2
    assert facts.current_accepted_row_count() == 1


def test_hash_mismatch_writes_nothing(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>16</ruonia>"
    artifact = _artifact(b"other")

    with pytest.raises(RawIntegrityError):
        commit_fetched(
            raw_store=raw_store,
            facts=facts,
            checkpoints=checkpoints,
            raw=body,
            artifacts=(artifact,),
            parse=lambda _artifact, _raw: (_observation(body),),
            stage="stage_1000",
            run_new_items=0,
            next_cursor="2024-01-15",
        )

    assert raw_store.stat().count == 0
    assert facts.stored_row_count() == 0
    assert checkpoints.load("CBR-03") is None


def test_naive_clock_is_refused(tmp_path: object) -> None:
    raw_store, facts, checkpoints = _stores(tmp_path)
    body = b"<ruonia>16</ruonia>"
    artifact = _artifact(body, first_observed_at=datetime(2026, 10, 13, 6, 0))

    with pytest.raises(ValueError, match="timezone-aware"):
        commit_fetched(
            raw_store=raw_store,
            facts=facts,
            checkpoints=checkpoints,
            raw=body,
            artifacts=(artifact,),
            parse=lambda _artifact, _raw: (_observation(body),),
            stage="stage_1000",
            run_new_items=0,
            next_cursor="2024-01-15",
        )

    assert raw_store.stat().count == 0
    assert checkpoints.load("CBR-03") is None
