"""Unit tests for Portfolio Allocation Explanation V1."""

from __future__ import annotations

from decimal import Decimal

from app.modules.investment.domain.portfolio_allocation_explanation import (
    build_portfolio_allocation_explanation,
    required_names_for_sleeve,
)


def test_required_names_for_65pct_at_15pct_cap() -> None:
    assert required_names_for_sleeve(sleeve_weight=0.65, max_single_position_weight=0.15) == 5
    assert required_names_for_sleeve(sleeve_weight=0.30, max_single_position_weight=0.15) == 2
    assert required_names_for_sleeve(sleeve_weight=0.0, max_single_position_weight=0.15) == 0


def test_fi_constrained_100k_scenario_explanation() -> None:
    """Live-like: target FI 65%, only 2 eligible → effective 30%, cash rises via constraints."""
    expl = build_portfolio_allocation_explanation(
        capital=Decimal("100000"),
        target_equity_weight=0.25,
        target_fi_weight=0.65,
        target_cash_weight=0.10,
        effective_equity_weight=0.25,
        effective_fi_weight=0.30,
        actual_equity_rub=Decimal("23200.89"),
        actual_fi_rub=Decimal("29851.30"),
        total_cash_rub=Decimal("46947.81"),
        strategic_cash_rub=Decimal("10000.00"),
        equity_selected_count=4,
        fi_selected_count=2,
        fi_eligible_count=2,
        fi_available_count=21,
        max_single_position_weight=0.15,
        confidence_level="UNKNOWN",
        calibration_status="INSUFFICIENT_SAMPLE",
        sample_size=0,
        confidence_unknown=True,
    )

    assert expl["version"] == "PORTFOLIO_ALLOCATION_EXPLANATION_V1"
    assert expl["target_allocation"]["fixed_income_weight"] == 0.65
    assert expl["constraints"]["fi_required_names_for_target"] == 5
    assert expl["constraints"]["fi_eligible_count"] == 2
    assert expl["constraints"]["fi_max_safe_weight"] == 0.30

    cash = expl["cash_breakdown"]
    assert Decimal(cash["strategic_cash_rub"]) == Decimal("10000.00")
    # ~35k constraint + ~1.9k lot ≈ residual over strategic
    assert Decimal(cash["constraint_unallocated_rub"]) >= Decimal("34000")
    assert Decimal(cash["lot_rounding_rub"]) >= Decimal("1000")
    assert Decimal(cash["strategic_cash_rub"]) + Decimal(
        cash["constraint_unallocated_rub"]
    ) + Decimal(cash["lot_rounding_rub"]) == Decimal("46947.81")

    codes = {m["code"] for m in expl["messages"]}
    assert "FI_CONCENTRATION_LIMIT" in codes
    assert "CASH_CONSTRAINT_UNALLOCATED" in codes
    assert "EQUITY_LOT_ROUNDING" in codes
    assert "EQUITY_CONFIDENCE_CAP" in codes

    fi_msg = next(m for m in expl["messages"] if m["code"] == "FI_CONCENTRATION_LIMIT")
    assert "2" in fi_msg["body_ru"]
    assert "15%" in fi_msg["body_ru"]
    assert "65%" in fi_msg["body_ru"]
    assert fi_msg["significance"] == "HIGH"


def test_equity_lot_rounding_only_when_sleeve_filled() -> None:
    expl = build_portfolio_allocation_explanation(
        capital=Decimal("100000"),
        target_equity_weight=0.25,
        target_fi_weight=0.65,
        target_cash_weight=0.10,
        effective_equity_weight=0.25,
        effective_fi_weight=0.65,
        actual_equity_rub=Decimal("24000"),
        actual_fi_rub=Decimal("64000"),
        total_cash_rub=Decimal("12000"),
        strategic_cash_rub=Decimal("10000"),
        equity_selected_count=4,
        fi_selected_count=5,
        fi_eligible_count=5,
        fi_available_count=21,
        max_single_position_weight=0.15,
        confidence_level="MEDIUM",
        calibration_status="OK",
        sample_size=40,
        confidence_unknown=False,
    )
    codes = {m["code"] for m in expl["messages"]}
    assert "FI_CONCENTRATION_LIMIT" not in codes
    assert "EQUITY_LOT_ROUNDING" in codes
    assert "EQUITY_CONFIDENCE_CAP" not in codes


def test_no_fake_fi_message_when_fully_filled() -> None:
    expl = build_portfolio_allocation_explanation(
        capital=Decimal("100000"),
        target_equity_weight=0.20,
        target_fi_weight=0.70,
        target_cash_weight=0.10,
        effective_equity_weight=0.20,
        effective_fi_weight=0.70,
        actual_equity_rub=Decimal("20000"),
        actual_fi_rub=Decimal("70000"),
        total_cash_rub=Decimal("10000"),
        strategic_cash_rub=Decimal("10000"),
        equity_selected_count=4,
        fi_selected_count=5,
        fi_eligible_count=5,
        fi_available_count=21,
        max_single_position_weight=0.15,
        confidence_level="HIGH",
        calibration_status="OK",
        sample_size=100,
        confidence_unknown=False,
    )
    assert expl["messages"] == [] or all(
        m["code"] not in {"FI_CONCENTRATION_LIMIT", "CASH_CONSTRAINT_UNALLOCATED"}
        for m in expl["messages"]
    )
    assert Decimal(expl["cash_breakdown"]["constraint_unallocated_rub"]) == Decimal("0.00")
