"""Investment Data Readiness V1 — deterministic gate tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.modules.system.application.investment_data_readiness import (
    ReadinessStatus,
    build_investment_data_readiness,
)


def _scalar_side_effect(sql: str) -> int:
    sql_l = sql.lower()
    if "market.candles" in sql_l:
        return 1000
    if "technical.signals_daily" in sql_l:
        return 50
    if "analytics.relation_snapshots" in sql_l:
        return 20
    if "fundamentals.dividend_events" in sql_l:
        return 0
    if "market.corporate_actions" in sql_l:
        return 3
    if "min(known_at" in sql_l:
        return 0
    return 0


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def mappings(self):
        return self

    def first(self):
        if isinstance(self._value, dict):
            return self._value
        return None


@pytest.fixture
def mock_session():
    session = MagicMock()

    def execute(stmt):
        sql = str(stmt)
        if "MIN(known_at" in sql or "min(known_at" in sql.lower():
            return _Result({"earliest": "2022-03-15", "latest": "2025-04-01", "n": 42})
        return _Result(_scalar_side_effect(sql))

    session.execute.side_effect = execute
    return session


def test_readiness_status_enum_values():
    assert set(ReadinessStatus) == {
        ReadinessStatus.READY,
        ReadinessStatus.PARTIAL,
        ReadinessStatus.NOT_READY,
        ReadinessStatus.UNKNOWN,
    }


@patch(
    "app.modules.investment.application.enrichment_service.fi_coverage_report",
    return_value={"bond_terms": 10, "instruments_with_cashflows": 8, "pending_jobs": 0},
)
@patch(
    "app.modules.investment.application.credit_rating_provider.credit_coverage_v1",
    return_value={"verdict": "NOT_READY", "coverage": "no production provider"},
)
@patch(
    "app.modules.fundamentals.application.dataset_v3_gate.build_dataset_v3_readiness_gate",
    return_value={
        "gate": "READY_FOR_DATASET_DESIGN",
        "blockers": ["no dividend_events — gross total-return labels blocked"],
        "design_notes": ["Banks/FI remain NOT_SUPPORTED"],
        "candidate_start_date": "2022-03-01",
        "candidate_start_evidence": "probe",
        "human_summary": "Dataset V3 designable; build blocked",
    },
)
@patch(
    "app.modules.fundamentals.application.coverage_service.FundamentalCoverageService"
)
@patch(
    "app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready",
    return_value=True,
)
def test_build_investment_data_readiness_domains(
    _schema_ready,
    coverage_cls,
    _gate,
    _credit,
    _fi,
    mock_session,
):
    coverage_cls.return_value.cohort_table.return_value = {
        "industrial_with_reports": 9,
        "industrial_mapped": 12,
        "bank_unsupported": 2,
        "unmapped": 5,
    }

    report = build_investment_data_readiness(mock_session)

    assert report["version"] == "INVESTMENT_DATA_READINESS_V1"
    assert report["dataset_v2_unchanged"] is True
    codes = {d["code"]: d for d in report["domains"]}
    assert codes["market_eod"]["status"] == "READY"
    assert codes["dividends"]["status"] == "NOT_READY"
    assert codes["total_return"]["status"] == "NOT_READY"
    assert codes["fundamentals_banks"]["status"] == "NOT_READY"
    assert codes["survivorship"]["status"] == "NOT_READY"
    assert codes["fundamentals_ras"]["status"] == "PARTIAL"
    assert codes["credit"]["status"] == "NOT_READY"
    assert codes["fixed_income"]["status"] == "PARTIAL"

    gate = report["dataset_v3"]
    assert gate["overall_status"] == "PARTIAL"
    assert gate["dataset_spec_mutated"] is False
    assert gate["recommended_start_date"] == "2022-03-15"
    assert "Dividends" in " ".join(gate["blocking_domains"]) or any(
        "Dividend" in b or "дивиденд" in b.lower() or "Dividends" in b
        for b in gate["blocking_domains"]
    )
    assert "Gross Total Return" in " ".join(gate["blocking_domains"]) or any(
        "Total Return" in b for b in gate["blocking_domains"]
    )


@patch(
    "app.modules.investment.application.enrichment_service.fi_coverage_report",
    return_value={"bond_terms": 0, "instruments_with_cashflows": 0},
)
@patch(
    "app.modules.investment.application.credit_rating_provider.credit_coverage_v1",
    return_value={"verdict": "NOT_READY"},
)
@patch(
    "app.modules.fundamentals.application.dataset_v3_gate.build_dataset_v3_readiness_gate",
    return_value={
        "gate": "NOT_READY",
        "blockers": ["no RAS"],
        "design_notes": [],
        "candidate_start_date": None,
        "human_summary": "not ready",
    },
)
@patch(
    "app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready",
    return_value=False,
)
def test_dataset_v3_not_ready_when_no_fundamentals(
    _schema, _gate, _credit, _fi, mock_session
):
    report = build_investment_data_readiness(mock_session)
    assert report["dataset_v3"]["overall_status"] == "NOT_READY"
    banks = next(d for d in report["domains"] if d["code"] == "fundamentals_banks")
    assert banks["status"] == "NOT_READY"


def test_empty_dividends_never_fake_zero_ready(mock_session):
    with (
        patch(
            "app.modules.investment.application.enrichment_service.fi_coverage_report",
            return_value={},
        ),
        patch(
            "app.modules.investment.application.credit_rating_provider.credit_coverage_v1",
            return_value={"verdict": "NOT_READY"},
        ),
        patch(
            "app.modules.fundamentals.application.dataset_v3_gate.build_dataset_v3_readiness_gate",
            return_value={
                "gate": "READY_FOR_DATASET_DESIGN",
                "blockers": ["no dividend_events"],
                "design_notes": [],
                "candidate_start_date": "2022-03-01",
            },
        ),
        patch(
            "app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready",
            return_value=True,
        ),
        patch(
            "app.modules.fundamentals.application.coverage_service.FundamentalCoverageService"
        ) as cov,
    ):
        cov.return_value.cohort_table.return_value = {"industrial_with_reports": 1}
        report = build_investment_data_readiness(mock_session)
        div = next(d for d in report["domains"] if d["code"] == "dividends")
        assert div["status"] == "NOT_READY"
        assert div["evidence"]["dividend_events"] == 0
        assert report["dataset_v3"]["overall_status"] != "READY"
