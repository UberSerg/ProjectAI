"""Application services: Prediction Calibration & Confidence Engine V1.

Read-only over Forward batches/outcomes. No Forward/Shadow/model mutation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.prediction.domain.calibration_v1 import (
    PredictionCalibration,
    RankingCalibration,
    calibrate_expected_return,
    calibrate_ranking_quality,
)
from app.modules.prediction.domain.confidence import (
    ConfidenceAssessment,
    ConfidenceInputs,
    PredictionConfidenceEngine,
)


def _safe_import_models() -> tuple[Any, Any, Any, Any] | None:
    try:
        from app.modules.prediction.infrastructure.forward_models import (
            ForwardPrediction,
            ForwardPredictionBatch,
        )
        from app.modules.prediction.infrastructure.forward_outcome_models import (
            ForwardBatchEvaluation,
            ForwardPredictionOutcome,
        )
    except Exception:  # noqa: BLE001
        return None
    return ForwardPredictionBatch, ForwardPredictionOutcome, ForwardBatchEvaluation, ForwardPrediction


def load_v0_expected_return_calibration(
    session: Session, *, limit: int = 10000
) -> PredictionCalibration:
    models = _safe_import_models()
    if models is None:
        return calibrate_expected_return([])
    Batch, Outcome, _Eval, _Pred = models
    try:
        pending = session.scalar(
            select(func.count())
            .select_from(Outcome)
            .join(Batch, Batch.id == Outcome.batch_id)
            .where(
                Outcome.status == "PENDING_OUTCOME",
                Batch.prediction_semantic == "EXPECTED_RETURN",
                Batch.candidate_name == CANDIDATE_V0_CONFIG.candidate_name,
                Batch.candidate_version == CANDIDATE_V0_CONFIG.candidate_version,
            )
        ) or 0
        rows = session.execute(
            select(Outcome.predicted_return_20d, Outcome.realized_return_20d)
            .join(Batch, Batch.id == Outcome.batch_id)
            .where(
                Outcome.status == "EVALUATED",
                Outcome.realized_return_20d.is_not(None),
                Outcome.horizon_observations == 20,
                Batch.prediction_semantic == "EXPECTED_RETURN",
                Batch.candidate_name == CANDIDATE_V0_CONFIG.candidate_name,
                Batch.candidate_version == CANDIDATE_V0_CONFIG.candidate_version,
            )
            .order_by(Outcome.as_of_date.desc())
            .limit(limit)
        ).all()
    except Exception:  # noqa: BLE001
        return calibrate_expected_return([])

    pairs = [(float(p), float(r)) for p, r in rows if p is not None and r is not None]
    return calibrate_expected_return(
        pairs,
        candidate=f"{CANDIDATE_V0_CONFIG.candidate_name}/{CANDIDATE_V0_CONFIG.candidate_version}",
        model_version=CANDIDATE_V0_CONFIG.candidate_version,
        pending_count=int(pending),
    )


def load_v1_ranking_calibration(session: Session, *, limit: int = 5000) -> RankingCalibration:
    models = _safe_import_models()
    if models is None:
        return calibrate_ranking_quality(
            sample_count=0, spearman_values=[], top20_realized=[], bottom20_realized=[]
        )
    Batch, Outcome, BatchEval, Pred = models
    try:
        pending = session.scalar(
            select(func.count())
            .select_from(Pred)
            .join(Batch, Batch.id == Pred.batch_id)
            .where(
                Pred.outcome_status == "PENDING_OUTCOME",
                Batch.prediction_semantic == "RANKING_SCORE",
                Batch.candidate_name == CANDIDATE_V1_RANKER_CONFIG.candidate_name,
                Batch.candidate_version == CANDIDATE_V1_RANKER_CONFIG.candidate_version,
            )
        ) or 0

        evals = session.execute(
            select(
                BatchEval.spearman_rank_ic,
                BatchEval.top20_realized_mean,
                BatchEval.bottom20_realized_mean,
                BatchEval.evaluated_count,
            )
            .join(Batch, Batch.id == BatchEval.batch_id)
            .where(
                Batch.prediction_semantic == "RANKING_SCORE",
                Batch.candidate_name == CANDIDATE_V1_RANKER_CONFIG.candidate_name,
                Batch.candidate_version == CANDIDATE_V1_RANKER_CONFIG.candidate_version,
                BatchEval.status.in_(("EVALUATED", "PARTIALLY_MATURED")),
                BatchEval.evaluated_count > 0,
            )
            .limit(limit)
        ).all()

        # Pair ranking scores with matured realized returns (market-side), never treat score as %.
        rank_rows = session.execute(
            select(Pred.predicted_return_20d, Outcome.realized_return_20d)
            .join(Batch, Batch.id == Pred.batch_id)
            .join(
                Outcome,
                (Outcome.as_of_date == Pred.as_of_date)
                & (Outcome.instrument_id == Pred.instrument_id)
                & (Outcome.status == "EVALUATED"),
            )
            .where(
                Batch.prediction_semantic == "RANKING_SCORE",
                Batch.candidate_name == CANDIDATE_V1_RANKER_CONFIG.candidate_name,
                Batch.candidate_version == CANDIDATE_V1_RANKER_CONFIG.candidate_version,
                Outcome.realized_return_20d.is_not(None),
            )
            .limit(limit)
        ).all()
    except Exception:  # noqa: BLE001
        return calibrate_ranking_quality(
            sample_count=0, spearman_values=[], top20_realized=[], bottom20_realized=[]
        )

    spearman = [float(s) for s, _, _, _ in evals if s is not None]
    tops = [float(t) for _, t, _, _ in evals if t is not None]
    bottoms = [float(b) for _, _, b, _ in evals if b is not None]
    pairs = [(float(p), float(r)) for p, r in rank_rows if p is not None and r is not None]
    sample = sum(int(c) for _, _, _, c in evals) if evals else len(pairs)
    return calibrate_ranking_quality(
        candidate=(
            f"{CANDIDATE_V1_RANKER_CONFIG.candidate_name}/"
            f"{CANDIDATE_V1_RANKER_CONFIG.candidate_version}"
        ),
        model_version=CANDIDATE_V1_RANKER_CONFIG.candidate_version,
        sample_count=int(sample),
        pending_count=int(pending),
        spearman_values=spearman,
        top20_realized=tops,
        bottom20_realized=bottoms,
        rank_pairs=pairs,
    )


def assess_equity_confidence(session: Session) -> tuple[PredictionCalibration, ConfidenceAssessment]:
    cal = load_v0_expected_return_calibration(session)
    conf = PredictionConfidenceEngine().assess(
        ConfidenceInputs(calibration=cal, data_quality_ok=True, model_status="RESEARCH")
    )
    return cal, conf


def build_calibration_report(session: Session) -> dict[str, Any]:
    v0_cal, v0_conf = assess_equity_confidence(session)
    v1_cal = load_v1_ranking_calibration(session)
    v1_conf = PredictionConfidenceEngine().assess_ranking(v1_cal)
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "pipeline": "Prediction → Calibration → Confidence → Allocation",
        "candidate_v0": {
            "id": f"{CANDIDATE_V0_CONFIG.candidate_name}/{CANDIDATE_V0_CONFIG.candidate_version}",
            "title": "Модель прогнозирования доходности",
            "semantic": "EXPECTED_RETURN",
            "calibration": _calibration_payload(v0_cal),
            "confidence": _confidence_payload(v0_conf),
        },
        "candidate_v1": {
            "id": (
                f"{CANDIDATE_V1_RANKER_CONFIG.candidate_name}/"
                f"{CANDIDATE_V1_RANKER_CONFIG.candidate_version}"
            ),
            "title": "Модель ранжирования",
            "semantic": "RANKING_SCORE",
            "calibration": _ranking_payload(v1_cal),
            "confidence": _confidence_payload(v1_conf),
        },
        "note": "Research comparison only — no automatic winner.",
        "chart_data": {
            "v0_buckets": [
                {
                    "bucket": b.bucket_name,
                    "average_prediction": b.average_prediction,
                    "average_realized_return": b.average_realized_return,
                    "sample_count": b.sample_count,
                }
                for b in v0_cal.buckets
            ]
        },
    }


def write_calibration_artifacts(session: Session, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_calibration_report(session)
    path = out_dir / "calibration.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                "v0": report["candidate_v0"]["calibration"],
                "v0_confidence": report["candidate_v0"]["confidence"],
                "v1": report["candidate_v1"]["calibration"],
                "v1_confidence": report["candidate_v1"]["confidence"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (out_dir / "charts_data.json").write_text(
        json.dumps(report["chart_data"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def _calibration_payload(cal: PredictionCalibration) -> dict[str, Any]:
    payload = asdict(cal)
    payload["calibration_status"] = cal.calibration_status.value
    payload["created_at"] = cal.created_at.isoformat()
    payload["bias_sign"] = (
        "negative_overestimates"
        if cal.bias is not None and cal.bias < 0
        else "positive_underestimates"
        if cal.bias is not None and cal.bias > 0
        else "none"
    )
    return payload


def _ranking_payload(cal: RankingCalibration) -> dict[str, Any]:
    payload = asdict(cal)
    payload["calibration_status"] = cal.calibration_status.value
    payload["created_at"] = cal.created_at.isoformat()
    return payload


def _confidence_payload(conf: ConfidenceAssessment) -> dict[str, Any]:
    return {
        "confidence_level": conf.confidence_level.value,
        "confidence_status": conf.confidence_status,
        "reason_codes": list(conf.reason_codes),
        "reason_ru": conf.reason_ru,
        "limitations": list(conf.limitations),
        "sample_size": conf.sample_size,
        "calibration_status": conf.calibration_status,
    }
