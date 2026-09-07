"""Portfolio Candidate V1 domain and orchestration tests."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.modules.investment.application.portfolio_candidate_service import (
    build_portfolio_candidate,
)
from app.modules.investment.domain.allocation import (
    AllocatedPosition,
    AllocationResult,
    AssetSleeve,
)
from app.modules.investment.domain.portfolio_candidate import (
    classify_candidate_status,
    diff_candidates,
    human_confidence_label,
)


def test_human_confidence_unknown_is_plain_russian() -> None:
    assert human_confidence_label("UNKNOWN") == "Недостаточно данных"
    assert human_confidence_label("INSUFFICIENT_SAMPLE") == "Недостаточно данных"


def test_classify_statuses() -> None:
    assert (
        classify_candidate_status(
            gate_status="APPROVED", has_positions=True, stale=False, insufficient=False
        ).value
        == "READY_FOR_RESEARCH"
    )
    assert (
        classify_candidate_status(
            gate_status="BLOCKED", has_positions=False, stale=False, insufficient=False
        ).value
        == "BLOCKED_BY_RISK"
    )
    assert (
        classify_candidate_status(
            gate_status="RESEARCH_ONLY", has_positions=True, stale=True, insufficient=False
        ).value
        == "STALE"
    )


def test_diff_first_candidate() -> None:
    diff = diff_candidates(None, {"allocation": {}})
    assert diff["has_previous"] is False
    assert "первый" in diff["summary_ru"].lower()


def test_diff_allocation_change() -> None:
    prev = {
        "candidate_id": "pc_old",
        "allocation": {
            "equity": {"target_weight": 0.3},
            "fixed_income": {"target_weight": 0.6},
            "cash": {"target_weight": 0.1},
        },
        "positions": [{"symbol": "A"}],
        "benchmark": {"cbr_hurdle_annual": 0.18},
    }
    cur = {
        "candidate_id": "pc_new",
        "allocation": {
            "equity": {"target_weight": 0.25},
            "fixed_income": {"target_weight": 0.65},
            "cash": {"target_weight": 0.1},
        },
        "positions": [{"symbol": "B"}],
        "benchmark": {"cbr_hurdle_annual": 0.18},
    }
    diff = diff_candidates(prev, cur)
    assert diff["has_previous"] is True
    texts = " ".join(c["text_ru"] for c in diff["changes"])
    assert "25%" in texts
    assert "исключена" in texts or "A" in texts


def _decision_pack(**overrides):
    base = {
        "as_of": "2026-09-05",
        "capital": "100000",
        "cbr_hurdle_annual": 0.18,
        "hurdle_1y": 0.18,
        "hurdle_20d": 0.01,
        "mode": "RISK_OPPORTUNITY_ENGINE_V0",
        "equity_opportunity": {"expected_excess_return": 0.0, "confidence_level": "UNKNOWN"},
        "fixed_income_opportunity": {
            "expected_yield": 0.14,
            "credit_quality": "UNKNOWN",
            "liquidity": "MEDIUM",
            "support_status": "SUPPORTED",
        },
        "cash_opportunity": {"annual_rate": 0.18},
        "calibration": {
            "sample_size": 0,
            "calibration_status": "INSUFFICIENT_SAMPLE",
            "uncertainty_note": "мало данных",
            "buckets": [],
            "limitations": [],
        },
        "equity_confidence": {
            "confidence_level": "UNKNOWN",
            "reason_ru": "Недостаточно зрелых прогнозов",
            "sample_size": 0,
            "calibration_status": "INSUFFICIENT_SAMPLE",
        },
        "decision": {
            "equity_weight": 0.25,
            "fixed_income_weight": 0.65,
            "cash_weight": 0.1,
            "explanations": ["Kraken ограничил акции до 25%."],
            "warnings": ["Equity confidence неизвестна"],
            "why_equity_ru": "Доля акций ограничена калибровкой.",
            "why_fixed_income_ru": "FI research sleeve.",
            "status": "RESEARCH_ONLY",
        },
        "bond_safety_reminder": "Высокая доходность может отражать риск.",
        "lots": {},
    }
    base.update(overrides)
    return base


def _risk_pack(*, fi_status="RESEARCH_ONLY", eq_status="RESEARCH_ONLY", blocked=None):
    return {
        "mode": "PORTFOLIO_RISK_GATE_V0",
        "risk_assessment": {
            "status": fi_status if fi_status == "BLOCKED" else "RESEARCH_ONLY",
            "positions": [
                {
                    "symbol": "EQUITY_SLEEVE",
                    "sleeve": "EQUITY_ALPHA",
                    "status": eq_status,
                    "explanations_ru": ["equity research"],
                    "warnings_ru": [],
                    "allowed_in_portfolio": eq_status != "BLOCKED",
                    "target_weight": 0.25,
                },
                {
                    "symbol": "FI_SLEEVE",
                    "sleeve": "FIXED_INCOME",
                    "status": fi_status,
                    "explanations_ru": (
                        ["Кредитное качество неизвестно"]
                        if fi_status != "BLOCKED"
                        else ["FI blocked"]
                    ),
                    "warnings_ru": ["credit unknown"],
                    "allowed_in_portfolio": fi_status != "BLOCKED",
                    "target_weight": 0.65,
                },
                {
                    "symbol": "CASH",
                    "sleeve": "CASH",
                    "status": "APPROVED",
                    "explanations_ru": [],
                    "warnings_ru": [],
                    "allowed_in_portfolio": True,
                    "target_weight": 0.1,
                },
            ],
            "approved": ["CASH"] if fi_status == "BLOCKED" else [],
            "approved_with_warnings": [],
            "research_only": [] if fi_status == "BLOCKED" else ["EQUITY_SLEEVE", "FI_SLEEVE"],
            "blocked": blocked or ([] if fi_status != "BLOCKED" else ["FI_SLEEVE"]),
            "insufficient_data": [],
            "warnings_ru": [],
            "summary_ru": "research gate",
        },
    }


@patch("app.modules.investment.application.portfolio_candidate_service.allocate_integer_lots")
@patch("app.modules.investment.application.portfolio_candidate_service.assess_portfolio_risk_gate")
@patch("app.modules.investment.application.portfolio_candidate_service.run_investment_decision")
def test_build_candidate_research_only_not_executable(
    mock_decide, mock_risk, mock_lots
) -> None:
    mock_decide.return_value = _decision_pack()
    mock_risk.return_value = _risk_pack()
    mock_lots.return_value = AllocationResult(
        starting_cash=Decimal("100000"),
        positions=(
            AllocatedPosition(
                symbol="EQUITY_SLEEVE",
                sleeve=AssetSleeve.EQUITY_ALPHA,
                lots=8,
                units=80,
                execution_price=Decimal("300"),
                notional=Decimal("24000"),
                fees=Decimal("12"),
                cash_used=Decimal("24012"),
            ),
            AllocatedPosition(
                symbol="FI_SLEEVE",
                sleeve=AssetSleeve.FIXED_INCOME,
                lots=65,
                units=65,
                execution_price=Decimal("980"),
                notional=Decimal("63700"),
                fees=Decimal("32"),
                cash_used=Decimal("63732"),
            ),
        ),
        fees=Decimal("44"),
        cash_remainder=Decimal("12256"),
        diagnostics=(),
    )
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = False

    candidate = build_portfolio_candidate(session, capital=Decimal("100000"), persist=False)
    assert candidate["version"] == "PORTFOLIO_CANDIDATE_V1"
    assert candidate["readiness"]["ready_for_real_money"] is False
    assert candidate["status"] in {"READY_FOR_RESEARCH", "PARTIAL", "STALE"}
    assert all(p["executable"] is False for p in candidate["positions"])
    assert float(candidate["money"]["ending_preview_cash"]) >= 0
    assert "Недостаточно данных" in candidate["decision_quality"]["equity_confidence_label_ru"]


@patch("app.modules.investment.application.portfolio_candidate_service.allocate_integer_lots")
@patch("app.modules.investment.application.portfolio_candidate_service.assess_portfolio_risk_gate")
@patch("app.modules.investment.application.portfolio_candidate_service.run_investment_decision")
def test_blocked_fi_diverts_to_cash_no_fake_fallback(
    mock_decide, mock_risk, mock_lots
) -> None:
    mock_decide.return_value = _decision_pack()
    mock_risk.return_value = _risk_pack(fi_status="BLOCKED", blocked=["FI_SLEEVE"])
    mock_lots.return_value = AllocationResult(
        starting_cash=Decimal("100000"),
        positions=(
            AllocatedPosition(
                symbol="EQUITY_SLEEVE",
                sleeve=AssetSleeve.EQUITY_ALPHA,
                lots=8,
                units=80,
                execution_price=Decimal("300"),
                notional=Decimal("24000"),
                fees=Decimal("12"),
                cash_used=Decimal("24012"),
            ),
        ),
        fees=Decimal("12"),
        cash_remainder=Decimal("75988"),
        diagnostics=(),
    )
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = False

    candidate = build_portfolio_candidate(session, persist=False)
    assert any(r["sleeve"] == "FIXED_INCOME" for r in candidate["rejected_candidates"])
    assert all(p["sleeve"] != "FIXED_INCOME" for p in candidate["positions"])
    assert candidate["allocation"]["adjusted_after_gate"]["fixed_income_weight"] == 0.0
    assert candidate["allocation"]["adjusted_after_gate"]["cash_weight"] >= 0.75
    args = mock_lots.call_args.args[0]
    assert all(c.symbol != "FI_SLEEVE" for c in args)


@patch("app.modules.investment.application.portfolio_candidate_service.allocate_integer_lots")
@patch("app.modules.investment.application.portfolio_candidate_service.assess_portfolio_risk_gate")
@patch("app.modules.investment.application.portfolio_candidate_service.run_investment_decision")
def test_all_cash_when_both_blocked(mock_decide, mock_risk, mock_lots) -> None:
    mock_decide.return_value = _decision_pack()
    mock_risk.return_value = _risk_pack(
        fi_status="BLOCKED", eq_status="BLOCKED", blocked=["FI_SLEEVE", "EQUITY_SLEEVE"]
    )
    mock_lots.return_value = AllocationResult(
        starting_cash=Decimal("100000"),
        positions=(),
        fees=Decimal("0"),
        cash_remainder=Decimal("100000"),
        diagnostics=(),
    )
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = False
    candidate = build_portfolio_candidate(session, persist=False)
    assert candidate["positions"] == []
    assert float(candidate["money"]["ending_preview_cash"]) == 100000.0
    assert "all_cash_ru" in candidate["empty_states"]
