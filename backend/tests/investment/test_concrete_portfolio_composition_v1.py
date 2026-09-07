"""Concrete Portfolio Composition V1 tests."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.modules.investment.domain.composition_config import CONCRETE_CANDIDATE_VERSION, CompositionConfig
from app.modules.investment.domain.equity_composition import (
    EquityCandidateRow,
    select_equity_composition,
)
from app.modules.investment.domain.fixed_income_composition import (
    FixedIncomeCandidateRow,
    select_fixed_income_composition,
)
from app.modules.investment.domain.portfolio_candidate import diff_candidates


def _eq(symbol: str, rank: int, price: str = "100", lot: int = 1) -> EquityCandidateRow:
    return EquityCandidateRow(
        instrument_id=rank,
        symbol=symbol,
        display_name=symbol,
        rank=rank,
        signal_value=0.1,
        signal_semantic="EXPECTED_RETURN",
        reference_price=Decimal(price),
        lot_size=lot,
        model_name="prediction_ml_candidate",
        model_version="v0",
        batch_id=1,
        as_of="2026-09-03",
    )


def _fi(symbol: str, *, bond_type: str = "Government", support: str = "SUPPORTED") -> FixedIncomeCandidateRow:
    return FixedIncomeCandidateRow(
        instrument_id=hash(symbol) % 10_000,
        symbol=symbol,
        display_name=symbol,
        bond_type=bond_type,
        support_status=support,
        credit_status="UNKNOWN",
        liquidity_status="MEDIUM",
        investment_eligibility="RESEARCH_ONLY",
        lot_size=1,
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("100"),
        accrued_interest=Decimal("10"),
        dirty_price_per_bond=Decimal("1010"),
        coupon_rate=7.5,
        maturity_date="2030-01-01",
        yield_value=None,
        cashflow_count=10,
        risk_flags=(),
        warnings=(),
    )


def test_equity_deterministic_and_no_synthetic_sleeve() -> None:
    rows = [_eq("SBER", 1), _eq("LKOH", 2, price="5000"), _eq("GAZP", 3), _eq("ROSN", 4), _eq("T", 5)]
    gate = {r.symbol: "RESEARCH_ONLY" for r in rows}
    a = select_equity_composition(
        rows, sleeve_weight=0.25, capital=Decimal("100000"), gate_status_by_symbol=gate
    )
    b = select_equity_composition(
        rows, sleeve_weight=0.25, capital=Decimal("100000"), gate_status_by_symbol=gate
    )
    assert [r.symbol for r in a.selected] == [r.symbol for r in b.selected]
    assert "EQUITY_SLEEVE" not in [r.symbol for r in a.selected]
    assert a.equal_weight <= 0.15 + 1e-9


def test_equity_blocked_excluded() -> None:
    rows = [_eq("SBER", 1), _eq("BAD", 2)]
    gate = {"SBER": "RESEARCH_ONLY", "BAD": "BLOCKED"}
    sel = select_equity_composition(
        rows, sleeve_weight=0.2, capital=Decimal("100000"), gate_status_by_symbol=gate
    )
    assert all(r.symbol != "BAD" for r in sel.selected)
    assert any(r["symbol"] == "BAD" for r in sel.rejected)


def test_fi_prefers_government_not_max_ytm_and_no_synthetic() -> None:
    rows = [
        _fi("CORP_HI", bond_type="Corporate"),
        _fi("OFZ_A", bond_type="Government"),
        _fi("OFZ_B", bond_type="Government"),
        _fi("UNSUPPORTED", support="UNSUPPORTED"),
    ]
    # Give corporate a fake high yield hint via opportunity only — selection uses quality order.
    gate = {r.symbol: "RESEARCH_ONLY" for r in rows}
    sel = select_fixed_income_composition(
        rows,
        sleeve_weight=0.3,
        capital=Decimal("100000"),
        gate_status_by_symbol=gate,
        config=CompositionConfig(max_fixed_income_positions=2),
    )
    assert "FI_SLEEVE" not in [r.symbol for r in sel.selected]
    assert "UNSUPPORTED" not in [r.symbol for r in sel.selected]
    assert all(r.bond_type == "Government" for r in sel.selected)


def test_ticker_diff_lots() -> None:
    prev = {
        "candidate_id": "a",
        "allocation": {
            "equity": {"target_weight": 0.25},
            "fixed_income": {"target_weight": 0.65},
            "cash": {"target_weight": 0.1},
        },
        "positions": [{"symbol": "SBER", "lots": 3, "risk_status": "RESEARCH_ONLY"}],
        "cash": {"total_cash_rub": "10000"},
        "benchmark": {"cbr_hurdle_annual": 0.14},
    }
    cur = {
        "candidate_id": "b",
        "allocation": {
            "equity": {"target_weight": 0.25},
            "fixed_income": {"target_weight": 0.65},
            "cash": {"target_weight": 0.1},
        },
        "positions": [
            {"symbol": "SBER", "lots": 2, "risk_status": "RESEARCH_ONLY"},
            {"symbol": "OFZ", "lots": 10, "risk_status": "RESEARCH_ONLY"},
        ],
        "cash": {"total_cash_rub": "12000"},
        "benchmark": {"cbr_hurdle_annual": 0.14},
    }
    diff = diff_candidates(prev, cur)
    kinds = {c["kind"] for c in diff["changes"]}
    assert "lots_changed" in kinds
    assert "position_added" in kinds
    assert "cash_changed" in kinds


@patch("app.modules.investment.application.portfolio_candidate_service.compose_instrument_selections")
@patch("app.modules.investment.application.portfolio_candidate_service.run_investment_decision")
def test_build_skips_synthetic_sleeves(mock_decide, mock_compose) -> None:
    from app.modules.investment.application.portfolio_candidate_service import build_portfolio_candidate
    from app.modules.investment.domain.equity_composition import EquitySelectionResult
    from app.modules.investment.domain.fixed_income_composition import FixedIncomeSelectionResult

    mock_decide.return_value = {
        "as_of": "2026-09-03",
        "decision": {
            "equity_weight": 0.25,
            "fixed_income_weight": 0.65,
            "cash_weight": 0.1,
            "explanations": ["test"],
            "warnings": [],
        },
        "equity_confidence": {"confidence_level": "UNKNOWN", "reason_ru": "n=0", "sample_size": 0},
        "calibration": {"calibration_status": "INSUFFICIENT_SAMPLE", "sample_size": 0},
        "cbr_hurdle_annual": 0.14,
        "mode": "test",
    }
    eq_row = _eq("SBER", 1, price="300", lot=10)
    fi_row = _fi("SU26207RMFS9")
    mock_compose.return_value = {
        "equity": EquitySelectionResult(
            selected=(eq_row,),
            rejected=(),
            available_count=1,
            after_gate_count=1,
            equal_weight=0.15,
            sleeve_weight=0.25,
            provenance={},
        ),
        "fixed_income": FixedIncomeSelectionResult(
            selected=(fi_row,),
            rejected=(),
            available_count=1,
            after_filters_count=1,
            equal_weight=0.15,
            sleeve_weight=0.65,
            provenance={},
        ),
        "equity_meta": {"status": "OK", "as_of": "2026-09-03"},
        "fi_meta": {"status": "OK"},
        "as_of": "2026-09-03",
        "pre_gate": {"equity": {}, "fixed_income": {}},
    }
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = False
    candidate = build_portfolio_candidate(session, persist=False)
    assert candidate["version"] == CONCRETE_CANDIDATE_VERSION
    symbols = [p["symbol"] for p in candidate["positions"]]
    assert "EQUITY_SLEEVE" not in symbols
    assert "FI_SLEEVE" not in symbols
    assert "SBER" in symbols or "SU26207RMFS9" in symbols
    assert float(candidate["money"]["ending_preview_cash"]) >= 0
    assert candidate["summary"]["executable_count"] == 0 or all(
        not p["executable"] or p["risk_status"] in {"APPROVED", "APPROVED_WITH_WARNINGS"}
        for p in candidate["positions"]
    )
