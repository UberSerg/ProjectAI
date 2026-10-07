"""Pure industrial profile: missing ≠ 0, banks out of scope, derived only when defensible."""

from __future__ import annotations

from datetime import date

from app.modules.fundamentals.domain.types import (
    FactRef,
    NormalizationStatus,
    PeriodType,
    ReportingStandard,
    ReportRef,
)
from app.modules.intelligence.fundamentals.peers import compute_peer_ranks, percentile_rank
from app.modules.intelligence.fundamentals.profile import (
    PriorPeriodFacts,
    build_industrial_profile,
    select_comparable_prior,
)


def _report(
    *,
    report_id: int,
    period_end: date,
    known_at: date,
    period_type: PeriodType = PeriodType.FY,
) -> ReportRef:
    return ReportRef(
        report_id=report_id,
        issuer_id=1,
        reporting_standard=ReportingStandard.RAS,
        period_type=period_type,
        period_end=period_end,
        known_at=known_at,
        source="FNS_GIR_BO",
    )


def _fact(code: str, value: float) -> FactRef:
    return FactRef(
        metric_code=code,
        value=value,
        normalization_status=NormalizationStatus.NORMALIZED,
        currency="RUB",
        unit_scale="THOUSANDS",
        source_metric_name=code,
        report_id=1,
    )


def test_missing_ratios_are_unknown_not_zero() -> None:
    latest = _report(
        report_id=1, period_end=date(2024, 12, 31), known_at=date(2025, 3, 20)
    )
    facts = (
        _fact("REVENUE", 1000.0),
        _fact("NET_INCOME", 100.0),
        _fact("TOTAL_ASSETS", 5000.0),
        _fact("TOTAL_EQUITY", 2000.0),
        # no debt, cash, ocf, current*
    )
    metrics, missing, limitations, status = build_industrial_profile(
        as_of=date(2025, 6, 1),
        latest=latest,
        facts=facts,
        visible_reports=(latest,),
        prior=None,
    )
    assert status == "READY"
    assert metrics["derived"]["net_margin"] == 0.1
    assert metrics["derived"]["roa"] == 0.02
    assert "debt_to_equity" in missing
    assert "current_ratio" in missing
    assert "accrual_proxy" in missing
    assert "debt_to_equity" not in metrics["derived"]
    assert 0.0 not in (
        metrics["derived"].get("debt_to_equity"),
        metrics["derived"].get("current_ratio"),
    )
    assert any("CURRENT_ASSETS" in item or "current_ratio" in item for item in missing)
    assert any("1410" in lim or "DEBT" in lim.upper() or "borrowings" in lim.lower() for lim in limitations)


def test_yoy_and_deterioration_from_prior() -> None:
    latest = _report(
        report_id=2, period_end=date(2024, 12, 31), known_at=date(2025, 3, 20)
    )
    prior_report = _report(
        report_id=1, period_end=date(2023, 12, 31), known_at=date(2024, 3, 15)
    )
    facts = (
        _fact("REVENUE", 800.0),
        _fact("NET_INCOME", 40.0),
        _fact("TOTAL_ASSETS", 5000.0),
        _fact("TOTAL_EQUITY", 2000.0),
        _fact("OPERATING_CASH_FLOW", -10.0),
    )
    prior = PriorPeriodFacts(
        report=prior_report,
        facts={"REVENUE": 1000.0, "NET_INCOME": 100.0, "TOTAL_EQUITY": 1800.0},
    )
    metrics, _missing, _lim, status = build_industrial_profile(
        as_of=date(2025, 6, 1),
        latest=latest,
        facts=facts,
        visible_reports=(prior_report, latest),
        prior=prior,
    )
    assert status == "READY"
    assert metrics["derived"]["revenue_yoy"] == -0.2
    assert "REVENUE_YOY_NEGATIVE" in metrics["flags"]["deterioration"]
    assert "NET_INCOME_YOY_NEGATIVE" in metrics["flags"]["deterioration"]
    assert "POSITIVE_NI_NEGATIVE_OCF" in metrics["flags"]["deterioration"]
    assert metrics["history"]["comparable_fy_years"] == 2


def test_select_comparable_prior_prefers_same_period_type() -> None:
    fy_old = _report(
        report_id=1, period_end=date(2022, 12, 31), known_at=date(2023, 3, 1)
    )
    h1 = _report(
        report_id=2,
        period_end=date(2023, 6, 30),
        known_at=date(2023, 8, 1),
        period_type=PeriodType.H1,
    )
    fy_new = _report(
        report_id=3, period_end=date(2023, 12, 31), known_at=date(2024, 3, 1)
    )
    prior = select_comparable_prior((fy_old, h1, fy_new), fy_new)
    assert prior is not None
    assert prior.report_id == 1


def test_peer_ranks_ignore_missing_peers() -> None:
    ranks = compute_peer_ranks(
        {"net_margin": 0.2, "roe": 0.1},
        [
            {"net_margin": 0.1},  # no roe — excluded for roe
            {"net_margin": 0.3, "roe": 0.05},
            {"roe": 0.2},
        ],
    )
    assert ranks["ranks"]["net_margin"]["peer_count"] == 2
    assert ranks["ranks"]["roe"]["peer_count"] == 2
    assert percentile_rank(0.2, [0.1, 0.3]) == 0.5


def test_zero_denominator_stays_missing() -> None:
    latest = _report(
        report_id=1, period_end=date(2024, 12, 31), known_at=date(2025, 3, 20)
    )
    facts = (
        _fact("REVENUE", 0.0),
        _fact("NET_INCOME", 10.0),
        _fact("TOTAL_ASSETS", 100.0),
        _fact("TOTAL_EQUITY", 0.0),
    )
    metrics, missing, _lim, _status = build_industrial_profile(
        as_of=date(2025, 6, 1),
        latest=latest,
        facts=facts,
        visible_reports=(latest,),
    )
    assert "net_margin" in missing
    assert "roe" in missing
    assert "net_margin" not in metrics["derived"]
