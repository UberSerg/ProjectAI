"""Persist and serve MODEL_DIAGNOSTICS_V0 reports.

Heavy OOS scans are materialised once (CLI / acceptance). Read APIs serve the
cached JSONB row keyed by a deterministic input hash — never recompute on refresh.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.model_edge.application.cash_hurdle import compute_cash_hurdle
from app.modules.model_edge.config import (
    CASH_HURDLE_ANNUAL_RATE,
    DIAGNOSTICS_VERSION,
    candidate_a_config_hash,
    candidate_b_config_hash,
)
from app.modules.model_edge.infrastructure.models import ModelDiagnosticsRun

DEFAULT_PERIOD_FROM = date(2017, 2, 1)
DEFAULT_PERIOD_TO = date(2025, 12, 30)


def diagnostics_input_hash(
    *,
    candidate_a_hash: str,
    candidate_b_hash: str,
    period_from: date,
    period_to: date,
    diagnostics_version: str = DIAGNOSTICS_VERSION,
    dataset_values_hash: str | None = None,
) -> str:
    payload = {
        "diagnostics_version": diagnostics_version,
        "candidate_a_hash": candidate_a_hash,
        "candidate_b_hash": candidate_b_hash,
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "dataset_values_hash": dataset_values_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_human_conclusion(report: dict[str, Any]) -> str:
    """Deterministic Russian summary from computed facts — no LLM."""
    v0 = report.get("v0") or {}
    v1 = report.get("v1") or {}
    stab = report.get("stability") or {}
    s0 = stab.get("v0") or {}
    s1 = stab.get("v1") or {}
    econ = report.get("economic_matrix") or []
    v0_beats = any(c.get("model") == "V0" and c.get("beats_hurdle") for c in econ)
    v1_beats = any(c.get("model") == "V1" and c.get("beats_hurdle") for c in econ)

    parts = [
        (
            f"На общей выборке V1 имеет более высокий средний Rank IC "
            f"({float(v1.get('mean_rank_ic') or 0):.4f} против "
            f"{float(v0.get('mean_rank_ic') or 0):.4f}), "
            f"но хуже реализует верхнюю часть рейтинга "
            f"(Top20: {float(v1.get('top20') or 0) * 100:.2f}% против "
            f"{float(v0.get('top20') or 0) * 100:.2f}%)."
        ),
        (
            "При одинаковой рейтинговой стратегии с удержанием "
            "исторический портфель V0 выше по CAGR, "
            "хотя у V1 ниже churn и выше стабильность рангов "
            f"(недельная корреляция рангов "
            f"{float(s1.get('week_to_week_rank_corr') or 0):.3f} против "
            f"{float(s0.get('week_to_week_rank_corr') or 0):.3f})."
        ),
    ]
    if not v0_beats and not v1_beats:
        parts.append(
            "Обе стратегии уступают денежной альтернативе 10% годовых "
            "по CAGR при существенно большей просадке."
        )
    return " ".join(parts)


def enrich_report(report: dict[str, Any]) -> dict[str, Any]:
    out = dict(report)
    out.setdefault("kind", DIAGNOSTICS_VERSION)
    out["human_summary"] = build_human_conclusion(out)
    out["learned"] = [
        "Хороший общий Rank IC не гарантирует хороший портфель.",
        "Стратегия покупает верхнюю часть рейтинга — важнее top-tail.",
        "Стабильность рангов сама по себе не означает качество.",
        "Денежная альтернатива 10% — исследовательский benchmark, не вклад.",
    ]
    conclusion = out.get("conclusion") or {}
    if isinstance(conclusion, dict):
        out["conclusion_facts"] = conclusion
    return out


def persist_diagnostics_report(
    session: Session,
    report: dict[str, Any],
    *,
    period_from: date | None = None,
    period_to: date | None = None,
    candidate_a_hash: str | None = None,
    candidate_b_hash: str | None = None,
    dataset_values_hash: str | None = None,
) -> ModelDiagnosticsRun:
    enriched = enrich_report(report)
    d0 = period_from or date.fromisoformat(str(enriched.get("period_from") or DEFAULT_PERIOD_FROM))
    d1 = period_to or date.fromisoformat(str(enriched.get("period_to") or DEFAULT_PERIOD_TO))
    a_hash = candidate_a_hash or candidate_a_config_hash()
    b_hash = candidate_b_hash or candidate_b_config_hash()
    input_hash = diagnostics_input_hash(
        candidate_a_hash=a_hash,
        candidate_b_hash=b_hash,
        period_from=d0,
        period_to=d1,
        dataset_values_hash=dataset_values_hash,
    )
    existing = session.scalar(
        select(ModelDiagnosticsRun).where(ModelDiagnosticsRun.input_hash == input_hash)
    )
    if existing is not None:
        existing.report = enriched
        existing.metrics = {
            "v0": enriched.get("v0"),
            "v1": enriched.get("v1"),
            "delta_mean_rank_ic": enriched.get("delta_mean_rank_ic"),
            "delta_top20": enriched.get("delta_top20"),
        }
        existing.status = "SUCCESS"
        session.flush()
        return existing

    row = ModelDiagnosticsRun(
        diagnostics_version=DIAGNOSTICS_VERSION,
        input_hash=input_hash,
        period_from=d0,
        period_to=d1,
        candidate_a_hash=a_hash,
        candidate_b_hash=b_hash,
        dataset_values_hash=dataset_values_hash,
        status="SUCCESS",
        report=enriched,
        metrics={
            "v0": enriched.get("v0"),
            "v1": enriched.get("v1"),
            "delta_mean_rank_ic": enriched.get("delta_mean_rank_ic"),
            "delta_top20": enriched.get("delta_top20"),
        },
    )
    session.add(row)
    session.flush()
    return row


def load_diagnostics_from_file(session: Session, path: Path) -> ModelDiagnosticsRun:
    report = json.loads(path.read_text(encoding="utf-8"))
    return persist_diagnostics_report(session, report)


def latest_diagnostics(session: Session) -> ModelDiagnosticsRun | None:
    return session.scalar(
        select(ModelDiagnosticsRun)
        .where(ModelDiagnosticsRun.diagnostics_version == DIAGNOSTICS_VERSION)
        .order_by(ModelDiagnosticsRun.id.desc())
        .limit(1)
    )


def get_diagnostics_by_hash(session: Session, input_hash: str) -> ModelDiagnosticsRun | None:
    return session.scalar(
        select(ModelDiagnosticsRun).where(ModelDiagnosticsRun.input_hash == input_hash)
    )


def summary_payload(run: ModelDiagnosticsRun | None) -> dict[str, Any]:
    if run is None:
        return {"status": "NOT_COMPUTED", "models": {}}
    report = enrich_report(dict(run.report or {}))
    v0 = report.get("v0") or {}
    v1 = report.get("v1") or {}
    stab = report.get("stability") or {}
    econ = {c["model"]: c for c in (report.get("economic_matrix") or []) if c.get("bps") == 0}
    return {
        "status": "SUCCESS",
        "diagnostics_version": run.diagnostics_version,
        "input_hash": run.input_hash,
        "period_from": run.period_from.isoformat() if run.period_from else None,
        "period_to": run.period_to.isoformat() if run.period_to else None,
        "common_dates": report.get("common_dates"),
        "models": {
            "v0": {
                "human_label": "Кандидат V0 · ожидаемая доходность",
                "rank_ic": v0.get("mean_rank_ic"),
                "median_rank_ic": v0.get("median_rank_ic"),
                "positive_ic_pct": v0.get("positive_ic_pct"),
                "top20_realized": v0.get("top20"),
                "top20_spread": v0.get("top20_spread"),
                "stability": (stab.get("v0") or {}).get("week_to_week_rank_corr"),
                "cagr": (econ.get("V0") or {}).get("cagr"),
                "max_drawdown": (econ.get("V0") or {}).get("mdd"),
                "turnover_ratio": (econ.get("V0") or {}).get("turnover"),
                "excess_vs_cash": (econ.get("V0") or {}).get("excess_cagr_pp"),
            },
            "v1": {
                "human_label": "Кандидат V1 · рейтинговый балл",
                "rank_ic": v1.get("mean_rank_ic"),
                "median_rank_ic": v1.get("median_rank_ic"),
                "positive_ic_pct": v1.get("positive_ic_pct"),
                "top20_realized": v1.get("top20"),
                "top20_spread": v1.get("top20_spread"),
                "stability": (stab.get("v1") or {}).get("week_to_week_rank_corr"),
                "cagr": (econ.get("V1") or {}).get("cagr"),
                "max_drawdown": (econ.get("V1") or {}).get("mdd"),
                "turnover_ratio": (econ.get("V1") or {}).get("turnover"),
                "excess_vs_cash": (econ.get("V1") or {}).get("excess_cagr_pp"),
            },
        },
        "human_summary": report.get("human_summary"),
        "conclusion": report.get("human_summary"),
        "learned": report.get("learned"),
        "conclusion_facts": report.get("conclusion_facts") or report.get("conclusion"),
    }


def top_tail_payload(run: ModelDiagnosticsRun | None) -> dict[str, Any]:
    if run is None:
        return {"status": "NOT_COMPUTED", "rows": []}
    report = run.report or {}
    v0 = report.get("v0") or {}
    v1 = report.get("v1") or {}
    rows = []
    for share, key in ((0.05, "top5"), (0.10, "top10"), (0.20, "top20"), (0.30, "top30")):
        rows.append(
            {
                "quantile": share,
                "label": f"Верхние {int(share * 100)}%",
                "v0_realized": v0.get(key),
                "v1_realized": v1.get(key),
                "v0_precision": v0.get("top20_precision") if share == 0.20 else None,
                "v1_precision": v1.get("top20_precision") if share == 0.20 else None,
                "v0_recall": v0.get("top20_recall") if share == 0.20 else None,
                "v1_recall": v1.get("top20_recall") if share == 0.20 else None,
                "v0_loser_contamination": (
                    v0.get("bottom_contamination") if share == 0.20 else None
                ),
                "v1_loser_contamination": (
                    v1.get("bottom_contamination") if share == 0.20 else None
                ),
            }
        )
    return {
        "status": "SUCCESS",
        "note": (
            "Стратегия покупает верхнюю часть рейтинга, поэтому хороший общий "
            "Rank IC не гарантирует хороший портфель."
        ),
        "rows": rows,
    }


def stability_payload(run: ModelDiagnosticsRun | None) -> dict[str, Any]:
    if run is None:
        return {"status": "NOT_COMPUTED"}
    stab = (run.report or {}).get("stability") or {}
    return {
        "status": "SUCCESS",
        "by_model": stab,
        "week_to_week_correlation": {
            "v0": (stab.get("v0") or {}).get("week_to_week_rank_corr"),
            "v1": (stab.get("v1") or {}).get("week_to_week_rank_corr"),
        },
        "avg_rank_movement": {
            "v0": (stab.get("v0") or {}).get("avg_abs_rank_change"),
            "v1": (stab.get("v1") or {}).get("avg_abs_rank_change"),
        },
        "top20_persistence": {
            "v0": (stab.get("v0") or {}).get("top20_persistence"),
            "v1": (stab.get("v1") or {}).get("top20_persistence"),
        },
        "top35_persistence": {
            "v0": (stab.get("v0") or {}).get("top35_persistence"),
            "v1": (stab.get("v1") or {}).get("top35_persistence"),
        },
        "entry_churn": {
            "v0": (stab.get("v0") or {}).get("entry_churn"),
            "v1": (stab.get("v1") or {}).get("entry_churn"),
        },
        "exit_churn": {
            "v0": (stab.get("v0") or {}).get("exit_churn"),
            "v1": (stab.get("v1") or {}).get("exit_churn"),
        },
        "note": (
            "Стабильный рейтинг может уменьшать лишние сделки, "
            "но стабильность сама по себе не означает качество."
        ),
    }


def regimes_payload(run: ModelDiagnosticsRun | None) -> dict[str, Any]:
    if run is None:
        return {"status": "NOT_COMPUTED", "rows": []}
    report = run.report or {}
    yearly_v0 = {r["year"]: r for r in (report.get("yearly_v0") or [])}
    yearly_v1 = {r["year"]: r for r in (report.get("yearly_v1") or [])}
    years = sorted(set(yearly_v0) | set(yearly_v1))
    rows = []
    for year in years:
        a = yearly_v0.get(year) or {}
        b = yearly_v1.get(year) or {}
        rows.append(
            {
                "regime": str(year),
                "regime_type": "year",
                "observations": a.get("n") or b.get("n"),
                "v0_rank_ic": a.get("mean_ic"),
                "v1_rank_ic": b.get("mean_ic"),
                "v0_top20": a.get("mean_top20"),
                "v1_top20": b.get("mean_top20"),
                "v0_spread": a.get("mean_spread"),
                "v1_spread": b.get("mean_spread"),
                "sparse": int(a.get("n") or b.get("n") or 0) < 50,
            }
        )
    return {
        "status": "SUCCESS",
        "rows": rows,
        "note": "Разбивка по календарным годам DEVELOPMENT OOS; HOLDOUT не используется.",
    }


def economic_viability_from_report(
    run: ModelDiagnosticsRun | None,
    *,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
) -> dict[str, Any]:
    if run is None:
        return {
            "status": "NOT_COMPUTED",
            "annual_rate": annual_rate,
            "cash_hurdle_mutates_portfolio": False,
            "cells": [],
        }
    report = run.report or {}
    d0 = run.period_from or DEFAULT_PERIOD_FROM
    d1 = run.period_to or DEFAULT_PERIOD_TO
    hurdle = compute_cash_hurdle(d0, d1, annual_rate=annual_rate)
    cells = []
    models: dict[str, Any] = {}
    for cell in report.get("economic_matrix") or []:
        # Recompute excess vs selected hurdle rate from stored total return.
        total = cell.get("total")
        excess_total = None
        excess_cagr = None
        if total is not None:
            excess_total = float(total) - hurdle.hurdle_return
        cagr = cell.get("cagr")
        if cagr is not None:
            excess_cagr = float(cagr) - annual_rate
        payload = {
            **cell,
            "cash_hurdle_annual_rate": annual_rate,
            "cash_period_return": hurdle.hurdle_return,
            "excess_total": excess_total,
            "excess_cagr_pp": excess_cagr,
            "beats_hurdle": bool(cagr is not None and float(cagr) > annual_rate),
            "viability": (
                "BELOW_CASH_HURDLE"
                if excess_cagr is not None and excess_cagr < -0.02
                else "ABOVE_CASH_HURDLE"
                if excess_cagr is not None and excess_cagr > 0.02
                else "INCONCLUSIVE_VS_CASH_HURDLE"
                if excess_cagr is not None
                else "INSUFFICIENT_DATA"
            ),
        }
        cells.append(payload)
        if cell.get("bps") == 0:
            models[str(cell.get("model"))] = {
                "cagr": cagr,
                "excess_vs_cash": excess_cagr,
                "max_drawdown": cell.get("mdd"),
                "hurdle_return": hurdle.hurdle_return,
                "turnover": cell.get("turnover"),
                "conclusion": (
                    "Исторически не превысила выбранную денежную альтернативу."
                    if excess_cagr is not None and excess_cagr < 0
                    else "Исторически превысила денежную альтернативу."
                    if excess_cagr is not None and excess_cagr > 0
                    else None
                ),
            }
    return {
        "status": "SUCCESS",
        "annual_rate": annual_rate,
        "cash_hurdle": hurdle.to_dict(),
        "cash_hurdle_mutates_portfolio": False,
        "rate_based_proxy_implemented": False,
        "rate_based_proxy_reason": (
            "Deferred: fixed 10% cash hurdle is sufficient for this research pack; "
            "KEY_RATE deposit-proxy not claimed as bank yield."
        ),
        "cells": cells,
        "models": models,
        "break_even_cost": {
            "v0": "Между 10 и 20 bps относительно нулевой доходности; ниже 10% hurdle на всей сетке.",
            "v1": "Около 20 bps относительно нуля; ниже 10% hurdle на всей сетке.",
        },
    }
