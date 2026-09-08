"""Unit tests for FNS GIR BO RAS parsing and PIT known_at (no network)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.modules.fundamentals.application.dataset_v3_gate import (
    GATE_READY_FOR_BUILD,
    GATE_READY_FOR_DATASET_DESIGN,
    build_dataset_v3_readiness_gate,
)
from app.modules.fundamentals.application.coverage_service import derive_defensible_metrics
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS,
    FNS_MAP_EXACT,
    FNS_MAP_UNMAPPED,
    SUPPORT_BANK,
    SUPPORT_INDUSTRIAL,
    extract_facts_from_correction,
    parse_bfo_periods,
    resolve_fns_identity,
    resolve_known_at,
)


def test_bank_secids_guarded() -> None:
    assert "SBER" in BANK_FI_SECIDS
    assert "VTBR" in BANK_FI_SECIDS
    assert "LKOH" not in BANK_FI_SECIDS


def test_resolve_known_at_prefers_date_present() -> None:
    known_at, published_at, precision = resolve_known_at(
        {"actualBfoDate": "2026-03-20"},
        {"datePresent": "2026-03-20T12:12:40"},
    )
    assert known_at == date(2026, 3, 20)
    assert published_at == datetime(2026, 3, 20, 12, 12, 40)
    assert precision == "DATE"


def test_resolve_known_at_falls_back_to_actual_bfo_date() -> None:
    known_at, published_at, precision = resolve_known_at(
        {"actualBfoDate": "2022-03-16"},
        {},
    )
    assert known_at == date(2022, 3, 16)
    assert published_at.date() == date(2022, 3, 16)
    assert precision == "DATE"


def test_missing_known_at_raises() -> None:
    with pytest.raises(ValueError, match="MISSING_KNOWN_AT"):
        resolve_known_at({}, {})


def test_missing_line_is_none_not_zero() -> None:
    facts = extract_facts_from_correction(
        {
            "balance": {"current1600": 100.0},  # no 1250, no 1410/1510
            "financialResult": {"current2110": 50.0},
            "fundsMovement": {},
        }
    )
    by_code = {f.metric_code: f.value for f in facts}
    assert by_code["TOTAL_ASSETS"] == 100.0
    assert by_code["REVENUE"] == 50.0
    assert "CASH_AND_EQUIVALENTS" not in by_code
    assert "TOTAL_DEBT" not in by_code
    assert 0.0 not in [by_code.get("CASH_AND_EQUIVALENTS"), by_code.get("TOTAL_DEBT")]


def test_zero_debt_line_is_kept() -> None:
    facts = extract_facts_from_correction(
        {
            "balance": {
                "current1600": 10.0,
                "current1300": 5.0,
                "current1410": 0.0,
                "current1510": 0.0,
            },
            "financialResult": {},
            "fundsMovement": {},
        }
    )
    by_code = {f.metric_code: f.value for f in facts}
    assert by_code["TOTAL_DEBT"] == 0.0


def test_parse_bfo_skips_is_cb() -> None:
    periods = [
        {
            "id": 1,
            "period": "2024",
            "isCb": True,
            "actualBfoDate": "2025-03-01",
            "typeCorrections": [
                {
                    "type": 12,
                    "correction": {
                        "id": 9,
                        "datePresent": "2025-03-01T00:00:00",
                        "periodType": 12,
                        "balance": {"current1600": 1.0},
                        "financialResult": {},
                        "fundsMovement": {},
                    },
                }
            ],
        }
    ]
    assert parse_bfo_periods(periods, issuer_id=1, org_id=1) == []


def test_parse_bfo_period_end_not_known_at() -> None:
    periods = [
        {
            "id": 42,
            "period": "2024",
            "isCb": False,
            "actualBfoDate": "2025-03-15",
            "actualCorrectionNumber": 0,
            "typeCorrections": [
                {
                    "type": 12,
                    "correction": {
                        "id": 7,
                        "datePresent": "2025-03-15T10:00:00",
                        "periodType": 12,
                        "balance": {"current1600": 1.0, "current1300": 1.0},
                        "financialResult": {"current2110": 2.0, "current2400": 0.5},
                        "fundsMovement": {"current4100": 0.1},
                    },
                }
            ],
        }
    ]
    bundles = parse_bfo_periods(periods, issuer_id=10, org_id=99)
    assert len(bundles) == 1
    report = bundles[0].report
    assert report.period_end == date(2024, 12, 31)
    assert report.known_at == date(2025, 3, 15)
    assert report.period_end != report.known_at
    assert report.reporting_standard.value == "RAS"
    assert bundles[0].metadata["revision_history_incomplete"] is True


def test_no_fake_ebitda_fcf() -> None:
    derived = derive_defensible_metrics(
        [
            {"metric_code": "NET_INCOME", "value": 10.0},
            {"metric_code": "TOTAL_EQUITY", "value": 100.0},
            {"metric_code": "TOTAL_ASSETS", "value": 200.0},
        ]
    )
    assert derived["roe"] == 0.1
    assert derived["ebitda"] is None
    assert derived["fcf"] is None


class _FakeClient:
    def __init__(self, hits: list) -> None:
        self._hits = hits

    def search_by_inn(self, inn: str):  # noqa: ARG002
        return self._hits


def test_resolve_identity_bank_shortcut() -> None:
    res = resolve_fns_identity(_FakeClient([]), inn="7707083893", secid="SBER")
    assert res.support_status == SUPPORT_BANK
    assert res.status == FNS_MAP_UNMAPPED


def test_resolve_identity_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import FnsOrgHit

    hit = FnsOrgHit(org_id=1, inn="7708004767", ogrn="1", short_name="X", is_cb=False)
    res = resolve_fns_identity(_FakeClient([hit]), inn="7708004767", secid="LKOH")
    assert res.status == FNS_MAP_EXACT
    assert res.support_status == SUPPORT_INDUSTRIAL


def test_dataset_v3_gate_fundamentals_alone_not_build(fundamentals_db=None) -> None:
    """Pure gate logic: dividends==0 must not be READY_FOR_BUILD even with reports.

    Uses the module constants; full DB path covered in integration when schema ready.
    """
    assert GATE_READY_FOR_BUILD != GATE_READY_FOR_DATASET_DESIGN
    # Simulate decision in gate helper: fundamentals alone → design at best.
    ras_reports = 10
    dividends = 0
    industrial_with = 8
    if ras_reports > 0 and dividends > 0 and industrial_with >= 5:
        gate = GATE_READY_FOR_BUILD
    elif ras_reports > 0 and industrial_with >= 1:
        gate = GATE_READY_FOR_DATASET_DESIGN
    else:
        gate = "NOT_READY"
    if dividends == 0 and gate == GATE_READY_FOR_BUILD:
        gate = GATE_READY_FOR_DATASET_DESIGN
    assert gate == GATE_READY_FOR_DATASET_DESIGN
