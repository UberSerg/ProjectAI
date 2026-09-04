"""Research Lab V0 — side-by-side experiment comparison read-model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.research_lab.application.service import enrich_run_summary
from app.modules.research_lab.catalog import COST_PRESETS_BPS, PROTECTED_SEGMENT
from app.modules.research_lab.errors import CompareTooFew, CompareTooMany, RunNotFound
from app.modules.simulator.infrastructure.models import SimulationRun, SimulationSpec
from app.modules.simulator.infrastructure.repository import get_nav_series, get_run

MIN_COMPARE_RUNS = 2
MAX_COMPARE_RUNS = 5

_FAIR_FIELDS: tuple[tuple[str, str], ...] = (
    ("candidate_config_hash", "Модель (candidate config hash)"),
    ("segment", "Сегмент прогнозов"),
    ("date_from", "Дата начала"),
    ("date_to", "Дата окончания"),
    ("initial_capital", "Стартовый капитал"),
    ("execution_timing", "Исполнение"),
    ("fractional_shares", "Дробные лоты"),
)

_METRICS: tuple[tuple[str, str, str], ...] = (
    ("total_price_return", "Доходность (price return)", "sim_cagr"),
    ("cagr", "CAGR", "sim_cagr"),
    ("imoex", "IMOEX (price return)", "sim_excess"),
    ("excess_vs_imoex", "Относительный результат (п.п.)", "sim_excess"),
    ("max_drawdown", "Максимальная просадка", "sim_max_drawdown"),
    ("annualized_volatility", "Волатильность", "sim_volatility"),
    ("sharpe_rf0", "Sharpe (rf=0)", "sim_sharpe"),
    ("turnover_ratio", "Оборот", "sim_turnover"),
    ("trade_count", "Число сделок", "sim_turnover"),
    ("average_gross_exposure", "Средняя gross exposure", "sim_exposure"),
    ("average_cash_weight", "Средняя доля cash", "sim_cash"),
    ("commission_bps", "Commission (bps)", "sim_commission"),
)

_HOLDOUT_WARNING = (
    "Сравнение допустимо для анализа, но результат на FINAL_HOLDOUT нельзя использовать "
    "как независимую проверку настройки, выбранной после просмотра holdout."
)

_COST_FAMILY_MISSING = (
    "Для этого сравнения нет полного набора сценариев издержек (0/5/10/20 bps)."
)
_COST_FAMILY_PRESENT = (
    "Выбранные эксперименты образуют семейство чувствительности к издержкам."
)


@dataclass(slots=True)
class _RunContext:
    run: SimulationRun
    spec_row: SimulationSpec | None
    payload: dict[str, Any]
    summary: dict[str, Any]


def compare_runs(session: Session, run_ids: list[int]) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(run_ids))
    if len(unique_ids) < MIN_COMPARE_RUNS:
        raise CompareTooFew(
            f"Для сравнения нужно минимум {MIN_COMPARE_RUNS} эксперимента",
            details={"provided": len(unique_ids), "minimum": MIN_COMPARE_RUNS},
        )
    if len(unique_ids) > MAX_COMPARE_RUNS:
        raise CompareTooMany(
            f"Можно сравнить не более {MAX_COMPARE_RUNS} экспериментов",
            details={"provided": len(unique_ids), "maximum": MAX_COMPARE_RUNS},
        )

    contexts: list[_RunContext] = []
    for run_id in unique_ids:
        run = get_run(session, run_id)
        if run is None:
            raise RunNotFound(
                f"Эксперимент {run_id} не найден",
                details={"run_id": run_id},
            )
        spec_row = session.get(SimulationSpec, run.simulation_spec_id)
        payload = dict(spec_row.payload or {}) if spec_row is not None else {}
        contexts.append(
            _RunContext(
                run=run,
                spec_row=spec_row,
                payload=payload,
                summary=enrich_run_summary(session, run),
            )
        )

    differences = _build_differences(contexts)
    fair_comparison = len(differences) == 0
    period_aligned = _period_aligned(contexts)
    cost_family = _build_cost_family(contexts)

    return {
        "runs": [ctx.summary for ctx in contexts],
        "fair_comparison": fair_comparison,
        "fair_badge": "Сопоставимые условия" if fair_comparison else "Условия различаются",
        "differences": differences,
        "metrics_table": _build_metrics_table(contexts),
        "interpretation": _build_interpretation(contexts, cost_family, fair_comparison),
        "observed_holdout_warning": _holdout_warning(contexts),
        "cost_family": cost_family,
        "nav_series": _build_nav_series(session, contexts),
        "normalization": "start_100",
        "period_aligned": period_aligned,
    }


def _field_value(ctx: _RunContext, field: str) -> Any:
    if field == "candidate_config_hash":
        return ctx.run.candidate_config_hash
    if field == "segment":
        return ctx.run.segment
    if field in {"date_from", "date_to"}:
        value = getattr(ctx.run, field)
        return value.isoformat() if value is not None else None
    return ctx.payload.get(field)


def _build_differences(contexts: list[_RunContext]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for field, human in _FAIR_FIELDS:
        values = {ctx.run.id: _field_value(ctx, field) for ctx in contexts}
        normalized = {run_id: _normalize_compare_value(value) for run_id, value in values.items()}
        if len(set(normalized.values())) <= 1:
            continue
        differences.append({"field": field, "human": human, "values": values})
    return differences


def _normalize_compare_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 9)
    return value


def _period_aligned(contexts: list[_RunContext]) -> bool:
    ranges = {
        (
            ctx.run.date_from.isoformat() if ctx.run.date_from else None,
            ctx.run.date_to.isoformat() if ctx.run.date_to else None,
        )
        for ctx in contexts
    }
    return len(ranges) == 1


def _metric_value(ctx: _RunContext, metric_id: str) -> Any:
    metrics = ctx.run.metrics or {}
    benchmark = ctx.run.benchmark or {}
    if metric_id == "imoex":
        return benchmark.get("total_price_return")
    if metric_id == "commission_bps":
        return ctx.payload.get("commission_bps")
    return metrics.get(metric_id)


def _build_metrics_table(contexts: list[_RunContext]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_id, human_label, help_id in _METRICS:
        values = {ctx.run.id: _metric_value(ctx, metric_id) for ctx in contexts}
        rows.append(
            {
                "metric_id": metric_id,
                "human_label": human_label,
                "help_id": help_id,
                "values": values,
            }
        )
    return rows


def _build_nav_series(session: Session, contexts: list[_RunContext]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for ctx in contexts:
        rows = get_nav_series(session, ctx.run.id)
        if not rows:
            out[ctx.run.id] = []
            continue
        base_nav = rows[0].nav
        scale = 100.0 / base_nav if base_nav else 1.0
        out[ctx.run.id] = [
            {
                "date": row.as_of_date.isoformat(),
                "nav": row.nav,
                "drawdown": row.drawdown,
                "nav_normalized": row.nav * scale,
            }
            for row in rows
        ]
    return out


def _cost_excluded_fingerprint(ctx: _RunContext) -> tuple[Any, ...]:
    return (
        ctx.payload.get("policy_name") or (ctx.spec_row.policy_name if ctx.spec_row else None),
        ctx.payload.get("risk_name") or (ctx.run.provenance or {}).get("risk_name"),
        ctx.run.segment,
        ctx.run.date_from.isoformat() if ctx.run.date_from else None,
        ctx.run.date_to.isoformat() if ctx.run.date_to else None,
        ctx.run.candidate_config_hash,
        float(ctx.payload.get("slippage_bps") or 0.0),
        float(ctx.payload.get("initial_capital") or 0.0),
        ctx.payload.get("execution_timing"),
        bool(ctx.payload.get("fractional_shares", True)),
    )


def _commission_bps(ctx: _RunContext) -> float | None:
    raw = ctx.payload.get("commission_bps")
    if raw is None:
        return None
    return float(raw)


def _build_cost_family(contexts: list[_RunContext]) -> dict[str, Any]:
    required = {float(bps) for bps in COST_PRESETS_BPS}
    by_fingerprint: dict[tuple[Any, ...], list[_RunContext]] = {}
    for ctx in contexts:
        by_fingerprint.setdefault(_cost_excluded_fingerprint(ctx), []).append(ctx)

    matrix: list[dict[str, Any]] = []
    for fingerprint, group in by_fingerprint.items():
        if len(group) < len(required):
            continue
        by_bps: dict[float, _RunContext] = {}
        valid = True
        for ctx in group:
            bps = _commission_bps(ctx)
            if bps is None or bps not in required:
                valid = False
                break
            if bps in by_bps:
                valid = False
                break
            by_bps[bps] = ctx
        if not valid or set(by_bps) != required:
            continue
        policy_name, risk_name, segment, date_from, date_to, candidate_hash, *_rest = fingerprint
        cells: dict[str, dict[str, Any]] = {}
        for bps in sorted(by_bps):
            ctx = by_bps[bps]
            metrics = ctx.run.metrics or {}
            cells[str(int(bps) if bps.is_integer() else bps)] = {
                "run_id": ctx.run.id,
                "total_price_return": metrics.get("total_price_return"),
                "max_drawdown": metrics.get("max_drawdown"),
                "turnover_ratio": metrics.get("turnover_ratio"),
                "sharpe_rf0": metrics.get("sharpe_rf0"),
            }
        matrix.append(
            {
                "policy_name": policy_name,
                "risk_name": risk_name,
                "segment": segment,
                "date_from": date_from,
                "date_to": date_to,
                "candidate_config_hash": candidate_hash,
                "cells": cells,
            }
        )

    present = bool(matrix)
    return {
        "present": present,
        "message": _COST_FAMILY_PRESENT if present else _COST_FAMILY_MISSING,
        "matrix": matrix if present else None,
    }


def _run_label(summary: dict[str, Any], run_id: int) -> str:
    return (
        summary.get("display_name")
        or summary.get("lab_name")
        or summary.get("name")
        or f"Эксперимент #{run_id}"
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _build_interpretation(
    contexts: list[_RunContext],
    cost_family: dict[str, Any],
    fair_comparison: bool,
) -> list[str]:
    if len(contexts) < 2:
        return []

    labels = {ctx.run.id: _run_label(ctx.summary, ctx.run.id) for ctx in contexts}
    observations: list[str] = []

    turnovers = [
        (ctx.run.id, (ctx.run.metrics or {}).get("turnover_ratio"))
        for ctx in contexts
        if (ctx.run.metrics or {}).get("turnover_ratio") is not None
    ]
    if len(turnovers) >= 2:
        low_id, low_val = min(turnovers, key=lambda item: item[1])
        high_id, high_val = max(turnovers, key=lambda item: item[1])
        if high_val > low_val * 1.05 + 1e-9:
            observations.append(
                f"«{labels[low_id]}» имеет более низкий оборот ({low_val:.1f}×), "
                f"чем «{labels[high_id]}» ({high_val:.1f}×)."
            )

    drawdowns = [
        (ctx.run.id, (ctx.run.metrics or {}).get("max_drawdown"))
        for ctx in contexts
        if (ctx.run.metrics or {}).get("max_drawdown") is not None
    ]
    if len(drawdowns) >= 2:
        shallow_id, shallow_val = max(drawdowns, key=lambda item: item[1])
        deep_id, deep_val = min(drawdowns, key=lambda item: item[1])
        if deep_val < shallow_val - 0.01:
            observations.append(
                f"Максимальная просадка у «{labels[deep_id]}» составляет {_pct(deep_val)}, "
                f"у «{labels[shallow_id]}» — {_pct(shallow_val)}."
            )

    returns = [
        (ctx.run.id, (ctx.run.metrics or {}).get("total_price_return"))
        for ctx in contexts
        if (ctx.run.metrics or {}).get("total_price_return") is not None
    ]
    if len(returns) >= 2:
        low_id, low_val = min(returns, key=lambda item: item[1])
        high_id, high_val = max(returns, key=lambda item: item[1])
        if high_val - low_val > 0.01:
            observations.append(
                f"Историческая price-доходность у «{labels[high_id]}» составляет {_pct(high_val)}, "
                f"у «{labels[low_id]}» — {_pct(low_val)}."
            )

    trades = [
        (ctx.run.id, (ctx.run.metrics or {}).get("trade_count"))
        for ctx in contexts
        if (ctx.run.metrics or {}).get("trade_count") is not None
    ]
    if len(trades) >= 2:
        low_id, low_val = min(trades, key=lambda item: item[1])
        high_id, high_val = max(trades, key=lambda item: item[1])
        if high_val > low_val:
            observations.append(
                f"«{labels[low_id]}» совершил {int(low_val)} сделок, "
                f"«{labels[high_id]}» — {int(high_val)}."
            )

    if fair_comparison:
        vols = [
            (ctx.run.id, (ctx.run.metrics or {}).get("annualized_volatility"))
            for ctx in contexts
            if (ctx.run.metrics or {}).get("annualized_volatility") is not None
        ]
        if len(vols) >= 2:
            low_id, low_val = min(vols, key=lambda item: item[1])
            high_id, high_val = max(vols, key=lambda item: item[1])
            if high_val > low_val * 1.05 + 1e-9:
                observations.append(
                    f"При сопоставимых условиях «{labels[low_id]}» показывает более низкую "
                    f"волатильность ({low_val * 100:.1f}%), чем «{labels[high_id]}» ({high_val * 100:.1f}%)."
                )

    for row in cost_family.get("matrix") or []:
        cells = row.get("cells") or {}
        zero = cells.get("0")
        twenty = cells.get("20")
        if not zero or not twenty:
            continue
        zero_ret = zero.get("total_price_return")
        twenty_ret = twenty.get("total_price_return")
        if zero_ret is None or twenty_ret is None:
            continue
        policy = row.get("policy_name") or "стратегия"
        observations.append(
            f"Для {policy} рост комиссии с 0 до 20 bps меняет price-доходность "
            f"с {_pct(zero_ret)} до {_pct(twenty_ret)}."
        )

    return observations


def _holdout_warning(contexts: list[_RunContext]) -> str | None:
    if any(ctx.run.segment == PROTECTED_SEGMENT for ctx in contexts):
        return _HOLDOUT_WARNING
    return None
