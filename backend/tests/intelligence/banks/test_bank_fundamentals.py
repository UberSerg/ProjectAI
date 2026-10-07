"""Bank/FI fundamentals — honest status, no industrial FNS fallback."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS as FNS_BANK_FI_SECIDS,
)
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    resolve_fns_identity,
)
from app.modules.intelligence.banks import (
    BANK_FI_SECIDS,
    build_bank_fi_fundamental_snapshot,
    is_bank_fi_secid,
    provider_status_report,
)
from app.modules.intelligence.banks.cbr_catalog import parse_cbr_reports_index_html
from app.modules.intelligence.banks.metrics import BANK_METRIC_CODES, INDUSTRIAL_RATIO_CODES
from app.modules.intelligence.banks.snapshot import assert_no_industrial_fallback


class _FakeFnsClient:
    def search_by_inn(self, inn: str):  # noqa: ANN001
        return []


CBR_REPORTS_FIXTURE = """
<html><body>
<a href="/banking_sector/credit/coinfo/f101?regnum=1481&amp;dt=2026-09-01">f101</a>
<a href="/banking_sector/credit/coinfo/f102?regnum=1481&amp;dt=2026-09-01">f102</a>
<a href="/banking_sector/credit/coinfo/f123?regnum=1481&amp;dt=2025-01-01">f123</a>
<a href="/banking_sector/credit/coinfo/f135?regnum=1481&amp;dt=2021-04-01">f135</a>
</body></html>
"""


def test_bank_secid_set_matches_fns_hard_deny() -> None:
    assert BANK_FI_SECIDS == FNS_BANK_FI_SECIDS
    assert is_bank_fi_secid("SBER")
    assert is_bank_fi_secid("sber")
    assert not is_bank_fi_secid("LKOH")


def test_fns_identity_still_hard_denies_banks() -> None:
    resolution = resolve_fns_identity(_FakeFnsClient(), inn="7707083893", secid="SBER")
    assert resolution.support_status == "NOT_SUPPORTED_BY_FNS_RAS_V1"
    assert resolution.reason == "BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1"


def test_provider_registry_has_honest_statuses() -> None:
    report = provider_status_report()
    assert report["overall_status"] in {"PARTIAL", "NOT_AVAILABLE"}
    assert report["industrial_fns_fallback"] == "FORBIDDEN"
    by_id = {p["provider_id"]: p for p in report["providers"]}
    assert by_id["FNS_GIR_BO_INDUSTRIAL_RAS"]["status"] == "NOT_AVAILABLE"
    assert by_id["CBR_CREDIT_ORG_FORMS_HTML"]["status"] == "PARTIAL"
    assert by_id["CBR_RATINGS_PORTAL"]["status"] == "REJECTED"
    assert by_id["ISSUER_IR_IFRS"]["status"] == "RESEARCH_ONLY"
    assert "SBER" in report["curated_cbr_credit_orgs"]


def test_cbr_catalog_parser_coverage_only() -> None:
    index = parse_cbr_reports_index_html(
        CBR_REPORTS_FIXTURE,
        ogrn="1027700132195",
    )
    assert index.status == "PARTIAL"
    assert index.regnum == "1481"
    forms = {f.form: f for f in index.forms}
    assert forms["f101"].max_dt == "2026-09-01"
    assert forms["f102"].count == 1
    assert "metrics_not_extracted" in index.limitations


def test_sber_snapshot_bank_semantics_without_industrial_metrics() -> None:
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        instrument_id=42,
        as_of=date(2026, 10, 1),
        cbr_html_fixture=CBR_REPORTS_FIXTURE,
        # Attempted industrial payload must be rejected, not accepted.
        bank_metrics={
            "REVENUE": 1_000_000,
            "EBITDA": 500_000,
            "TOTAL_DEBT": 100,
            "NET_PROFIT": 12.5,  # bank candidate — still not from a ready feed
        },
    )
    assert snap.issuer_kind == "BANK_FI"
    assert snap.status in {"PARTIAL", "NOT_AVAILABLE"}
    assert "REVENUE" not in snap.metrics
    assert "EBITDA" not in snap.metrics
    assert "TOTAL_DEBT" not in snap.metrics
    assert snap.metrics.get("NET_PROFIT") == 12.5
    assert set(INDUSTRIAL_RATIO_CODES).isdisjoint(snap.metrics)
    assert "bank_fi_industrial_fns_unsupported" in snap.limitations
    assert "INDUSTRIAL_FNS_FALLBACK_FORBIDDEN" in snap.limitations
    assert_no_industrial_fallback(snap)
    payload = snap.to_dict()
    assert payload["issuer_kind"] == "BANK_FI"
    assert any(f.get("fact") == "cbr_form_catalog" for f in payload["facts_used"])


def test_sber_without_metrics_is_partial_or_not_available() -> None:
    snap = build_bank_fi_fundamental_snapshot(
        secid="SBER",
        as_of=date(2026, 10, 1),
        cbr_html_fixture=CBR_REPORTS_FIXTURE,
    )
    assert snap.issuer_kind == "BANK_FI"
    assert snap.status == "PARTIAL"
    assert snap.metrics == {}
    assert set(snap.missing_metrics) == set(BANK_METRIC_CODES)
    assert_no_industrial_fallback(snap)


def test_non_bank_not_handled_as_bank_fi() -> None:
    snap = build_bank_fi_fundamental_snapshot(secid="LKOH", as_of=date(2026, 10, 1))
    assert snap.issuer_kind == "UNKNOWN"
    assert snap.status == "UNKNOWN"
    assert snap.metrics == {}


def test_assert_no_industrial_fallback_raises() -> None:
    from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1

    bad = FundamentalSnapshotV1(
        issuer_kind="BANK_FI",
        status="PARTIAL",
        metrics={"REVENUE": 1.0},
    )
    with pytest.raises(AssertionError):
        assert_no_industrial_fallback(bad)
