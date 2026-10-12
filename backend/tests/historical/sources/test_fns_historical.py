"""Offline FNS historical pilot. Numbers come from the captured GIR BO payload."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import FnsGirBoClient
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    ParsedObservation,
    PitQuality,
    RecordQuality,
)
from app.modules.historical.sources.fns.adapter import (
    PILOT_INN,
    PILOT_SECID,
    chronology_problems,
)
from app.modules.historical.sources.fns.adapter import (
    FnsGirBoHistoricalSource as Source,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "fns"
    / "fixtures"
    / "lkoh_gir_bo_live.json"
)
LIVE_BFO_SHA256 = "c2906d79d3ab738b6f01355928824c29ba5d2bb2de8d65ba52c18a6c88614bf0"
RAS_METRICS = {
    "ras.TOTAL_ASSETS",
    "ras.TOTAL_EQUITY",
    "ras.CASH_AND_EQUIVALENTS",
    "ras.TOTAL_DEBT",
    "ras.REVENUE",
    "ras.OPERATING_INCOME",
    "ras.NET_INCOME",
    "ras.OPERATING_CASH_FLOW",
}


def _fixture() -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["fixture_origin"] == "live_capture"
    assert payload["full_bfo_sha256"] == LIVE_BFO_SHA256
    return payload


def _client(payload: dict, *, status: int = 200, calls: list[str] | None = None) -> FnsGirBoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        if status != 200:
            return httpx.Response(status, json={"status": status})
        if "advanced-search" in request.url.path:
            return httpx.Response(200, json=payload["search"])
        if "/bfo" in request.url.path:
            return httpx.Response(200, json=payload["periods"])
        return httpx.Response(404, json={"path": request.url.path})

    return FnsGirBoClient(transport=httpx.MockTransport(handler), pacing_seconds=0)


def _source(payload: dict, **kwargs: object) -> Source:
    observed = kwargs.pop("observed_at", datetime.fromisoformat(payload["captured_at"]))
    origin = kwargs.pop("fixture_origin", payload["fixture_origin"])
    client = kwargs.pop("client", None)
    calls = kwargs.pop("calls", None)
    if client is None:
        client = _client(payload, calls=calls)  # type: ignore[arg-type]
    return Source(
        client,  # type: ignore[arg-type]
        inn=str(kwargs.pop("inn", payload["inn"])),
        secid=str(kwargs.pop("secid", payload["secid"])),
        observed_at=observed,  # type: ignore[arg-type]
        fixture_origin=origin,  # type: ignore[arg-type]
    )


def test_live_capture_pilot_is_ready_for_one_industrial_org() -> None:
    payload = _fixture()
    calls: list[str] = []
    source = _source(payload, calls=calls)
    coverage = source.discover()
    result = source.run()
    again = source.fetch_sample(limit=30)
    ranged = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 12, 31), limit=10)

    org_id = payload["search"]["content"][0]["id"]
    assert result.status is AdapterStatus.READY
    assert result.blockers == ()
    assert result.http_error is None
    assert result.identity_basis["inn"] == PILOT_INN == "7708004767"
    assert result.identity_basis["ogrn"] == "1027700035769"
    assert result.identity_basis["fns_org_id"] == str(org_id) == "6681478"
    assert result.identity_basis["secid"] == PILOT_SECID == "LKOH"
    assert result.identity_basis["support_status"] == "INDUSTRIAL_RAS_V1"
    assert result.identity_basis["mapping_status"] == "EXACT_IDENTIFIER"
    assert result.periods == ("FY:2021", "FY:2022", "FY:2023", "FY:2024", "FY:2025")
    assert result.fact_count == 40
    assert result.pit == ("PIT_PROXY", "RESEARCH_ONLY")
    assert coverage.status is AdapterStatus.READY
    assert coverage.earliest == date(2021, 12, 31)
    assert coverage.latest == date(2025, 12, 31)
    assert calls == [
        "/advanced-search/organizations/search",
        f"/nbo/organizations/{org_id}/bfo/",
    ]
    assert [item.external_document_id for item in again] == [
        item.external_document_id for item in result.statement_artifacts
    ]
    assert len(ranged) == 1
    assert ranged[0].reporting_period == "FY:2024"

    by_period = {item.reporting_period: item for item in result.statement_artifacts}
    proxy = by_period["FY:2024"]
    assert proxy.historical_pit_quality is PitQuality.PIT_PROXY
    assert "fns_publication_timestamp_absent" in proxy.limitations
    researched = by_period["FY:2025"]
    assert researched.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "fns_date_present_timezone_unspecified" in researched.limitations
    assert "fns_published_correction_date_differs_from_date_present" in researched.limitations
    for artifact in result.statement_artifacts:
        assert artifact.published_at is not None
        assert artifact.period_end != artifact.first_observed_at.date()
        assert artifact.period_end != artifact.published_at.date()
        assert chronology_problems(artifact) == ()
        assert artifact.period_end == date(int(artifact.reporting_period.split(":")[1]), 12, 31)
        assert artifact.first_observed_at == datetime(2026, 10, 12, 20, 25, tzinfo=UTC)

    ras = [item for item in result.observations if item.metric_id.startswith("ras.")]
    assert {item.metric_id for item in ras} == RAS_METRICS
    assert all(item.quality_errors() == () for item in source.validate(tuple(ras)))
    assert all("explicit_zero" in item.limitations or item.value != 0 for item in ras)
    period_2025 = next(row for row in payload["periods"] if row["period"] == "2025")
    expected_revenue = period_2025["typeCorrections"][0]["correction"]["financialResult"]["current2110"]
    revenue = next(item for item in ras if item.metric_id == "ras.REVENUE" and item.period == "FY:2025")
    assert revenue.value == expected_revenue
    assert revenue.reporting_standard == "RAS"
    assert revenue.issuer_identity["ogrn"] == "1027700035769"
    identity = next(item for item in result.observations if item.metric_id == "issuer.identity")
    assert identity.source_id == "FNS-02"
    assert identity.evidence == "fns_advanced_search_exact_inn"
    assert "fns_search_snapshot_has_no_publication_timestamp" in identity.limitations
    parsed = source.parse(proxy, result.raw_by_document_id[proxy.external_document_id])
    assert len(parsed) == 8
    assert {item.metric_id for item in parsed} <= RAS_METRICS


def test_bank_secid_does_not_fetch_or_emit_industrial_ratios() -> None:
    payload = _fixture()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, json={"no": "call"})

    client = FnsGirBoClient(transport=httpx.MockTransport(handler), pacing_seconds=0)
    result = Source(
        client,
        inn="7707083893",
        secid="SBER",
        observed_at=datetime(2026, 10, 12, 20, 25, tzinfo=UTC),
        fixture_origin=payload["fixture_origin"],
    ).run()
    assert calls == []
    assert result.status is not AdapterStatus.READY
    assert result.fact_count == 0
    assert result.statement_artifacts == ()
    assert "BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1" in result.limitations
    assert not any(item.metric_id.startswith("ras.") for item in result.observations)


def test_http_forbidden_is_blocked_without_fabricated_statements() -> None:
    payload = _fixture()
    result = _source(payload, client=_client(payload, status=403)).run()
    assert result.status is AdapterStatus.BLOCKED
    assert result.http_error == "HTTP 403"
    assert "http_403" in result.limitations
    assert result.fact_count == 0
    assert result.statement_artifacts == ()
    assert result.periods == ()
    assert result.pit == ()


def test_synthetic_fixture_cannot_claim_ready() -> None:
    payload = _fixture()
    result = _source(payload, fixture_origin="synthetic_not_live").run()
    assert result.fact_count == 40
    assert result.status is AdapterStatus.PENDING
    assert result.status is not AdapterStatus.READY
    assert "synthetic_not_live_fixture_cannot_claim_ready" in result.blockers


def test_unmarked_mock_cannot_claim_ready() -> None:
    payload = _fixture()
    result = _source(payload, fixture_origin=None).run()
    assert result.status is AdapterStatus.PENDING
    assert "unmarked_fixture_cannot_claim_ready" in result.blockers


def test_validate_quarantines_zero_without_explicit_mark() -> None:
    payload = _fixture()
    source = _source(payload)
    zero = ParsedObservation(
        metric_id="ras.TOTAL_DEBT",
        source_id="FNS-01",
        content_hash="abc",
        normalization_version="fns_ras_okud_lines_v1",
        quality_status=RecordQuality.ACCEPTED,
        value=0,
        evidence="balance.current1410+current1510",
    )
    checked = source.validate((zero,))
    assert checked[0].quality_status is RecordQuality.QUARANTINE
    assert "zero_requires_explicit_zero_mark" in zero.quality_errors()


def test_adapter_does_not_touch_polza_or_decision_memory() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "fns" / "adapter.py"
    )
    body = source.read_text(encoding="utf-8").lower()
    assert "polza" not in body
    assert "prospective_captures" not in body
    assert "committee_decisions" not in body


@pytest.mark.parametrize(
    ("secid", "expected"),
    [("LKOH", False), ("SBER", True), ("VTBR", True)],
)
def test_pilot_secid_is_not_a_bank(secid: str, expected: bool) -> None:
    from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import BANK_FI_SECIDS

    assert (secid in BANK_FI_SECIDS) is expected
    assert PILOT_SECID not in BANK_FI_SECIDS
