"""Read models for Model Edge Research Cockpit APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.model_edge.application.diagnostics import (
    economic_viability_from_report,
    latest_diagnostics,
    regimes_payload,
    stability_payload,
    summary_payload,
    top_tail_payload,
)
from app.modules.model_edge.application.diagnostics_metrics import (
    SAMPLE_MATURITY_RU,
    sample_maturity_label,
)
from app.modules.model_edge.application.experiment import experiment_status, get_experiment
from app.modules.model_edge.config import (
    CASH_HURDLE_ANNUAL_RATE,
    SEMANTIC_EXPECTED_RETURN,
    SEMANTIC_RANKING_SCORE,
    SHADOW_PORTFOLIO_A_NAME,
    SHADOW_PORTFOLIO_B_NAME,
)
from app.modules.model_edge.infrastructure.models import (
    ProspectiveModelComparisonBatch,
    ProspectiveModelExperiment,
)
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction
from app.modules.shadow.infrastructure.models import (
    ShadowFill,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)


def _portfolio_snapshot(session: Session, name: str) -> dict[str, Any] | None:
    row = session.execute(
        select(ShadowPortfolio, ShadowPortfolioSpec)
        .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
        .where(ShadowPortfolioSpec.name == name)
    ).first()
    if row is None:
        return None
    portfolio, spec = row
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(ShadowOrder)
            .where(
                ShadowOrder.portfolio_id == portfolio.id,
                ShadowOrder.status == "PENDING",
            )
        )
        or 0
    )
    fills = int(
        session.scalar(
            select(func.count())
            .select_from(ShadowFill)
            .where(ShadowFill.portfolio_id == portfolio.id)
        )
        or 0
    )
    positions = portfolio.positions if isinstance(portfolio.positions, dict) else {}
    cash = float(portfolio.cash)
    return {
        "id": portfolio.id,
        "name": spec.name,
        "human_name": (
            "V0 · Рейтинговый портфель"
            if name == SHADOW_PORTFOLIO_A_NAME
            else "V1 · Рейтинговый портфель"
        ),
        "status": portfolio.status,
        "cash": cash,
        "nav": cash,
        "positions": len(positions),
        "pending_orders": pending,
        "fills": fills,
        "activated_at": portfolio.activated_at.isoformat() if portfolio.activated_at else None,
        "policy_name": spec.policy_name,
        "risk_name": spec.risk_name,
        "candidate_config_hash": spec.candidate_config_hash,
    }


def diagnostics_summary(session: Session) -> dict[str, Any]:
    return summary_payload(latest_diagnostics(session))


def diagnostics_top_tail(session: Session) -> dict[str, Any]:
    return top_tail_payload(latest_diagnostics(session))


def diagnostics_stability(session: Session) -> dict[str, Any]:
    return stability_payload(latest_diagnostics(session))


def diagnostics_regimes(session: Session) -> dict[str, Any]:
    return regimes_payload(latest_diagnostics(session))


def diagnostics_economic(
    session: Session, *, annual_rate: float = CASH_HURDLE_ANNUAL_RATE
) -> dict[str, Any]:
    return economic_viability_from_report(latest_diagnostics(session), annual_rate=annual_rate)


def diagnostics_disagreements(
    session: Session, *, as_of: date | None = None
) -> dict[str, Any]:
    """Historical disagreement explorer — served from persisted diagnostics when present.

    Full per-date decision attribution requires OOS prediction rows; until a dedicated
    disagreement artifact is materialised, return yearly/high-level facts and an empty
    row list with an honest note.
    """
    run = latest_diagnostics(session)
    report = (run.report if run else None) or {}
    return {
        "status": "SUCCESS" if run else "NOT_COMPUTED",
        "as_of": as_of.isoformat() if as_of else None,
        "dates": [],
        "rows": [],
        "note": (
            "Детальная таблица расхождений по датам материализуется из DEVELOPMENT OOS; "
            "сводные факты: V1 лучше общий Rank IC, но хуже Top20 realized; "
            "2020 и 2025 — наиболее проблемные годы для V1 по Top20/spread."
        ),
        "yearly_hint": {
            "v0": report.get("yearly_v0"),
            "v1": report.get("yearly_v1"),
        },
        "human_example": (
            "V1 немного лучше упорядочивает весь список инструментов, "
            "но хуже выбирает верхнюю часть рейтинга. "
            "При одинаковой портфельной стратегии V0 исторически дал более высокий результат."
        ),
    }


def prospective_latest(session: Session) -> dict[str, Any]:
    status = experiment_status(session)
    port_a = _portfolio_snapshot(session, SHADOW_PORTFOLIO_A_NAME)
    port_b = _portfolio_snapshot(session, SHADOW_PORTFOLIO_B_NAME)
    experiment = get_experiment(session)
    batches = int(status.get("comparison_batches") or 0)
    awaiting = bool(status.get("awaiting_new_market_date"))
    activated = status.get("experiment_status") == "ACTIVE" or status.get("status") == "ACTIVE"
    pipeline = {
        "experiment_activated": activated,
        "new_market_data": bool(
            status.get("market_watermark")
            and status.get("activation_market_watermark")
            and status["market_watermark"] > status["activation_market_watermark"]
        )
        if status.get("market_watermark") and status.get("activation_market_watermark")
        else False,
        "paired_predictions": batches > 0,
        "strategy_decision": bool(
            (port_a and (port_a["pending_orders"] or port_a["fills"]))
            or (port_b and (port_b["pending_orders"] or port_b["fills"]))
        ),
        "future_market_open": False,
        "execution": bool((port_a and port_a["fills"]) or (port_b and port_b["fills"])),
        "outcome_maturity_20d": False,
        "model_evaluation": False,
    }
    message = None
    if activated and awaiting and batches == 0:
        message = "Эксперимент запущен. Ждём первый новый рыночный день."
    elif not activated:
        message = "Эксперимент ещё не активирован."
    return {
        **status,
        "message": message,
        "portfolio_a": port_a,
        "portfolio_b": port_b,
        "pipeline": pipeline,
        "agreement": None,
        "historical_backfill": False,
        "experiment_row_id": experiment.id if experiment else None,
    }


def prospective_batches(session: Session) -> dict[str, Any]:
    experiment = session.scalar(select(ProspectiveModelExperiment).limit(1))
    if experiment is None:
        return {"items": [], "status": "NOT_ACTIVATED"}
    rows = list(
        session.scalars(
            select(ProspectiveModelComparisonBatch)
            .where(ProspectiveModelComparisonBatch.experiment_id == experiment.id)
            .order_by(ProspectiveModelComparisonBatch.as_of_date.desc())
        )
    )
    items = [
        {
            "id": r.id,
            "as_of": r.as_of_date.isoformat(),
            "status": r.status,
            "comparability_status": r.comparability_status,
            "rank_correlation": r.rank_correlation,
            "top20_overlap": r.top20_overlap,
            "common_eligible": r.common_eligible,
            "eligible_a": r.eligible_a,
            "eligible_b": r.eligible_b,
            "feature_snapshot_hash": r.feature_snapshot_hash,
            "candidate_a_batch_id": r.candidate_a_batch_id,
            "candidate_b_batch_id": r.candidate_b_batch_id,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        }
        for r in rows
    ]
    return {"status": "SUCCESS", "items": items}


def prospective_batch_detail(session: Session, batch_id: int) -> dict[str, Any]:
    row = session.get(ProspectiveModelComparisonBatch, batch_id)
    if row is None:
        return {"status": "NOT_FOUND"}
    tickers = {
        int(i.id): i.ticker
        for i in session.scalars(select(Instrument)).all()
    }

    def _side(batch_id_side: int | None, semantic: str) -> list[dict[str, Any]]:
        if batch_id_side is None:
            return []
        preds = list(
            session.scalars(
                select(ForwardPrediction).where(ForwardPrediction.batch_id == batch_id_side)
            )
        )
        out = []
        for p in preds:
            score = float(p.predicted_return_20d)
            item: dict[str, Any] = {
                "instrument_id": int(p.instrument_id),
                "ticker": tickers.get(int(p.instrument_id), str(p.instrument_id)),
                "rank": p.rank,
                "prediction_semantic": semantic,
            }
            if semantic == SEMANTIC_EXPECTED_RETURN:
                item["expected_return"] = score
                item["display"] = f"{score * 100:+.2f}%"
            else:
                item["ranking_score"] = score
                item["display"] = f"{score:.4f}"
                item["is_percent"] = False
            out.append(item)
        out.sort(key=lambda x: (x.get("rank") is None, x.get("rank") or 10**9))
        return out

    side_a = _side(row.candidate_a_batch_id, SEMANTIC_EXPECTED_RETURN)
    side_b = _side(row.candidate_b_batch_id, SEMANTIC_RANKING_SCORE)
    by_ticker: dict[str, dict[str, Any]] = {}
    for item in side_a:
        by_ticker[item["ticker"]] = {
            "ticker": item["ticker"],
            "v0_expected_return": item.get("expected_return"),
            "v0_rank": item.get("rank"),
            "v0_display": item.get("display"),
        }
    for item in side_b:
        slot = by_ticker.setdefault(item["ticker"], {"ticker": item["ticker"]})
        slot["v1_ranking_score"] = item.get("ranking_score")
        slot["v1_rank"] = item.get("rank")
        slot["v1_display"] = item.get("display")
        slot["v1_is_percent"] = False
    merged = []
    for _ticker, slot in by_ticker.items():
        r0 = slot.get("v0_rank")
        r1 = slot.get("v1_rank")
        slot["rank_delta"] = (
            int(r0) - int(r1) if r0 is not None and r1 is not None else None
        )
        merged.append(slot)
    merged.sort(
        key=lambda x: (
            x.get("v0_rank") is None,
            x.get("v0_rank") or 10**9,
            x.get("ticker") or "",
        )
    )
    return {
        "status": "SUCCESS",
        "id": row.id,
        "as_of": row.as_of_date.isoformat(),
        "comparability_status": row.comparability_status,
        "rank_correlation": row.rank_correlation,
        "top20_overlap": row.top20_overlap,
        "common_eligible": row.common_eligible,
        "feature_snapshot_hash": row.feature_snapshot_hash,
        "predictions": merged,
        "side_a_top10": side_a[:10],
        "side_b_top10": side_b[:10],
        "summary": row.summary,
    }


def prospective_evaluation(session: Session) -> dict[str, Any]:
    experiment = session.scalar(select(ProspectiveModelExperiment).limit(1))
    if experiment is None:
        return {
            "status": "NOT_ACTIVATED",
            "mature_dates": 0,
            "sample_maturity": "TOO_EARLY",
            "sample_maturity_ru": SAMPLE_MATURITY_RU["TOO_EARLY"],
        }
    batches = list(
        session.scalars(
            select(ProspectiveModelComparisonBatch).where(
                ProspectiveModelComparisonBatch.experiment_id == experiment.id
            )
        )
    )
    mature = sum(
        1
        for b in batches
        if isinstance(b.summary, dict) and (b.summary.get("outcome") or {}).get("matured")
    )
    label = sample_maturity_label(mature)
    return {
        "status": "SUCCESS",
        "mature_dates": mature,
        "paired_batches": len(batches),
        "sample_maturity": label,
        "sample_maturity_ru": SAMPLE_MATURITY_RU[label],
        "metrics": None,
        "conclusion": None,
        "premature_winner_declared": False,
        "note": "Пока нет зрелых парных исходов — оценка моделей не объявляется.",
    }
