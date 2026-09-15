"""Deterministic Portfolio Allocation Explanation V1.

Explains target vs actual Candidate allocation without changing investment logic.
All numbers must derive from already-computed Candidate / composition state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class AllocationExplanationMessage:
    code: str
    sleeve: str | None
    title_ru: str
    body_ru: str
    significance: str  # HIGH | MEDIUM | LOW
    metrics: dict[str, Any]


def required_names_for_sleeve(*, sleeve_weight: float, max_single_position_weight: float) -> int:
    """Minimum distinct names to fill sleeve without exceeding concentration cap."""
    if sleeve_weight <= 0 or max_single_position_weight <= 0:
        return 0
    return max(1, math.ceil(sleeve_weight / max_single_position_weight - 1e-12))


def build_portfolio_allocation_explanation(
    *,
    capital: Decimal,
    target_equity_weight: float,
    target_fi_weight: float,
    target_cash_weight: float,
    effective_equity_weight: float,
    effective_fi_weight: float,
    actual_equity_rub: Decimal,
    actual_fi_rub: Decimal,
    total_cash_rub: Decimal,
    strategic_cash_rub: Decimal,
    equity_selected_count: int,
    fi_selected_count: int,
    fi_eligible_count: int,
    fi_available_count: int,
    max_single_position_weight: float,
    confidence_level: str | None,
    calibration_status: str | None,
    sample_size: int | None,
    confidence_unknown: bool,
) -> dict[str, Any]:
    """Build investor-facing explanation payload from authoritative Candidate numbers."""
    capital = Decimal(str(capital))
    if capital <= 0:
        return {
            "version": "PORTFOLIO_ALLOCATION_EXPLANATION_V1",
            "messages": [],
            "cash_breakdown": {},
            "constraints": {},
            "target_allocation": {},
            "actual_allocation": {},
            "allocation_deltas": {},
        }

    actual_eq_w = float(actual_equity_rub / capital)
    actual_fi_w = float(actual_fi_rub / capital)
    actual_cash_w = float(total_cash_rub / capital)

    planned_invested_w = max(0.0, effective_equity_weight) + max(0.0, effective_fi_weight)
    planned_invested_rub = (capital * Decimal(str(planned_invested_w))).quantize(Decimal("0.01"))
    actual_invested_rub = (actual_equity_rub + actual_fi_rub).quantize(Decimal("0.01"))

    # Unrealized sleeve vs decision targets (before integer lots).
    unrealized_eq_w = max(0.0, target_equity_weight - effective_equity_weight)
    unrealized_fi_w = max(0.0, target_fi_weight - effective_fi_weight)
    constraint_unallocated_rub = (
        capital * Decimal(str(unrealized_eq_w + unrealized_fi_w))
    ).quantize(Decimal("0.01"))

    # Residual after strategic + constraint ≈ integer-lot shortfall (non-negative).
    lot_rounding_rub = max(
        Decimal("0"),
        (total_cash_rub - strategic_cash_rub - constraint_unallocated_rub).quantize(Decimal("0.01")),
    )

    # Cross-check: planned invested − actual invested should ≈ lot rounding.
    lot_from_invested = max(Decimal("0"), (planned_invested_rub - actual_invested_rub).quantize(Decimal("0.01")))
    # Prefer invested-gap when it reconciles within 1 RUB (authoritative lot math).
    if abs(lot_from_invested - lot_rounding_rub) <= Decimal("1.00"):
        lot_rounding_rub = lot_from_invested
        # Reconcile constraint so strategic + constraint + lot == total cash.
        constraint_unallocated_rub = max(
            Decimal("0"),
            (total_cash_rub - strategic_cash_rub - lot_rounding_rub).quantize(Decimal("0.01")),
        )

    fi_required_names = required_names_for_sleeve(
        sleeve_weight=target_fi_weight,
        max_single_position_weight=max_single_position_weight,
    )
    fi_max_safe_weight = min(
        target_fi_weight,
        fi_selected_count * max_single_position_weight if fi_selected_count else 0.0,
    )

    messages: list[AllocationExplanationMessage] = []

    # Confidence / calibration (equity target shape) — before sleeve fill messages.
    if confidence_unknown or str(confidence_level or "").upper() in {
        "UNKNOWN",
        "INSUFFICIENT_SAMPLE",
    }:
        cal = str(calibration_status or "UNKNOWN")
        n = sample_size if sample_size is not None else 0
        messages.append(
            AllocationExplanationMessage(
                code="EQUITY_CONFIDENCE_CAP",
                sleeve="EQUITY_ALPHA",
                title_ru="Доля акций ограничена качеством подтверждения модели",
                body_ru=(
                    f"План по акциям — {target_equity_weight * 100:.0f}% капитала. "
                    "Сейчас у модели недостаточно prospective observations для подтверждённой "
                    f"калибровки (статус: {cal}, наблюдений: {n}), поэтому Kraken не расширяет "
                    "акционную долю агрессивнее текущего исследовательского лимита."
                ),
                significance="MEDIUM",
                metrics={
                    "target_equity_weight": target_equity_weight,
                    "confidence_level": confidence_level,
                    "calibration_status": calibration_status,
                    "sample_size": sample_size,
                },
            )
        )

    # FI concentration / eligible instruments — main live case.
    if unrealized_fi_w >= 0.02:  # ≥2 percentage points
        messages.append(
            AllocationExplanationMessage(
                code="FI_CONCENTRATION_LIMIT",
                sleeve="FIXED_INCOME",
                title_ru=(
                    f"Облигации: {target_fi_weight * 100:.0f}% → "
                    f"{actual_fi_w * 100:.1f}%"
                ),
                body_ru=(
                    f"Kraken планировала направить {target_fi_weight * 100:.0f}% капитала в облигации, "
                    f"но сейчас требованиям стратегии соответствуют {fi_eligible_count} "
                    f"{_issues_word(fi_eligible_count)} "
                    f"(из {fi_available_count} в исследовательском FI-universe). "
                    f"Лимит концентрации — не более {max_single_position_weight * 100:.0f}% на один инструмент, "
                    f"поэтому для целевой доли нужно минимум {fi_required_names} выпусков. "
                    f"При {fi_selected_count} подходящих выпусках безопасно размещено около "
                    f"{fi_max_safe_weight * 100:.0f}% капитала "
                    f"(факт после лотов — {actual_fi_w * 100:.1f}%). "
                    "Оставшаяся сумма сохранена в Cash вместо покупки менее подходящих бумаг."
                ),
                significance="HIGH",
                metrics={
                    "target_fi_weight": target_fi_weight,
                    "effective_fi_weight": effective_fi_weight,
                    "actual_fi_weight": actual_fi_w,
                    "fi_eligible_count": fi_eligible_count,
                    "fi_available_count": fi_available_count,
                    "fi_selected_count": fi_selected_count,
                    "required_names_for_target": fi_required_names,
                    "max_single_position_weight": max_single_position_weight,
                    "max_safe_fi_weight": fi_max_safe_weight,
                    "unrealized_fi_weight": unrealized_fi_w,
                },
            )
        )

    # Cash: strategic vs constrained
    if float(constraint_unallocated_rub) / float(capital) >= 0.02:
        messages.append(
            AllocationExplanationMessage(
                code="CASH_CONSTRAINT_UNALLOCATED",
                sleeve="CASH",
                title_ru=(
                    f"Cash: {target_cash_weight * 100:.0f}% → {actual_cash_w * 100:.1f}%"
                ),
                body_ru=(
                    f"Целевой Cash политики — около {target_cash_weight * 100:.0f}% "
                    f"({_fmt_money(strategic_cash_rub)}). "
                    f"Дополнительно около {_fmt_money(constraint_unallocated_rub)} "
                    f"({float(constraint_unallocated_rub) / float(capital) * 100:.1f}%) "
                    "не размещены в рынок: целевые доли не удалось заполнить подходящими "
                    "инструментами без нарушения лимитов. Kraken не стала покупать менее "
                    "подходящие бумаги только ради полного инвестирования капитала."
                ),
                significance="HIGH",
                metrics={
                    "strategic_cash_rub": str(strategic_cash_rub),
                    "constraint_unallocated_rub": str(constraint_unallocated_rub),
                    "target_cash_weight": target_cash_weight,
                    "actual_cash_weight": actual_cash_w,
                },
            )
        )

    # Equity lot rounding (small gap after effective sleeve filled)
    eq_lot_gap_w = max(0.0, effective_equity_weight - actual_eq_w)
    if eq_lot_gap_w >= 0.005 and unrealized_eq_w < 0.01:
        messages.append(
            AllocationExplanationMessage(
                code="EQUITY_LOT_ROUNDING",
                sleeve="EQUITY_ALPHA",
                title_ru=(
                    f"Акции: {target_equity_weight * 100:.0f}% → {actual_eq_w * 100:.1f}%"
                ),
                body_ru=(
                    "Небольшая разница связана с покупкой только целых биржевых лотов. "
                    "Kraken не дробит акции и не подбирает бумаги лишь затем, чтобы "
                    "математически совпасть с целевым процентом."
                ),
                significance="LOW",
                metrics={
                    "target_equity_weight": target_equity_weight,
                    "effective_equity_weight": effective_equity_weight,
                    "actual_equity_weight": actual_eq_w,
                    "lot_gap_weight": eq_lot_gap_w,
                    "equity_selected_count": equity_selected_count,
                },
            )
        )

    if float(lot_rounding_rub) / float(capital) >= 0.005 and not any(
        m.code == "EQUITY_LOT_ROUNDING" for m in messages
    ):
        messages.append(
            AllocationExplanationMessage(
                code="LOT_ROUNDING",
                sleeve=None,
                title_ru="Остаток из‑за целых лотов",
                body_ru=(
                    f"Около {_fmt_money(lot_rounding_rub)} осталось в Cash из‑за округления "
                    "до целых биржевых лотов после выбора конкретных инструментов."
                ),
                significance="LOW",
                metrics={"lot_rounding_rub": str(lot_rounding_rub)},
            )
        )

    # Sort: HIGH → MEDIUM → LOW, keep stable order within
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    messages_sorted = sorted(messages, key=lambda m: (rank.get(m.significance, 9), m.code))

    return {
        "version": "PORTFOLIO_ALLOCATION_EXPLANATION_V1",
        "target_allocation": {
            "equity_weight": target_equity_weight,
            "fixed_income_weight": target_fi_weight,
            "cash_weight": target_cash_weight,
            "equity_rub": str((capital * Decimal(str(target_equity_weight))).quantize(Decimal("0.01"))),
            "fixed_income_rub": str(
                (capital * Decimal(str(target_fi_weight))).quantize(Decimal("0.01"))
            ),
            "cash_rub": str((capital * Decimal(str(target_cash_weight))).quantize(Decimal("0.01"))),
        },
        "actual_allocation": {
            "equity_weight": actual_eq_w,
            "fixed_income_weight": actual_fi_w,
            "cash_weight": actual_cash_w,
            "equity_rub": str(actual_equity_rub.quantize(Decimal("0.01"))),
            "fixed_income_rub": str(actual_fi_rub.quantize(Decimal("0.01"))),
            "cash_rub": str(total_cash_rub.quantize(Decimal("0.01"))),
        },
        "effective_pre_lot_allocation": {
            "equity_weight": effective_equity_weight,
            "fixed_income_weight": effective_fi_weight,
            "cash_weight": max(0.0, 1.0 - planned_invested_w),
            "note_ru": (
                "Доли после composition и лимитов концентрации, до покупки целыми лотами."
            ),
        },
        "allocation_deltas": {
            "equity_weight": actual_eq_w - target_equity_weight,
            "fixed_income_weight": actual_fi_w - target_fi_weight,
            "cash_weight": actual_cash_w - target_cash_weight,
            "equity_rub": str(
                (actual_equity_rub - capital * Decimal(str(target_equity_weight))).quantize(
                    Decimal("0.01")
                )
            ),
            "fixed_income_rub": str(
                (actual_fi_rub - capital * Decimal(str(target_fi_weight))).quantize(Decimal("0.01"))
            ),
            "cash_rub": str(
                (total_cash_rub - capital * Decimal(str(target_cash_weight))).quantize(
                    Decimal("0.01")
                )
            ),
        },
        "cash_breakdown": {
            "strategic_cash_rub": str(strategic_cash_rub.quantize(Decimal("0.01"))),
            "strategic_cash_weight": float(strategic_cash_rub / capital),
            "constraint_unallocated_rub": str(constraint_unallocated_rub),
            "constraint_unallocated_weight": float(constraint_unallocated_rub / capital),
            "lot_rounding_rub": str(lot_rounding_rub),
            "lot_rounding_weight": float(lot_rounding_rub / capital),
            "total_cash_rub": str(total_cash_rub.quantize(Decimal("0.01"))),
            "note_ru": (
                "Strategic Cash — намеренный резерв политики. "
                "Constraint / unallocated — капитал, который target хотел инвестировать, "
                "но composition/risk-лимиты не позволили. "
                "Lot rounding — остаток от целых лотов. "
                "Поле cash.lot_remainder_rub сохранено для совместимости и может включать "
                "constraint + lot rounding."
            ),
        },
        "constraints": {
            "max_single_position_weight": max_single_position_weight,
            "fi_required_names_for_target": fi_required_names,
            "fi_eligible_count": fi_eligible_count,
            "fi_available_count": fi_available_count,
            "fi_selected_count": fi_selected_count,
            "fi_max_safe_weight": fi_max_safe_weight,
            "equity_selected_count": equity_selected_count,
            "confidence_unknown": confidence_unknown,
        },
        "messages": [
            {
                "code": m.code,
                "sleeve": m.sleeve,
                "title_ru": m.title_ru,
                "body_ru": m.body_ru,
                "significance": m.significance,
                "metrics": m.metrics,
            }
            for m in messages_sorted
        ],
        "summary_ru": _summary_ru(messages_sorted),
    }


def _issues_word(n: int) -> str:
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 14:
        return "выпусков"
    if n1 == 1:
        return "выпуск"
    if 2 <= n1 <= 4:
        return "выпуска"
    return "выпусков"


def _fmt_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f} ₽".replace(",", " ")


def _summary_ru(messages: list[AllocationExplanationMessage]) -> str:
    highs = [m for m in messages if m.significance == "HIGH"]
    if not highs:
        if messages:
            return messages[0].body_ru
        return (
            "Фактический состав близок к плану Kraken. Существенных ограничений "
            "размещения капитала сейчас не видно."
        )
    return " ".join(m.body_ru for m in highs[:2])
