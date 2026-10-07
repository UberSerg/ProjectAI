"""Coverage matrix + historical vs prospective separation."""

from __future__ import annotations

from datetime import date

from app.modules.intelligence.research.constants import (
    DOMAIN_INTRADAY,
    DOMAIN_NEWS,
    FNS_EARLIEST_HONEST_KNOWN_AT,
    MODE_HISTORICAL_EVALUABLE,
    MODE_INSUFFICIENT_HISTORY,
    MODE_NOT_ELIGIBLE,
    MODE_PROSPECTIVE_ONLY,
)
from app.modules.intelligence.research.coverage import (
    DomainEvidence,
    build_coverage_matrix,
    classify_domain,
)
from app.modules.intelligence.research.service import build_research_plan

AS_OF = date(2026, 10, 7)


def test_news_defaults_to_prospective_only() -> None:
    matrix = build_coverage_matrix(as_of=AS_OF)
    assert DOMAIN_NEWS in matrix["prospective_only_domains"]
    assert matrix["domain_evaluation_modes"][DOMAIN_NEWS] == MODE_PROSPECTIVE_ONLY
    assert matrix["is_dataset_v5"] is False
    assert "do not backdate" in matrix["news_policy"].lower() or "backdate" in matrix["news_policy"]


def test_architectural_priors_base_historical() -> None:
    matrix = build_coverage_matrix(as_of=AS_OF)
    by_pack = {row["pack"]: row for row in matrix["packs"]}
    assert by_pack["BASE"]["evaluation_mode"] == MODE_HISTORICAL_EVALUABLE
    assert by_pack["BASE"]["historical_eligible"] is True
    assert by_pack["BASE"]["earliest_honest_known_at"] is not None


def test_intraday_without_history_blocks_pack() -> None:
    matrix = build_coverage_matrix(as_of=AS_OF)
    by_pack = {row["pack"]: row for row in matrix["packs"]}
    assert by_pack["BASE+INTRADAY"]["evaluation_mode"] == MODE_NOT_ELIGIBLE
    assert by_pack["INTELLIGENCE_FULL"]["evaluation_mode"] == MODE_NOT_ELIGIBLE
    assert "BASE" in matrix["historical_evaluable_packs"]
    assert "BASE+INTRADAY" not in matrix["historical_evaluable_packs"]


def test_rich_fundamental_earliest_known_at() -> None:
    matrix = build_coverage_matrix(as_of=AS_OF)
    fund = matrix["domains"]["rich_fundamental"]
    assert fund["earliest_honest_known_at"] == FNS_EARLIEST_HONEST_KNOWN_AT.isoformat()
    by_pack = {row["pack"]: row for row in matrix["packs"]}
    assert by_pack["BASE+RICH_FUNDAMENTAL"]["evaluation_mode"] == MODE_HISTORICAL_EVALUABLE


def test_short_intraday_history_is_insufficient_not_giant_oos() -> None:
    overrides = {
        DOMAIN_INTRADAY: DomainEvidence(
            domain=DOMAIN_INTRADAY,
            earliest_honest_known_at=date(2026, 9, 1),
            latest_known_at=AS_OF,
            row_count=50,
            known_at_quality="HONEST_HISTORICAL",
            status="PARTIAL",
            limitations=("short_backfill_only",),
        )
    }
    matrix = build_coverage_matrix(as_of=AS_OF, domain_overrides=overrides)
    by_pack = {row["pack"]: row for row in matrix["packs"]}
    assert by_pack["BASE+INTRADAY"]["evaluation_mode"] == MODE_INSUFFICIENT_HISTORY
    assert "BASE+INTRADAY" in matrix["insufficient_history_packs"]
    assert by_pack["BASE+INTRADAY"]["earliest_honest_known_at"] == "2026-09-01"


def test_classify_news_observed_today() -> None:
    evidence = DomainEvidence(
        domain=DOMAIN_NEWS,
        earliest_honest_known_at=AS_OF,
        known_at_quality="OBSERVED_TODAY",
        status="NOT_READY",
    )
    assert classify_domain(evidence, as_of=AS_OF) == MODE_PROSPECTIVE_ONLY


def test_research_plan_stops_at_coverage_when_needed() -> None:
    plan = build_research_plan(as_of=AS_OF)
    assert plan["experiment_name"] == "Intelligence Research V1"
    assert plan["is_dataset_v5"] is False
    assert plan["candidate_promotion"] is False
    assert plan["retunes_v4"] is False
    assert "coverage_matrix" in plan
    assert plan["next_step"] in {"run_focused_oos", "stop_at_coverage_matrix"}
    # With priors, BASE (+ fund/event/macro) are historical → focused OOS allowed.
    assert "BASE" in plan["coverage_matrix"]["historical_evaluable_packs"]
    assert plan["experiment"]["identity"]["is_dataset_v5"] is False


def test_override_makes_full_pack_historical() -> None:
    overrides = {
        DOMAIN_INTRADAY: DomainEvidence(
            domain=DOMAIN_INTRADAY,
            earliest_honest_known_at=date(2020, 1, 1),
            latest_known_at=AS_OF,
            row_count=50_000,
            known_at_quality="HONEST_HISTORICAL",
            status="READY",
        )
    }
    matrix = build_coverage_matrix(as_of=AS_OF, domain_overrides=overrides)
    by_pack = {row["pack"]: row for row in matrix["packs"]}
    assert by_pack["BASE+INTRADAY"]["evaluation_mode"] == MODE_HISTORICAL_EVALUABLE
    assert by_pack["INTELLIGENCE_FULL"]["evaluation_mode"] == MODE_HISTORICAL_EVALUABLE
    assert by_pack["INTELLIGENCE_FULL"]["historical_eligible"] is True
