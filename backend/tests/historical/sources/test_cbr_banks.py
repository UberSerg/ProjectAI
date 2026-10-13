"""CBR bank forms 101/102/123/135: SOAP wrap, fixture label, no live network."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    PitQuality,
    RecordQuality,
)
from app.modules.historical.sources.cbr_banks.fixtures import SBER_SOAP_FIXTURE_NOT_LIVE
from app.modules.historical.sources.cbr_banks.source import (
    CbrBanksHistoricalSource,
    wrap_sber_soap_bundle,
)
from app.modules.intelligence.banks.cbr_soap import CbrSoapParseResult
from app.modules.intelligence.banks.metrics import INDUSTRIAL_RATIO_CODES
from app.modules.intelligence.banks.providers import CBR_CREDIT_ORG_BY_SECID

FIXED = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
PERIOD = date(2026, 9, 1)


def _intelligence_fixtures() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "intelligence" / "banks" / "test_sber_cbr_soap.py"
    spec = importlib.util.spec_from_file_location("sber_cbr_soap_unit_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._FIXTURES


def _source(**kwargs: object) -> CbrBanksHistoricalSource:
    defaults: dict[str, object] = {"observed_at": FIXED}
    defaults.update(kwargs)
    return CbrBanksHistoricalSource(**defaults)  # type: ignore[arg-type]


def _by_id(source: CbrBanksHistoricalSource) -> dict[str, HistoricalArtifact]:
    return {artifact.source_id: artifact for artifact in source.fetch_sample()}


def test_fixture_matches_intelligence_unit_fixture() -> None:
    assert SBER_SOAP_FIXTURE_NOT_LIVE == _intelligence_fixtures()
    assert CBR_CREDIT_ORG_BY_SECID["SBER"].regnum == "1481"


def test_fixture_not_live_wraps_partial_sber_metrics() -> None:
    source = _source()
    coverage = source.inspect_coverage()
    artifacts = _by_id(source)
    assert coverage.status == AdapterStatus.PARTIAL
    assert coverage.status != AdapterStatus.READY
    assert "fixture_not_live" in coverage.limitations
    assert coverage.earliest == PERIOD
    assert coverage.latest == PERIOD

    form101 = artifacts["CBR-06"]
    form102 = artifacts["CBR-07"]
    form123 = artifacts["CBR-08"]
    form135 = artifacts["CBR-09"]
    assert form101.fetch_status == FetchStatus.EMPTY
    assert form101.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert form101.period_end is None

    for artifact in (form102, form123, form135):
        assert artifact.fetch_status == FetchStatus.OK
        assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
        assert artifact.published_at is None
        assert artifact.period_end == PERIOD
        assert artifact.first_observed_at == FIXED
        assert artifact.period_end != artifact.first_observed_at.date()
        assert artifact.chronology_errors() == ()
        assert "fixture_not_live" in artifact.limitations
        assert "not_live_history" in artifact.limitations
        assert artifact.quality_status == RecordQuality.QUARANTINE

    observations = {
        item.metric_id: item
        for artifact in source.fetch_sample()
        for item in source.parse(artifact, source.raw_for(artifact))
    }
    assert set(observations) == {"NET_PROFIT", "EQUITY", "CAPITAL_ADEQUACY"}
    assert observations["EQUITY"].value == 8092364887
    assert observations["EQUITY"].unit == "thousand_rub"
    assert observations["EQUITY"].currency == "RUB"
    assert observations["EQUITY"].source_id == "CBR-08"
    assert observations["EQUITY"].extra["field"] == "000"
    assert observations["NET_PROFIT"].value == 1332707281
    assert observations["NET_PROFIT"].value != 1163640131 + 1332707281
    assert observations["NET_PROFIT"].source_id == "CBR-07"
    assert observations["CAPITAL_ADEQUACY"].value == pytest.approx(13.095)
    assert observations["CAPITAL_ADEQUACY"].unit == "percent"
    assert observations["CAPITAL_ADEQUACY"].extra["raw_value"] == "13.095"
    assert observations["CAPITAL_ADEQUACY"].source_id == "CBR-09"
    for item in observations.values():
        assert item.period_end == PERIOD
        assert item.extra["known_at"] == FIXED.isoformat()
        assert item.extra["known_at"][:10] != item.period_end.isoformat()
        assert item.extra["period_end_is_not_known_at"] is True
        assert item.extra["origin"] == "fixture_not_live"
        assert item.extra["pit"] == PitQuality.PIT_PROXY.value
        assert item.quality_errors() == ()
        assert "inn" not in item.issuer_identity
        assert item.issuer_identity["regnum"] == "1481"
    assert set(INDUSTRIAL_RATIO_CODES).isdisjoint(observations)
    assert {"TOTAL_ASSETS", "LOAN_BOOK", "DEPOSITS"}.isdisjoint(observations)


def test_default_clock_is_now_and_not_the_form_period() -> None:
    before = datetime.now(UTC) - timedelta(seconds=2)
    source = CbrBanksHistoricalSource()
    equity = next(item for item in source.fetch_sample() if item.source_id == "CBR-08")
    after = datetime.now(UTC) + timedelta(seconds=2)
    assert before <= equity.first_observed_at <= after
    assert equity.period_end == PERIOD
    assert equity.period_end != equity.first_observed_at.date()
    assert equity.historical_pit_quality == PitQuality.PIT_PROXY


def test_discover_does_not_fetch_and_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_kwargs: object) -> dict[str, str]:
        raise AssertionError("discover must not call SOAP")

    monkeypatch.setattr(
        "app.modules.historical.sources.cbr_banks.source.fetch_cbr_soap_bundle",
        _boom,
    )
    coverage = CbrBanksHistoricalSource(live=True, observed_at=FIXED).discover()
    assert coverage.status == AdapterStatus.PARTIAL
    assert coverage.earliest is None
    assert "0409101" in coverage.formats
    assert "partial_not_ready" in coverage.limitations


def test_failed_live_fetch_uses_labeled_fixture_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _boom(*, regnum: str, timeout_s: float) -> dict[str, str]:
        calls.append(regnum)
        assert timeout_s == 15
        raise RuntimeError("cbr down")

    monkeypatch.setattr(
        "app.modules.historical.sources.cbr_banks.source.fetch_cbr_soap_bundle",
        _boom,
    )
    source = CbrBanksHistoricalSource(live=True, observed_at=FIXED, timeout_s=15)
    sample = source.fetch_sample()
    source.fetch_range(start=PERIOD, end=PERIOD, limit=10)
    source.inspect_coverage()
    assert calls == ["1481"]
    summary = source.summary()
    assert summary["origin"] == "fixture_not_live"
    assert summary["status"] == AdapterStatus.PARTIAL.value
    assert summary["status"] != AdapterStatus.READY.value
    assert summary["fetch_error"] == "cbr_soap_fetch_failed:RuntimeError"
    metrics = {row["source_id"]: [item["metric_id"] for item in row["metrics"]] for row in summary["forms"]}
    assert metrics["CBR-06"] == []
    assert metrics["CBR-07"] == ["NET_PROFIT"]
    assert metrics["CBR-08"] == ["EQUITY"]
    assert metrics["CBR-09"] == ["CAPITAL_ADEQUACY"]
    assert all("fixture_not_live" in artifact.limitations for artifact in sample)


def test_live_bundle_is_not_replaced_with_fixture_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    def _live(*, regnum: str, timeout_s: float) -> dict[str, str]:
        assert regnum == "1481"
        assert timeout_s == 60
        bundle = dict(SBER_SOAP_FIXTURE_NOT_LIVE)
        bundle.pop("form102_enum")
        bundle["form123"] = bundle["form123"].replace("8092364887", "1000")
        return bundle

    monkeypatch.setattr(
        "app.modules.historical.sources.cbr_banks.source.fetch_cbr_soap_bundle",
        _live,
    )
    source = CbrBanksHistoricalSource(live=True, observed_at=FIXED)
    summary = source.summary()
    assert summary["origin"] == "live"
    assert summary["fetch_error"] is None
    assert summary["status"] == "PARTIAL"
    by_form = {row["source_id"]: row for row in summary["forms"]}
    assert by_form["CBR-08"]["metrics"][0]["value"] == 1000
    assert by_form["CBR-08"]["pit"] == PitQuality.PIT_PROXY.value
    assert "fixture_not_live" not in source.fetch_sample()[0].limitations
    profit = next(
        item
        for artifact in source.fetch_sample()
        for item in source.parse(artifact, source.raw_for(artifact))
        if item.metric_id == "NET_PROFIT"
    )
    assert "f102_definition_pinned_not_rechecked" in profit.limitations


def test_undocumented_publication_element_stays_proxy() -> None:
    bundle = dict(SBER_SOAP_FIXTURE_NOT_LIVE)
    bundle["form123"] = bundle["form123"].replace(
        "<F123DATA OnDate=\"20260901\">",
        "<F123DATA OnDate=\"20260901\"><PubDate>2026-10-11T08:00:00+00:00</PubDate>",
    )
    source = _source(fixtures=bundle)
    artifacts = _by_id(source)
    form123 = artifacts["CBR-08"]
    form135 = artifacts["CBR-09"]
    assert form123.historical_pit_quality == PitQuality.PIT_PROXY
    assert form123.published_at is None
    assert form123.chronology_errors() == ()
    assert form123.historical_availability_evidence == "cbr_reporting_period_not_verified_archive_snapshot"
    assert "undocumented_publication_element_not_a_publication_timestamp" in form123.limitations
    assert form135.historical_pit_quality == PitQuality.PIT_PROXY
    assert form135.published_at is None
    assert "undocumented_publication_element_not_a_publication_timestamp" not in form135.limitations
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL


def test_fetch_clock_is_not_a_publication_timestamp() -> None:
    bundle = dict(SBER_SOAP_FIXTURE_NOT_LIVE)
    bundle["form123"] = bundle["form123"].replace(
        "<F123DATA OnDate=\"20260901\">",
        f"<F123DATA OnDate=\"20260901\"><PubDate>{FIXED.isoformat()}</PubDate>",
    )
    form123 = _by_id(_source(fixtures=bundle))["CBR-08"]
    assert form123.historical_pit_quality == PitQuality.PIT_PROXY
    assert form123.published_at is None
    assert form123.published_at != form123.first_observed_at
    assert form123.chronology_errors() == ()
    assert "publication_timestamp_equals_fetch_clock_not_used" in form123.limitations
    assert "undocumented_publication_element_not_a_publication_timestamp" in form123.limitations


def test_reporting_date_and_same_day_timestamp_stay_proxy() -> None:
    bundle = dict(SBER_SOAP_FIXTURE_NOT_LIVE)
    bundle["form135"] = bundle["form135"].replace(
        "<F135DATA OnDate=\"20260901\">",
        "<F135DATA OnDate=\"20260901\"><PubDate>2026-09-01T12:00:00+00:00</PubDate>",
    )
    source = _source(fixtures=bundle)
    form135 = _by_id(source)["CBR-09"]
    assert form135.historical_pit_quality == PitQuality.PIT_PROXY
    assert form135.published_at is None
    assert form135.chronology_errors() == ()
    assert form135.period_end == date(2026, 9, 1)
    assert "publication_timestamp_equals_period_end_not_used" in form135.limitations
    assert "undocumented_publication_element_not_a_publication_timestamp" in form135.limitations


def test_parser_proved_assets_pass_and_industrial_ratios_do_not(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.historical.sources.cbr_banks.source as source_mod

    original = source_mod.parse_cbr_soap_metrics

    def _fake(**kwargs: object) -> CbrSoapParseResult:
        real = original(**kwargs)  # type: ignore[arg-type]
        metrics = dict(real.metrics)
        metrics["REVENUE"] = {
            "value": 1,
            "unit": "thousand_rub",
            "form": "0409102",
            "field": "industrial",
            "definition": "forbidden",
        }
        metrics["TOTAL_ASSETS"] = {
            "value": 42,
            "unit": "thousand_rub",
            "form": "0409101",
            "field": "assets",
            "definition": "parser proved",
            "period_end": "2026-09-01",
        }
        return CbrSoapParseResult(
            metrics=metrics,
            period_end=real.period_end,
            limitations=real.limitations,
            facts=real.facts,
        )

    monkeypatch.setattr(source_mod, "parse_cbr_soap_metrics", _fake)
    source = _source()
    observations = [
        item
        for artifact in source.fetch_sample()
        for item in source.parse(artifact, source.raw_for(artifact))
    ]
    assert "REVENUE" not in {item.metric_id for item in observations}
    assets = next(item for item in observations if item.metric_id == "TOTAL_ASSETS")
    assert assets.source_id == "CBR-06"
    assert assets.value == 42
    assert assets.extra["parser_proved"] is True
    rejected = source.validate(
        (
            assets,
            type(assets)(
                metric_id="EBITDA",
                source_id="CBR-06",
                content_hash=assets.content_hash,
                normalization_version=assets.normalization_version,
                quality_status=assets.quality_status,
                value=1,
                evidence="injected",
                extra={"parser_proved": True, "known_at": FIXED.isoformat()},
            ),
            type(assets)(
                metric_id="LOAN_BOOK",
                source_id="CBR-06",
                content_hash=assets.content_hash,
                normalization_version=assets.normalization_version,
                quality_status=assets.quality_status,
                value=1,
                evidence="unproved",
                extra={"known_at": FIXED.isoformat()},
            ),
        )
    )
    assert [item.metric_id for item in rejected] == ["TOTAL_ASSETS"]


def test_validate_drops_known_at_equal_to_period_end() -> None:
    wrapped = wrap_sber_soap_bundle(
        SBER_SOAP_FIXTURE_NOT_LIVE,
        origin="fixture_not_live",
        observed_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    assert wrapped.status == AdapterStatus.PARTIAL
    assert wrapped.observations == ()
    equity = next(item for item in wrapped.artifacts if item.source_id == "CBR-08")
    assert equity.first_observed_at.date() == equity.period_end
    assert "period_end_equals_first_observed_at" in equity.limitations


def test_fetch_range_keeps_undated_form_101() -> None:
    source = _source()
    early = source.fetch_range(start=date(2020, 1, 1), end=date(2020, 12, 31), limit=10)
    assert [item.source_id for item in early] == ["CBR-06"]
    covered = source.fetch_range(start=PERIOD, end=PERIOD, limit=10)
    assert [item.source_id for item in covered] == ["CBR-06", "CBR-07", "CBR-08", "CBR-09"]
    august = source.fetch_range(start=date(2026, 8, 1), end=date(2026, 8, 31), limit=10)
    assert [item.source_id for item in august] == ["CBR-06"]
    assert source.fetch_range(start=PERIOD, end=date(2026, 8, 1), limit=10) == ()


def test_source_does_not_import_polza_or_write_prospective_tables() -> None:
    import app.modules.historical.sources.cbr_banks.source as source_mod

    text = Path(source_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all("polza" not in name.lower() for name in imported)
    assert "prospective_captures" not in text
