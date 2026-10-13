"""FNS-03: the public LKOH BFO payload has no prior-correction list."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import FnsGirBoClient
from app.modules.historical.domain.evidence import AdapterStatus, PitQuality, PublishedAtPrecision
from app.modules.historical.sources.fns.revisions import (
    PILOT_INN,
    PILOT_SECID,
    FnsGirBoRevisionSource,
    payload_has_revision_list,
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
OBSERVED_AT = datetime(2026, 10, 12, 20, 25, tzinfo=UTC)


def _fixture() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["inn"] == PILOT_INN == "7708004767"
    assert payload["secid"] == PILOT_SECID == "LKOH"
    return payload


def _client(search: dict[str, Any], periods: list[dict[str, Any]], *, status: int = 200) -> FnsGirBoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"status": status})
        if "advanced-search" in request.url.path:
            return httpx.Response(200, json=search)
        if request.url.path.endswith("/bfo/"):
            return httpx.Response(200, json=periods)
        return httpx.Response(404, json={"path": request.url.path})

    return FnsGirBoClient(transport=httpx.MockTransport(handler), pacing_seconds=0)


def _source(payload: dict[str, Any], **kwargs: Any) -> FnsGirBoRevisionSource:
    periods = kwargs.pop("periods", payload["periods"])
    search = kwargs.pop("search", payload["search"])
    client = kwargs.pop("client", None)
    if client is None:
        client = _client(search, periods)
    return FnsGirBoRevisionSource(
        client,
        inn=str(kwargs.pop("inn", payload["inn"])),
        secid=str(kwargs.pop("secid", payload["secid"])),
        observed_at=kwargs.pop("observed_at", OBSERVED_AT),
    )


def _revision_lists(period: dict[str, Any]) -> list[str]:
    """Lists of correction objects. A type slot with one correction dict is not one."""
    found: list[str] = []
    for key, value in period.items():
        if key == "typeCorrections":
            continue
        if isinstance(value, list):
            found.append(key)
    slots = period.get("typeCorrections")
    assert isinstance(slots, list)
    for index, slot in enumerate(slots):
        assert isinstance(slot, dict)
        for key, value in slot.items():
            if isinstance(value, list):
                found.append(f"typeCorrections[{index}].{key}")
        correction = slot.get("correction")
        if isinstance(correction, list):
            found.append(f"typeCorrections[{index}].correction")
        elif isinstance(correction, dict):
            for key, value in correction.items():
                if isinstance(value, list):
                    found.append(f"typeCorrections[{index}].correction.{key}")
    return found


def test_lkoh_payload_has_no_revision_list() -> None:
    periods = _fixture()["periods"]
    assert len(periods) == 5
    assert payload_has_revision_list(periods) is False
    for period in periods:
        assert isinstance(period["actualCorrectionNumber"], int)
        assert period["actualCorrectionNumber"] == 0
        assert "corrections" not in period
        assert "revisions" not in period
        assert "revisionHistory" not in period
        slots = period["typeCorrections"]
        assert len(slots) == 1
        correction = slots[0]["correction"]
        assert isinstance(correction, dict)
        assert correction["correctionVersion"] == 0
        assert "corrections" not in slots[0]
        assert _revision_lists(period) == []


def test_lkoh_discovery_emits_zero_prior_revisions() -> None:
    payload = _fixture()
    result = _source(payload).run()

    assert result.discover_status is AdapterStatus.PARTIAL
    assert result.revisions_status is AdapterStatus.BLOCKED
    assert result.payload_has_revision_list is False
    assert result.period_count == 5
    assert result.latest_correction_count == 5
    assert result.prior_revision_count == 0
    assert result.prior_revisions == ()
    assert result.observations == ()
    assert result.http_error is None
    assert "no_revision_list" in result.evidence
    assert "correction_value_is_object" in result.evidence
    assert "actualCorrectionNumber_is_scalar" in result.evidence
    assert "prior_corrections_not_in_public_bfo" in result.blockers
    assert result.pit == ("PIT_PROXY", "RESEARCH_ONLY")

    expected_ids = {str(period["typeCorrections"][0]["correction"]["id"]) for period in payload["periods"]}
    assert {item.revision_identifier for item in result.latest} == expected_ids
    for item in result.latest:
        assert item.published_at is not None
        assert item.period_end == date(item.fiscal_year, 12, 31)
        assert item.period_end != item.published_at.date()
        assert item.published_at_precision in {
            PublishedAtPrecision.DATE_ONLY,
            PublishedAtPrecision.TIMESTAMP,
        }
        assert item.pit_quality in {PitQuality.PIT_PROXY, PitQuality.RESEARCH_ONLY}
    proxy = next(item for item in result.latest if item.fiscal_year == 2024)
    assert proxy.pit_quality is PitQuality.PIT_PROXY
    assert proxy.published_at_precision is PublishedAtPrecision.DATE_ONLY
    clock = next(item for item in result.latest if item.fiscal_year == 2025)
    assert clock.pit_quality is PitQuality.RESEARCH_ONLY
    assert clock.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert _source(payload).fetch_sample() == ()


def test_scalar_correction_number_does_not_invent_revisions() -> None:
    payload = _fixture()
    period = {
        "id": 1,
        "period": "2020",
        "isCb": False,
        "actualBfoDate": "2021-03-20",
        "actualCorrectionNumber": 4,
        "publishedCorrectionNumber": 4,
        "publishedCorrectionDate": "2021-03-20",
        "typeCorrections": [
            {
                "type": 12,
                "correction": {
                    "id": 7,
                    "datePresent": "2021-03-20T00:00:00",
                    "correctionVersion": 0,
                    "periodType": 12,
                },
            }
        ],
    }
    result = _source(payload, periods=[period]).run()
    assert result.payload_has_revision_list is False
    assert result.prior_revision_count == 0
    assert result.prior_revisions == ()
    assert result.latest_correction_count == 1
    assert result.latest[0].revision_identifier == "7"
    assert result.latest[0].actual_correction_number == 4
    assert result.latest[0].period_end == date(2020, 12, 31)
    assert result.latest[0].published_at is not None
    assert result.latest[0].period_end != result.latest[0].published_at.date()
    assert result.revisions_status is AdapterStatus.BLOCKED
    assert result.discover_status is AdapterStatus.PARTIAL


def test_present_correction_list_keeps_each_identifier_and_the_latest() -> None:
    payload = _fixture()
    latest = {
        "id": 200,
        "datePresent": "2025-04-02T00:00:00",
        "correctionVersion": 1,
        "periodType": 12,
        "balance": {"current1600": 9},
    }
    prior = {
        "id": 100,
        "datePresent": "2025-03-01T00:00:00",
        "correctionVersion": 0,
        "periodType": 12,
        "balance": {"current1600": 1},
    }
    period = {
        "id": 55,
        "period": "2024",
        "isCb": False,
        "actualBfoDate": "2025-03-01",
        "actualCorrectionNumber": 1,
        "publishedCorrectionNumber": 1,
        "publishedCorrectionDate": "2025-04-02",
        "typeCorrections": [{"type": 12, "correction": latest, "corrections": [prior, latest]}],
    }
    result = _source(payload, periods=[period]).run()
    assert result.payload_has_revision_list is True
    assert result.prior_revision_count == 1
    assert result.latest_correction_count == 1
    assert result.latest[0].revision_identifier == "200"
    assert result.latest[0].correction_version == 1
    assert result.prior_revisions[0].revision_identifier == "100"
    assert result.prior_revisions[0].revision_identifier != result.latest[0].revision_identifier
    assert result.prior_revisions[0].period_end == date(2024, 12, 31)
    assert result.prior_revisions[0].published_at is not None
    assert result.prior_revisions[0].published_at.date() == date(2025, 3, 1)
    assert result.prior_revisions[0].period_end != result.prior_revisions[0].published_at.date()
    assert result.latest[0].published_at is not None
    assert result.latest[0].published_at.date() == date(2025, 4, 2)
    assert result.discover_status is AdapterStatus.PARTIAL
    assert result.revisions_status is AdapterStatus.PARTIAL
    assert result.observations == ()
    assert _source(payload, periods=[period]).parse(result.prior_revisions[0], b"{}") == ()


def test_correction_list_without_singular_object_does_not_drop_the_latest() -> None:
    payload = _fixture()
    older = {"id": 10, "datePresent": "2025-03-01T00:00:00", "correctionVersion": 0, "periodType": 12}
    newer = {"id": 11, "datePresent": "2025-05-01T00:00:00", "correctionVersion": 2, "periodType": 12}
    period = {
        "id": 9,
        "period": "2024",
        "isCb": False,
        "actualBfoDate": "2025-03-01",
        "actualCorrectionNumber": 2,
        "publishedCorrectionDate": "2025-05-01",
        "typeCorrections": [{"type": 12, "corrections": [older, newer]}],
    }
    result = _source(payload, periods=[period]).run()
    assert result.prior_revision_count == 1
    assert result.latest[0].revision_identifier == "11"
    assert result.latest[0].correction_version == 2
    assert result.prior_revisions[0].revision_identifier == "10"
    assert {item.revision_identifier for item in result.prior_revisions} | {result.latest[0].revision_identifier} == {
        "10",
        "11",
    }


def test_bank_secid_emits_no_industrial_ratios() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, json={"no": "call"})

    client = FnsGirBoClient(transport=httpx.MockTransport(handler), pacing_seconds=0)
    result = FnsGirBoRevisionSource(
        client,
        inn="7707083893",
        secid="SBER",
        observed_at=OBSERVED_AT,
    ).run()
    assert calls == []
    assert result.discover_status is AdapterStatus.PARTIAL
    assert result.revisions_status is AdapterStatus.BLOCKED
    assert result.prior_revision_count == 0
    assert result.observations == ()
    assert "BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1" in result.blockers


def test_bank_period_is_not_parsed_as_industrial_revisions() -> None:
    payload = _fixture()
    period = {
        "id": 3,
        "period": "2024",
        "isCb": True,
        "actualCorrectionNumber": 2,
        "typeCorrections": [
            {
                "type": 12,
                "correction": {"id": 1, "datePresent": "2025-03-01T00:00:00", "correctionVersion": 1},
                "corrections": [
                    {"id": 1, "correctionVersion": 1, "datePresent": "2025-03-01T00:00:00"},
                    {"id": 2, "correctionVersion": 0, "datePresent": "2025-02-01T00:00:00"},
                ],
            }
        ],
    }
    result = _source(payload, periods=[period]).run()
    assert result.prior_revision_count == 0
    assert result.latest == ()
    assert result.observations == ()
    assert result.payload_has_revision_list is False
    assert "is_cb_period_skipped" in result.limitations
    assert result.revisions_status is AdapterStatus.BLOCKED


def test_module_does_not_call_llm_memory_or_stage_1000() -> None:
    source = Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "fns" / "revisions.py"
    body = source.read_text(encoding="utf-8").lower()
    assert "polza" not in body
    assert "prospective_captures" not in body
    assert "stage_1000" not in body
    assert "committee_decisions" not in body
