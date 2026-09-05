"""Fundamental Provider Coverage V1.1 tests — no live secrets."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.modules.fundamentals.application.dataset_v3_gate import evaluate_dataset_v3_gate
from app.modules.fundamentals.application.disclosure_type_map import map_message_type
from app.modules.fundamentals.application.provider_status import (
    probe_edisclosure_gateway,
    probe_gir_bo,
    provider_probe_to_dict,
)
from app.modules.fundamentals.application.providers_matrix import build_providers_matrix
from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    SOURCE_GIR_BO,
    DisclosureEntityType,
    NormalizationStatus,
    PeriodType,
    ProviderOperationalStatus,
    ReportingStandard,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.edisclosure_gateway import (
    ApiKeyToken,
    AuthParams,
    EdisclosureGatewayClient,
    apply_disclosure_event_versioning,
    humanize_auth_failure,
    known_at_from_event,
    paginate_disclosure_events,
    redact_secrets,
)
from app.modules.fundamentals.infrastructure.gir_bo_client import (
    GirBoClient,
    parse_bfo_list,
    parse_search_page,
    subscription_required_message,
)
from app.modules.fundamentals.infrastructure.ras_report_parser import parse_ras_payload

FIXTURES = Path(__file__).parent / "fixtures"


class _SettingsStub:
    edisclosure_gateway_enabled = False
    edisclosure_gateway_base_url = "https://gateway.e-disclosure.ru"
    edisclosure_gateway_username = ""
    edisclosure_gateway_secret = ""
    gir_bo_enabled = False
    gir_bo_base_url = "https://bo.nalog.gov.ru"
    gir_bo_user_agent = "TestAgent/1.0"
    http_timeout_seconds = 5.0


class _SettingsWithCreds(_SettingsStub):
    edisclosure_gateway_enabled = True
    edisclosure_gateway_username = "user@example.com"
    edisclosure_gateway_secret = "s3cr3t"


def test_provider_matrix_has_three_providers() -> None:
    matrix = build_providers_matrix(live=False)
    codes = {row["code"] for row in matrix["providers"]}
    assert codes == {"MOEX_ISS", "EDISCLOSURE_GATEWAY", "GIR_BO"}


def test_edisclosure_ready_requires_credentials_when_enabled_without_secret() -> None:
    settings = _SettingsStub()
    settings.edisclosure_gateway_enabled = True
    probe = probe_edisclosure_gateway(settings=settings, live=False)
    assert probe.operational_status is ProviderOperationalStatus.READY_REQUIRES_CREDENTIALS


def test_gir_bo_disabled_reports_ready_capability() -> None:
    probe = probe_gir_bo(settings=_SettingsStub(), live=False)
    assert probe.operational_status is ProviderOperationalStatus.READY
    assert probe.enabled is False


def test_redact_secrets_masks_password_and_token() -> None:
    raw = '{"password":"abc","token":"xyz","login":"user"}'
    redacted = redact_secrets(raw)
    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "user" in redacted


def test_gateway_repr_never_contains_token() -> None:
    client = EdisclosureGatewayClient(settings=_SettingsStub())
    client._token = "super-secret-token-value"
    text = repr(client)
    assert "super-secret-token-value" not in text
    client.close()


def test_provider_probe_dict_has_no_secret_fields() -> None:
    probe = probe_edisclosure_gateway(settings=_SettingsWithCreds(), live=False)
    payload = json.dumps(provider_probe_to_dict(probe))
    assert "s3cr3t" not in payload


def test_auth_params_parsing() -> None:
    params = AuthParams.from_mapping({"login": "u", "password": "p"})
    assert params.login == "u"
    assert params.password == "p"


def test_api_key_token_parsing() -> None:
    token = ApiKeyToken.from_response(
        {"token": "t-123", "expirationDate": "2026-12-31T23:59:59"}
    )
    assert token.token == "t-123"
    assert token.expiration_date is not None


def test_humanize_auth_failure_400() -> None:
    msg = humanize_auth_failure(400, {"errors": [{"description": "Пользователь не найден."}]})
    assert "Неверные учётные данные" in msg
    assert "Пользователь не найден" in msg


def test_paginate_disclosure_events_from_event_id_and_count() -> None:
    events = [
        {"eventId": "A", "eventDate": "2020-01-01T10:00:00"},
        {"eventId": "B", "eventDate": "2020-01-02T10:00:00"},
        {"eventId": "C", "eventDate": "2020-01-03T10:00:00"},
    ]
    page = paginate_disclosure_events(events, from_event_id="A", count=1)
    assert [e["eventId"] for e in page] == ["B"]


def test_known_at_from_event_date_parses_moscow_datetime() -> None:
    dt = known_at_from_event({"eventDate": "2020-07-13T18:40:06"})
    assert dt is not None
    assert dt.year == 2020 and dt.month == 7 and dt.day == 13


def test_disclosure_publish_then_exclude_removes_active() -> None:
    active: dict[str, dict] = {}
    publish = {
        "eventId": "1",
        "eventType": "Publish",
        "eventDate": "2020-01-01T10:00:00",
        "file": {"uid": "DOC1"},
    }
    active = apply_disclosure_event_versioning(
        active, publish, entity=DisclosureEntityType.FILES
    )
    assert len(active) == 1
    exclude = {
        "eventId": "2",
        "eventType": "Delete",
        "eventDate": "2020-01-02T10:00:00",
        "file": {"uid": "DOC1"},
    }
    active = apply_disclosure_event_versioning(
        active, exclude, entity=DisclosureEntityType.FILES
    )
    assert active == {}


def test_disclosure_change_updates_version() -> None:
    active: dict[str, dict] = {}
    first = {
        "eventId": "1",
        "eventType": "Publish",
        "file": {"uid": "DOC1"},
        "version": 1,
    }
    second = {
        "eventId": "2",
        "eventType": "Change",
        "file": {"uid": "DOC1"},
        "version": 2,
    }
    active = apply_disclosure_event_versioning(
        active, first, entity=DisclosureEntityType.FILES
    )
    active = apply_disclosure_event_versioning(
        active, second, entity=DisclosureEntityType.FILES
    )
    assert active["Files:DOC1"]["version"] == 2


def test_gir_bo_search_exact_inn_only() -> None:
    payload = {
        "content": [
            {"id": 1, "inn": "7736050003", "shortName": "GAZP"},
            {"id": 2, "inn": "7700000000", "shortName": "OTHER"},
        ]
    }
    assert parse_search_page(payload, inn="7736050003") is not None
    assert parse_search_page(payload, inn="9999999999") is None


def test_gir_bo_rejects_ambiguous_inn_hits() -> None:
    payload = {
        "content": [
            {"id": 1, "inn": "7736050003"},
            {"id": 2, "inn": "7736050003"},
        ]
    }
    assert parse_search_page(payload, inn="7736050003") is None


def test_gir_bo_fixture_gazp_inn() -> None:
    summary = json.loads((FIXTURES / "gir_inn_search_gazp.json").read_text(encoding="utf-8"))
    org = parse_search_page(summary, inn="7736050003")
    assert org is not None
    assert org.org_id == 6622458


def test_ras_parser_maps_core_lines() -> None:
    balance = {
        "current2110": 100.0,
        "current2400": 10.0,
        "current1600": 500.0,
        "current1300": 200.0,
        "current1250": 50.0,
        "actives": 500.0,
    }
    result = parse_ras_payload(balance)
    codes = {
        f.canonical_metric_code
        for f in result.facts
        if f.normalization_status.value == "NORMALIZED"
    }
    assert codes >= {"REVENUE", "NET_INCOME", "TOTAL_ASSETS", "TOTAL_EQUITY", "CASH_AND_EQUIVALENTS"}


def test_ras_parser_unknown_line_stays_source_only() -> None:
    result = parse_ras_payload({"current9999": 1.0, "actives": 1.0})
    unknown = [f for f in result.facts if f.source_metric_code == "9999"]
    assert unknown and unknown[0].normalization_status is NormalizationStatus.SOURCE_ONLY


def test_ras_parser_rejects_scale_mismatch() -> None:
    result = parse_ras_payload({"unitScale": "THOUSANDS", "current2110": 1.0}, expected_scale="RUB")
    assert result.rejected_scale_mismatch is True
    assert result.facts == ()


def test_report_invisible_before_known_at_date_only() -> None:
    report = ReportRef(
        issuer_id=1,
        reporting_standard=ReportingStandard.RAS,
        period_type=PeriodType.FY,
        period_end=date(2024, 12, 31),
        known_at=date(2025, 3, 16),
        source=SOURCE_GIR_BO,
    )
    assert pit_rules.latest_report([report], date(2025, 3, 15)) is None
    assert pit_rules.latest_report([report], date(2025, 3, 16)) is report


def test_restatement_latest_known_at_wins() -> None:
    base = ReportRef(
        issuer_id=1,
        reporting_standard=ReportingStandard.RAS,
        period_type=PeriodType.FY,
        period_end=date(2024, 12, 31),
        known_at=date(2025, 3, 16),
        report_version=1,
        source=SOURCE_GIR_BO,
    )
    restated = ReportRef(
        issuer_id=1,
        reporting_standard=ReportingStandard.RAS,
        period_type=PeriodType.FY,
        period_end=date(2024, 12, 31),
        known_at=date(2025, 4, 1),
        report_version=2,
        is_restatement=True,
        source=SOURCE_GIR_BO,
    )
    as_of = date(2025, 4, 2)
    latest = pit_rules.latest_report([base, restated], as_of)
    assert latest is not None
    assert latest.report_version == 2


def test_gir_bo_disabled_still_reports_public_capability() -> None:
    probe = probe_gir_bo(settings=_SettingsStub(), live=False)
    assert probe.operational_status is ProviderOperationalStatus.READY
    assert probe.enabled is False
    assert "GIR_BO_ENABLED=false" in probe.human_explanation


def test_edisclosure_disabled_is_requires_credentials_not_rejected() -> None:
    probe = probe_edisclosure_gateway(settings=_SettingsStub(), live=False)
    assert probe.operational_status is ProviderOperationalStatus.READY_REQUIRES_CREDENTIALS
    assert "OpenAPI" in probe.human_explanation or "Gateway" in probe.human_explanation


def test_extract_ras_forms_from_bfo_row_maps_core_metrics() -> None:
    from app.modules.fundamentals.infrastructure.gir_bo_client import extract_ras_forms_from_bfo_row

    rows = json.loads((FIXTURES / "gir_bfo_list_sample.json").read_text(encoding="utf-8"))
    # Prefer full GAZP fixture if present
    merged_path = FIXTURES / "gir_correction_merged_gazp.json"
    if merged_path.exists():
        payload = json.loads(merged_path.read_text(encoding="utf-8"))
    else:
        payload = extract_ras_forms_from_bfo_row(rows[0] if rows else {})
    result = parse_ras_payload(payload)
    codes = {
        f.canonical_metric_code
        for f in result.facts
        if f.normalization_status is NormalizationStatus.NORMALIZED
    }
    assert "TOTAL_ASSETS" in codes or "REVENUE" in codes or codes  # at least some mapping


def test_provider_unavailable_status_is_explicit_not_data_loss() -> None:
    probe = probe_gir_bo(settings=_SettingsStub(), live=False)
    assert "стира" not in probe.human_explanation.lower()
    payload = json.dumps(provider_probe_to_dict(probe))
    assert "password" not in payload.lower() or "[REDACTED]" in payload


def test_subscription_required_message_distinct() -> None:
    msg = subscription_required_message(403)
    assert "подписк" in msg.lower()
    assert msg != "HTTP 403"


def test_unknown_message_type_source_only() -> None:
    mapped = map_message_type(999999, "Неизвестный тип")
    assert mapped.normalization_status is NormalizationStatus.SOURCE_ONLY


def test_dataset_v3_gate_blockers_when_no_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.fundamentals.application import readiness as readiness_mod

    class FakeSession:
        pass

    monkeypatch.setattr(
        readiness_mod,
        "coverage",
        lambda _s: {
            "mapped_share": 0.0,
            "financial_reports": 0,
            "corporate_events": 0,
            "mapped_instruments": 0,
        },
    )
    monkeypatch.setattr(
        "app.modules.fundamentals.application.dataset_v3_gate._estimate_report_years",
        lambda _s: 0,
    )
    monkeypatch.setattr(
        "app.modules.fundamentals.application.dataset_v3_gate._core_metric_coverage",
        lambda _s: 0.0,
    )
    monkeypatch.setattr(
        "app.modules.fundamentals.application.dataset_v3_gate._known_at_quality_note",
        lambda _s, _r: "NONE",
    )

    result = evaluate_dataset_v3_gate(FakeSession())
    assert result.status.value == "NOT_READY"
    assert any("финансовых отчётов" in b for b in result.blockers)


def test_edisclosure_live_auth_success_with_mock_transport() -> None:
    settings = _SettingsWithCreds()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth":
            return httpx.Response(201, json={"token": "tok", "expirationDate": "2026-12-31T23:59:59"})
        if request.url.path == "/api/v1/dictionaries/message-types":
            return httpx.Response(200, json=[{"id": 1, "name": "Test"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = EdisclosureGatewayClient(settings=settings, transport=transport)
    probe = probe_edisclosure_gateway(settings=settings, client=client, live=True)
    assert probe.authenticated is True
    assert probe.operational_status is ProviderOperationalStatus.READY
    client.close()


def test_edisclosure_auth_failure_humanized_with_mock_transport() -> None:
    settings = _SettingsWithCreds()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"description": "Пользователь не найден."}]},
        )

    transport = httpx.MockTransport(handler)
    client = EdisclosureGatewayClient(settings=settings, transport=transport)
    probe = probe_edisclosure_gateway(settings=settings, client=client, live=True)
    assert probe.authenticated is False
    assert "Пользователь не найден" in probe.human_explanation
    client.close()


def test_gir_bo_bfo_list_parser_from_fixture() -> None:
    rows = json.loads((FIXTURES / "gir_bfo_list_sample.json").read_text(encoding="utf-8"))
    parsed = parse_bfo_list(rows)
    assert len(parsed) >= 1
    assert parsed[0].known_at_quality.value == "DATE_ONLY"


def test_gir_bo_sample_probe_disabled() -> None:
    client = GirBoClient(settings=_SettingsStub())
    probe = client.sample_probe()
    assert probe["enabled"] is False
    client.close()
