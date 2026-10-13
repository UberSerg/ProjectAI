"""Offline IR-01 / IR-07 pilot. Numbers come from the captured Lukoil databook."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import BANK_FI_SECIDS
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    ParsedObservation,
    PitQuality,
    RecordQuality,
)
from app.modules.historical.sources.issuer_statements.source import (
    PILOT_HTTP_STATUS,
    PILOT_SHA256,
    PILOT_URL,
    IssuerStatementsSource,
    chronology_problems,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "issuer_statements"
    / "fixtures"
    / "lukoil_analyst_databook_4q2021.xlsx"
)
OBSERVED = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
EXPECTED = {
    "ifrs.CASH_AND_EQUIVALENTS": 677_482.0,
    "ifrs.TOTAL_ASSETS": 6_864_749.0,
    "ifrs.TOTAL_EQUITY": 4_523_184.0,
    "ifrs.SALES_INCLUDING_EXCISE_AND_EXPORT_DUTIES": 9_435_143.0,
    "ifrs.OPERATING_INCOME": 978_945.0,
    "ifrs.NET_INCOME": 773_442.0,
    "ifrs.OPERATING_CASH_FLOW": 1_126_614.0,
}


def _payload() -> bytes:
    body = FIXTURE.read_bytes()
    assert len(body) == 395_529
    return body


def _source(payload: bytes | None = None, **kwargs: object) -> IssuerStatementsSource:
    origin = kwargs.pop("fixture_origin", "live_capture")
    return IssuerStatementsSource(
        payload=_payload() if payload is None else payload,
        secid=str(kwargs.pop("secid", "LKOH")),
        observed_at=kwargs.pop("observed_at", OBSERVED),  # type: ignore[arg-type]
        fixture_origin=origin,  # type: ignore[arg-type]
        transport=kwargs.pop("transport", None),  # type: ignore[arg-type]
    )


def test_captured_workbook_parses_one_ifrs_year_and_blocks_ras() -> None:
    source = _source()
    result = source.run()
    coverage = source.discover()
    sample = source.fetch_sample(limit=30)
    ranged = source.fetch_range(start=date(2021, 1, 1), end=date(2021, 12, 31), limit=10)
    outside = source.fetch_range(start=date(2020, 1, 1), end=date(2020, 12, 31), limit=10)

    assert result.ir01_status is AdapterStatus.READY
    assert result.ir07_status is AdapterStatus.BLOCKED
    assert result.blockers == ()
    assert result.http_status == PILOT_HTTP_STATUS == 200
    assert result.http_status_source == "pilot_capture"
    assert result.issuer == "ПАО «ЛУКОЙЛ»"
    assert result.secid == "LKOH"
    assert result.source_url == PILOT_URL
    assert result.fact_count == 7
    assert result.ras_fact_count == 0
    assert result.metrics == tuple(EXPECTED)
    assert result.periods == ("FY:2021",)
    assert result.pit == ("RESEARCH_ONLY",)
    assert coverage.status is AdapterStatus.READY
    assert coverage.earliest == coverage.latest == date(2021, 12, 31)
    assert len(sample) == 1
    assert len(ranged) == 1
    assert outside == ()

    artifact = result.artifacts[0]
    assert artifact.source_id == "IR-01"
    assert artifact.period_end == date(2021, 12, 31)
    assert artifact.published_at is None
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.historical_pit_quality is not PitQuality.PIT_VERIFIED
    assert artifact.content_hash == PILOT_SHA256
    assert "published_at_not_stated_in_workbook" in artifact.limitations
    assert "no_ras_statement_in_document" in artifact.limitations
    assert chronology_problems(artifact) == ()
    assert artifact.period_end != artifact.first_observed_at.date()

    by_metric = {item.metric_id: item for item in result.observations}
    assert set(by_metric) == set(EXPECTED)
    assert "ifrs.REVENUE" not in by_metric
    assert "ifrs.EBITDA" not in by_metric
    assert not any("RATIO" in item.metric_id or item.metric_id.endswith("ROE") for item in result.observations)
    for metric_id, value in EXPECTED.items():
        row = by_metric[metric_id]
        assert row.value == value
        assert row.unit == "million_rub"
        assert row.currency == "RUB"
        assert row.reporting_standard == "IFRS"
        assert row.period_end == date(2021, 12, 31)
        assert row.source_id == "IR-01"
        assert row.quality_errors() == ()
        assert row.issuer_identity["secid"] == "LKOH"
    sales = by_metric["ifrs.SALES_INCLUDING_EXCISE_AND_EXPORT_DUTIES"]
    assert sales.evidence == "Выручка от реализации (включая акцизы и экспортные пошлины)"
    assert "not_canonical_revenue" in sales.limitations
    assert "ras_statement_absent_from_capped_document" in result.limitations
    assert not any(item.source_id == "IR-07" for item in result.observations)

    parsed = source.parse(artifact, result.raw_by_document_id[artifact.external_document_id])
    assert [item.metric_id for item in parsed] == list(EXPECTED)
    assert all(item.quality_errors() == () for item in source.validate(tuple(parsed)))


def test_bank_secid_does_not_fetch_or_emit_industrial_lines() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, content=b"no")

    result = IssuerStatementsSource(
        transport=httpx.MockTransport(handler),
        secid="SBER",
        observed_at=OBSERVED,
        fixture_origin="live_capture",
    ).run()
    assert calls == []
    assert result.ir01_status is AdapterStatus.BLOCKED
    assert result.ir07_status is AdapterStatus.BLOCKED
    assert result.fact_count == 0
    assert result.ras_fact_count == 0
    assert result.metrics == ()
    assert result.http_status is None
    assert result.http_status_source == "not_requested"
    assert "BANK_FI_NOT_SUPPORTED" in result.blockers
    assert "industrial_statement_lines_not_emitted" in result.limitations
    assert "SBER" in BANK_FI_SECIDS


def test_http_forbidden_is_blocked_without_fabricated_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden")

    result = IssuerStatementsSource(
        transport=httpx.MockTransport(handler),
        observed_at=OBSERVED,
        fixture_origin="live_http",
    ).run()
    assert result.http_status == 403
    assert result.http_status_source == "response"
    assert result.ir01_status is AdapterStatus.BLOCKED
    assert result.ir07_status is AdapterStatus.BLOCKED
    assert result.blockers == ("HTTP 403",)
    assert result.fact_count == 0
    assert result.ras_fact_count == 0
    assert result.observations == ()
    assert result.artifacts == ()
    assert result.pit == ()


def test_html_200_is_not_a_statement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>anti-bot</html>")

    result = IssuerStatementsSource(
        transport=httpx.MockTransport(handler),
        observed_at=OBSERVED,
        fixture_origin="live_http",
    ).run()
    assert result.http_status == 200
    assert result.ir01_status is AdapterStatus.BLOCKED
    assert result.ir07_status is AdapterStatus.BLOCKED
    assert result.fact_count == 0
    assert result.ras_fact_count == 0
    assert "response_is_not_xlsx" in result.blockers


def test_synthetic_fixture_cannot_claim_ready() -> None:
    result = _source(fixture_origin="synthetic_not_live").run()
    assert result.fact_count == 7
    assert result.ir01_status is AdapterStatus.PENDING
    assert result.ir01_status is not AdapterStatus.READY
    assert "synthetic_not_live_fixture_cannot_claim_ready" in result.blockers
    assert result.ir07_status is AdapterStatus.BLOCKED
    assert result.ras_fact_count == 0


def test_validate_quarantines_zero_without_explicit_mark() -> None:
    zero = ParsedObservation(
        metric_id="ifrs.TOTAL_ASSETS",
        source_id="IR-01",
        content_hash="abc",
        normalization_version="issuer_ifrs_databook_lines_v1",
        quality_status=RecordQuality.ACCEPTED,
        value=0,
        evidence="Итого активы",
        issuer_identity={"secid": "LKOH"},
    )
    checked = _source().validate((zero,))
    assert checked[0].quality_status is RecordQuality.QUARANTINE
    assert "zero_requires_explicit_zero_mark" in zero.quality_errors()


def test_adapter_does_not_touch_llm_memory_or_stage_1000() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "modules"
        / "historical"
        / "sources"
        / "issuer_statements"
        / "source.py"
    )
    body = source.read_text(encoding="utf-8").lower()
    assert "polza" not in body
    assert "prospective" not in body
    assert "stage_1000" not in body
    assert "stage-1000" not in body


@pytest.mark.parametrize("secid", ["LKOH", "SBER", "VTBR"])
def test_pilot_issuer_is_not_a_bank(secid: str) -> None:
    assert (secid in BANK_FI_SECIDS) is (secid != "LKOH")
