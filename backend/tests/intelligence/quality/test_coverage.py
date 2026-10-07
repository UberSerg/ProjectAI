"""Focused tests for Intelligence quality coverage + storage estimators."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.modules.intelligence.quality.coverage import (
    COVERAGE_DOMAINS,
    DomainCoverage,
    build_intelligence_coverage_summary,
    overall_status,
)
from app.modules.intelligence.quality.estimates import (
    default_scenario_table,
    estimate_intraday_rows_per_year,
    estimate_intraday_storage,
)


def test_estimate_intraday_rows_research_universe() -> None:
    # 40 × 10 × 250 = 100_000
    assert estimate_intraday_rows_per_year(40) == 100_000
    est = estimate_intraday_storage(40, years=1.0)
    assert est.rows_per_year == 100_000
    assert est.rows_total == 100_000
    assert est.total_bytes == 100_000 * (200 + 64)
    assert est.feature_snapshot_rows_per_year == 40 * 250
    assert "market.candles" in " ".join(est.assumptions)


def test_estimate_rejects_negative() -> None:
    with pytest.raises(ValueError):
        estimate_intraday_rows_per_year(-1)
    with pytest.raises(ValueError):
        estimate_intraday_storage(10, years=-0.5)


def test_default_scenario_table_shapes() -> None:
    rows = default_scenario_table()
    assert len(rows) >= 3
    assert {r["scenario"] for r in rows} >= {
        "research_equity_v1",
        "liquid_expanded",
        "cautionary_catalog",
    }


def test_overall_status_conservative() -> None:
    assert (
        overall_status(
            (
                DomainCoverage("daily", "READY"),
                DomainCoverage("intraday", "NOT_READY"),
            )
        )
        == "NOT_READY"
    )
    assert (
        overall_status(
            (
                DomainCoverage("daily", "UNKNOWN"),
                DomainCoverage("macro", "PARTIAL"),
            )
        )
        == "PARTIAL"
    )
    assert overall_status((DomainCoverage("events", "UNKNOWN"),)) == "UNKNOWN"


def test_domain_coverage_rejects_bad_status() -> None:
    with pytest.raises(ValueError):
        DomainCoverage(domain="daily", status="OK")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DomainCoverage(domain="ticks", status="READY")  # type: ignore[arg-type]


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


def _session_with_counts(mapping: dict[str, int | date | None]) -> MagicMock:
    """Route SQL fragments to canned scalars (longest key wins)."""

    session = MagicMock()
    ordered = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)

    def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:  # noqa: ARG001
        sql = str(stmt)
        for key, value in ordered:
            if key in sql:
                return _Result(value)
        return _Result(0)

    session.execute.side_effect = execute
    return session


def test_build_coverage_summary_all_domains_not_ready() -> None:
    session = _session_with_counts({})
    payload = build_intelligence_coverage_summary(session)
    assert payload["schema"] == "IntelligenceCoverageSummaryV1"
    domains = {d["domain"]: d for d in payload["domains"]}
    assert set(domains) == set(COVERAGE_DOMAINS)
    assert payload["overall_status"] == "NOT_READY"
    assert payload["production_isolation"]["persist_registry"] is False
    assert domains["intraday"]["evidence"]["storage"] == "market.candles"


def test_build_coverage_summary_partial_ready_mix() -> None:
    session = _session_with_counts(
        {
            "COUNT(DISTINCT instrument_id)": 40,
            "fundamental_snapshots WHERE status = 'READY'": 25,
            "FROM intelligence.fundamental_snapshots WHERE TRUE": 40,
            "FROM intelligence.intraday_feature_snapshots": 200,
            "FROM intelligence.knowledge_rule_evaluations": 20,
            "FROM intelligence.intelligence_events": 80,
            "FROM intelligence.source_documents": 90,
            "FROM intelligence.macro_snapshots": 10,
            "FROM intelligence.knowledge_rules": 5,
            "timeframe = '1d'": 10_000,
            "timeframe = '60m'": 5_000,
            "MAX(": date(2026, 10, 1),
        }
    )
    payload = build_intelligence_coverage_summary(session, as_of=date(2026, 10, 1))
    domains = {d["domain"]: d for d in payload["domains"]}
    assert domains["daily"]["status"] == "READY"
    assert domains["intraday"]["status"] == "READY"
    assert domains["fundamentals"]["status"] == "READY"
    assert domains["events"]["status"] == "READY"
    assert domains["macro"]["status"] == "READY"
    assert domains["knowledge"]["status"] == "READY"
    assert payload["overall_status"] == "READY"
    assert payload["as_of"] == "2026-10-01"


def test_build_coverage_summary_query_failure_unknown() -> None:
    session = MagicMock()
    session.execute.side_effect = RuntimeError("db down")
    payload = build_intelligence_coverage_summary(session)
    statuses = {d["status"] for d in payload["domains"]}
    assert statuses == {"UNKNOWN"}
    assert payload["overall_status"] == "UNKNOWN"
