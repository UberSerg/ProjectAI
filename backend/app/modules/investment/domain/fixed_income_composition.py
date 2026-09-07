"""FIXED_INCOME_COMPOSITION_V1 — deterministic bond selection (data quality first, not max YTM)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.modules.investment.domain.composition_config import (
    DEFAULT_COMPOSITION_CONFIG,
    FIXED_INCOME_COMPOSITION_VERSION,
    CompositionConfig,
)
from app.modules.investment.domain.fixed_income import calculate_bond_purchase


@dataclass(frozen=True, slots=True)
class FixedIncomeCandidateRow:
    instrument_id: int
    symbol: str
    display_name: str
    bond_type: str
    support_status: str
    credit_status: str
    liquidity_status: str
    investment_eligibility: str
    lot_size: int
    nominal: Decimal
    clean_price_percent: Decimal
    accrued_interest: Decimal
    dirty_price_per_bond: Decimal
    coupon_rate: float | None
    maturity_date: str | None
    yield_value: float | None
    cashflow_count: int
    risk_flags: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixedIncomeSelectionResult:
    selected: tuple[FixedIncomeCandidateRow, ...]
    rejected: tuple[dict[str, Any], ...]
    available_count: int
    after_filters_count: int
    equal_weight: float
    sleeve_weight: float
    provenance: dict[str, Any]


def fi_reason_ru(row: FixedIncomeCandidateRow) -> str:
    subtype = {
        "Government": "государственная",
        "Corporate": "корпоративная",
        "Municipal": "муниципальная",
    }.get(row.bond_type, row.bond_type)
    credit_note = (
        "Кредитное качество не подтверждено."
        if str(row.credit_status).upper() in {"UNKNOWN", "NOT_RATED"}
        else f"Кредитный статус: {row.credit_status}."
    )
    return (
        f"{subtype.capitalize()} облигация с support={row.support_status}, "
        f"ликвидность={row.liquidity_status}. {credit_note} "
        "Выбрана по качеству данных и пригодности лота, не по максимальной доходности."
    )


def _sort_key(row: FixedIncomeCandidateRow, *, prefer_gov: bool) -> tuple:
    support_rank = {"SUPPORTED": 0, "RESEARCH_ONLY": 1, "UNSUPPORTED": 9}.get(row.support_status, 5)
    type_rank = 0 if (prefer_gov and row.bond_type == "Government") else (1 if row.bond_type == "Government" else 2)
    liq_rank = {"HIGH": 0, "MEDIUM": 1, "UNKNOWN": 2, "LOW": 3}.get(row.liquidity_status, 4)
    maturity = row.maturity_date or "9999-99-99"
    return (support_rank, type_rank, liq_rank, -row.cashflow_count, maturity, row.symbol)


def select_fixed_income_composition(
    candidates: Sequence[FixedIncomeCandidateRow],
    *,
    sleeve_weight: float,
    capital: Decimal,
    gate_status_by_symbol: dict[str, str],
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> FixedIncomeSelectionResult:
    rejected: list[dict[str, Any]] = []
    eligible: list[FixedIncomeCandidateRow] = []

    for row in sorted(
        candidates, key=lambda r: _sort_key(r, prefer_gov=config.prefer_government_bonds)
    ):
        if row.support_status == "UNSUPPORTED":
            rejected.append(_rej(row, "UNSUPPORTED", "Unsupported bond исключён."))
            continue
        if row.dirty_price_per_bond <= 0 or row.lot_size <= 0 or row.nominal <= 0:
            rejected.append(_rej(row, "INSUFFICIENT_DATA", "Нет корректной dirty price / lot / nominal."))
            continue
        status = gate_status_by_symbol.get(row.symbol, row.investment_eligibility or "RESEARCH_ONLY")
        if status in {"BLOCKED", "INSUFFICIENT_DATA"} or row.investment_eligibility == "BLOCKED":
            rejected.append(
                _rej(row, str(status), "Исключено Risk Gate / eligibility до включения в состав.")
            )
            continue
        eligible.append(row)

    selected: list[FixedIncomeCandidateRow] = []
    min_names = max(1, math.ceil(sleeve_weight / config.max_single_position_weight - 1e-12))
    n_slots = max(0, min(config.max_fixed_income_positions, len(eligible)))
    if n_slots > 0 and n_slots < min_names:
        effective_sleeve = n_slots * config.max_single_position_weight
    else:
        effective_sleeve = sleeve_weight

    if effective_sleeve <= 0 or n_slots == 0 or capital <= 0:
        return FixedIncomeSelectionResult(
            selected=(),
            rejected=tuple(rejected[: config.max_rejected_shown]),
            available_count=len(candidates),
            after_filters_count=len(eligible),
            equal_weight=0.0,
            sleeve_weight=sleeve_weight,
            provenance=_prov(sleeve_weight, selected),
        )

    target_per = float(capital) * effective_sleeve / n_slots
    for row in eligible:
        if len(selected) >= n_slots:
            break
        if target_per < config.min_position_rub:
            break
        lot_cost = float(
            calculate_bond_purchase(
                nominal=row.nominal,
                clean_price_percent=row.clean_price_percent,
                accrued_interest_per_bond=row.accrued_interest,
                lots=1,
                lot_size=row.lot_size,
            ).cash_required
        )
        if lot_cost > target_per * 1.05:
            rejected.append(
                _rej(
                    row,
                    "SKIPPED",
                    f"Один лот (~{lot_cost:,.0f} ₽) слишком дорог для целевой доли ~{target_per:,.0f} ₽.",
                )
            )
            continue
        if lot_cost / float(capital) > config.max_single_position_weight:
            rejected.append(
                _rej(
                    row,
                    "BLOCKED",
                    f"Один лот превысил лимит концентрации {config.max_single_position_weight * 100:.0f}%.",
                )
            )
            continue
        selected.append(row)

    n = len(selected)
    eq_w = (effective_sleeve / n) if n else 0.0
    if n and eq_w > config.max_single_position_weight:
        eq_w = config.max_single_position_weight
    if n and float(capital) * eq_w < config.min_position_rub:
        max_by_min = int(float(capital) * effective_sleeve // config.min_position_rub)
        selected = selected[: max(0, max_by_min)]
        n = len(selected)
        eq_w = min((effective_sleeve / n) if n else 0.0, config.max_single_position_weight)

    selected_syms = {s.symbol for s in selected}
    for row in eligible:
        if row.symbol in selected_syms:
            continue
        if len(rejected) >= config.max_rejected_shown:
            break
        if any(r["symbol"] == row.symbol for r in rejected):
            continue
        rejected.append(_rej(row, "SKIPPED", "Не вошла в ограниченный набор FI-позиций V1."))

    return FixedIncomeSelectionResult(
        selected=tuple(selected),
        rejected=tuple(rejected[: config.max_rejected_shown]),
        available_count=len(candidates),
        after_filters_count=len(eligible),
        equal_weight=eq_w,
        sleeve_weight=sleeve_weight,
        provenance=_prov(sleeve_weight, selected),
    )


def _rej(row: FixedIncomeCandidateRow, status: str, reason: str) -> dict[str, Any]:
    ytm = f", YTM≈{row.yield_value * 100:.1f}%" if row.yield_value is not None else ""
    coupon = f"купон≈{row.coupon_rate}%" if row.coupon_rate is not None else "купон н/д"
    return {
        "symbol": row.symbol,
        "display_name": row.display_name,
        "sleeve": "FIXED_INCOME",
        "opportunity_hint": f"{row.bond_type}; {coupon}{ytm}",
        "risk_status": status,
        "reason_ru": reason,
    }


def _prov(sleeve_weight: float, selected: Sequence[FixedIncomeCandidateRow]) -> dict[str, Any]:
    return {
        "policy": FIXED_INCOME_COMPOSITION_VERSION,
        "weighting": "EQUAL_WEIGHT",
        "selection": "support→gov_preference→liquidity→cashflows→maturity→symbol",
        "sleeve_weight": sleeve_weight,
        "selected_symbols": [s.symbol for s in selected],
        "note_ru": "Не выбираем по максимальному YTM.",
    }
