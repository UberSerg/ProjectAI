"""EQUITY_COMPOSITION_V1 — deterministic ticker selection over existing forward signals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.modules.investment.domain.composition_config import (
    DEFAULT_COMPOSITION_CONFIG,
    EQUITY_COMPOSITION_VERSION,
    CompositionConfig,
)
from app.modules.model_edge.config import SEMANTIC_RANKING_SCORE


@dataclass(frozen=True, slots=True)
class EquityCandidateRow:
    instrument_id: int
    symbol: str
    display_name: str
    rank: int
    signal_value: float
    signal_semantic: str
    reference_price: Decimal
    lot_size: int | None
    model_name: str
    model_version: str
    batch_id: int
    as_of: str
    lot_size_provenance: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EquitySelectionResult:
    selected: tuple[EquityCandidateRow, ...]
    rejected: tuple[dict[str, Any], ...]
    available_count: int
    after_gate_count: int
    equal_weight: float
    sleeve_weight: float
    provenance: dict[str, Any]


def equity_reason_ru(row: EquityCandidateRow, *, semantic: str) -> str:
    if semantic == SEMANTIC_RANKING_SCORE:
        return (
            f"Бумага вошла в верхнюю часть текущего рейтинга акций (rank={row.rank}) "
            "и прошла доступные проверки риска. RANKING_SCORE — не процент доходности."
        )
    return (
        f"Бумага вошла в верхнюю часть текущего списка equity-кандидатов (rank={row.rank}) "
        "и прошла доступные проверки риска."
    )


def select_equity_composition(
    candidates: Sequence[EquityCandidateRow],
    *,
    sleeve_weight: float,
    capital: Decimal,
    gate_status_by_symbol: dict[str, str],
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> EquitySelectionResult:
    """Equal-weight top-N after Risk Gate; blocked capital returns to cash."""
    rejected: list[dict[str, Any]] = []
    eligible: list[EquityCandidateRow] = []

    ordered = sorted(candidates, key=lambda r: (r.rank, r.instrument_id))
    for row in ordered:
        status = gate_status_by_symbol.get(row.symbol, "RESEARCH_ONLY")
        if status in {"BLOCKED", "INSUFFICIENT_DATA"}:
            rejected.append(_rej(row, status, "Исключено Risk Gate до включения в состав."))
            continue
        if row.lot_size is None or row.lot_size <= 0:
            rejected.append(
                _rej(
                    row,
                    "INSUFFICIENT_DATA",
                    "Неизвестен размер лота (LOTSIZE) по источнику MOEX — позиция не включается.",
                )
            )
            continue
        if row.reference_price * row.lot_size <= 0:
            rejected.append(_rej(row, "INSUFFICIENT_DATA", "Нет корректной цены или размера лота."))
            continue
        eligible.append(row)

    selected: list[EquityCandidateRow] = []
    n_slots = max(0, min(config.max_equity_positions, len(eligible)))
    if sleeve_weight <= 0 or n_slots == 0 or capital <= 0:
        return EquitySelectionResult(
            selected=(),
            rejected=tuple(rejected[: config.max_rejected_shown]),
            available_count=len(candidates),
            after_gate_count=len(eligible),
            equal_weight=0.0,
            sleeve_weight=sleeve_weight,
            provenance=_prov(candidates, sleeve_weight),
        )

    target_per = float(capital) * sleeve_weight / n_slots
    for row in eligible:
        if len(selected) >= n_slots:
            break
        if target_per < config.min_position_rub:
            break
        lot_cost = float(row.reference_price * int(row.lot_size))
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
                    f"Один лот занял бы более {config.max_single_position_weight * 100:.0f}% портфеля.",
                )
            )
            continue
        selected.append(row)

    n = len(selected)
    eq_w = (sleeve_weight / n) if n else 0.0
    if n and float(capital) * eq_w < config.min_position_rub:
        max_by_min = int(float(capital) * sleeve_weight // config.min_position_rub)
        selected = selected[: max(0, max_by_min)]
        n = len(selected)
        eq_w = (sleeve_weight / n) if n else 0.0

    selected_syms = {s.symbol for s in selected}
    for row in eligible:
        if row.symbol in selected_syms:
            continue
        if len(rejected) >= config.max_rejected_shown:
            break
        if any(r["symbol"] == row.symbol for r in rejected):
            continue
        rejected.append(_rej(row, "SKIPPED", "Не вошла в ограниченный набор equity-позиций V1."))

    return EquitySelectionResult(
        selected=tuple(selected),
        rejected=tuple(rejected[: config.max_rejected_shown]),
        available_count=len(candidates),
        after_gate_count=len(eligible),
        equal_weight=eq_w,
        sleeve_weight=sleeve_weight,
        provenance=_prov(candidates, sleeve_weight, selected=selected),
    )


def _rej(row: EquityCandidateRow, status: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "display_name": row.display_name,
        "sleeve": "EQUITY_ALPHA",
        "opportunity_hint": _equity_opp_hint(row),
        "risk_status": status,
        "reason_ru": reason,
    }


def _equity_opp_hint(row: EquityCandidateRow) -> str:
    if row.signal_semantic == SEMANTIC_RANKING_SCORE:
        return f"rank={row.rank} (RANKING_SCORE)"
    return f"rank={row.rank}, signal≈{row.signal_value * 100:.1f}% (EXPECTED_RETURN research)"


def _prov(
    candidates: Sequence[EquityCandidateRow],
    sleeve_weight: float,
    selected: Sequence[EquityCandidateRow] | None = None,
) -> dict[str, Any]:
    head = candidates[0] if candidates else None
    return {
        "policy": EQUITY_COMPOSITION_VERSION,
        "weighting": "EQUAL_WEIGHT",
        "sleeve_weight": sleeve_weight,
        "model_name": head.model_name if head else None,
        "model_version": head.model_version if head else None,
        "signal_semantic": head.signal_semantic if head else None,
        "batch_id": head.batch_id if head else None,
        "as_of": head.as_of if head else None,
        "selected_symbols": [s.symbol for s in (selected or ())],
    }
