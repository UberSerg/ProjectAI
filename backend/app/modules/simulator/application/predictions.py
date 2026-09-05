"""OOS prediction artifact loader — never regenerates models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.domain.ports.portfolio import PredictionSignal
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.prediction.infrastructure.artifacts import (
    candidate_artifact_dir,
    prediction_hash,
)
from app.modules.simulator.config import SimulationSegment


class PredictionProvenanceError(ValueError):
    """Raised when OOS provenance cannot be established."""


@dataclass(frozen=True, slots=True)
class PredictionBundle:
    segment: SimulationSegment
    artifact_dir: Path
    candidate_config_hash: str
    dataset_values_hash: str
    prediction_hash: str
    frame: pd.DataFrame
    fold_aware: bool
    prediction_semantic: str = "EXPECTED_RETURN"
    candidate_name: str = CANDIDATE_V0_CONFIG.candidate_name
    candidate_version: str = CANDIDATE_V0_CONFIG.candidate_version


def resolve_candidate_dir(
    *,
    candidate_name: str | None = None,
    candidate_version: str | None = None,
    config_hash: str | None = None,
    root: Path | None = None,
) -> Path:
    name = candidate_name or CANDIDATE_V0_CONFIG.candidate_name
    version = candidate_version or CANDIDATE_V0_CONFIG.candidate_version
    if config_hash is None:
        if version == CANDIDATE_V1_RANKER_CONFIG.candidate_version:
            config_hash = CANDIDATE_V1_RANKER_CONFIG.config_hash()
        else:
            config_hash = CANDIDATE_V0_CONFIG.config_hash()
    return candidate_artifact_dir(
        candidate_name=name,
        candidate_version=version,
        config_hash=config_hash,
        root=root,
    )


def load_oos_predictions(
    segment: SimulationSegment,
    *,
    artifact_dir: Path | None = None,
    expected_prediction_hash: str | None = None,
    candidate_name: str | None = None,
    candidate_version: str | None = None,
    config_hash: str | None = None,
) -> PredictionBundle:
    """Load DEVELOPMENT_OOS or FINAL_HOLDOUT predictions only."""
    base = artifact_dir or resolve_candidate_dir(
        candidate_name=candidate_name,
        candidate_version=candidate_version,
        config_hash=config_hash,
    )
    marker_path = base / "holdout_evaluated_marker.json"
    config_path = base / "candidate_config.json"
    if not marker_path.exists() or not config_path.exists():
        raise PredictionProvenanceError(f"missing candidate artifacts under {base}")

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    candidate_config_hash = str(config_payload.get("config_hash") or "")
    prediction_semantic = str(config_payload.get("prediction_semantic") or "EXPECTED_RETURN")
    cand_name = str(config_payload.get("candidate_name") or candidate_name or CANDIDATE_V0_CONFIG.candidate_name)
    cand_version = str(
        config_payload.get("candidate_version") or candidate_version or CANDIDATE_V0_CONFIG.candidate_version
    )
    if not candidate_config_hash:
        if cand_version == CANDIDATE_V1_RANKER_CONFIG.candidate_version:
            candidate_config_hash = CANDIDATE_V1_RANKER_CONFIG.config_hash()
        else:
            candidate_config_hash = CANDIDATE_V0_CONFIG.config_hash()
    dataset_values_hash = str(
        config_payload.get("required_values_hash")
        or CANDIDATE_V0_CONFIG.required_values_hash
    )

    if segment == "DEVELOPMENT_OOS":
        csv_path = base / "predictions_development.csv"
        hash_key = "development_prediction_hash"
        fold_aware = True
    elif segment == "FINAL_HOLDOUT":
        if prediction_semantic == "RANKING_SCORE":
            raise PredictionProvenanceError(
                "Candidate V1 Ranker FINAL_HOLDOUT predictions are not available "
                "for research selection (already-observed holdout blocked)."
            )
        csv_path = base / "predictions_holdout.csv"
        hash_key = "holdout_prediction_hash"
        fold_aware = False
    else:
        raise PredictionProvenanceError(f"unknown segment: {segment}")

    if not csv_path.exists():
        raise PredictionProvenanceError(f"missing OOS predictions: {csv_path}")

    frame = pd.read_csv(csv_path)
    # Prefer explicit prediction_score; fall back to y_pred (V0 and V1 export both)
    if "prediction_score" in frame.columns and "y_pred" not in frame.columns:
        frame = frame.copy()
        frame["y_pred"] = frame["prediction_score"]
    required = {"sample_id", "instrument_id", "as_of_date", "y_pred"}
    missing = required - set(frame.columns)
    if missing:
        raise PredictionProvenanceError(f"prediction CSV missing columns: {sorted(missing)}")
    if fold_aware and "fold_id" not in frame.columns:
        raise PredictionProvenanceError("development OOS predictions require fold_id provenance")

    frame = frame.copy()
    frame["sample_id"] = frame["sample_id"].astype(int)
    frame["instrument_id"] = frame["instrument_id"].astype(int)
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    frame["y_pred"] = frame["y_pred"].astype(float)
    frame = frame.dropna(subset=["y_pred"])

    computed = prediction_hash(frame)
    recorded = marker.get(hash_key)
    if expected_prediction_hash and expected_prediction_hash not in {computed, recorded}:
        raise PredictionProvenanceError(
            f"prediction hash mismatch: expected={expected_prediction_hash} "
            f"computed={computed} recorded={recorded}"
        )

    return PredictionBundle(
        segment=segment,
        artifact_dir=base,
        candidate_config_hash=candidate_config_hash,
        dataset_values_hash=dataset_values_hash,
        prediction_hash=computed,
        frame=frame,
        fold_aware=fold_aware,
        prediction_semantic=prediction_semantic,
        candidate_name=cand_name,
        candidate_version=cand_version,
    )


def signals_for_date(
    bundle: PredictionBundle,
    decision_date: date,
    *,
    ticker_by_id: dict[int, str],
) -> list[PredictionSignal]:
    """Exact as_of_date match only — no forward-fill."""
    day = bundle.frame[bundle.frame["as_of_date"] == decision_date]
    out: list[PredictionSignal] = []
    semantic = bundle.prediction_semantic
    for row in day.itertuples(index=False):
        iid = int(row.instrument_id)
        ticker = ticker_by_id.get(iid)
        if not ticker:
            continue
        fold_id = None
        if bundle.fold_aware and "fold_id" in bundle.frame.columns:
            fold_id = str(row.fold_id)
        sample_id = int(row.sample_id)
        score = float(row.y_pred)
        if semantic == "RANKING_SCORE":
            out.append(
                PredictionSignal(
                    instrument_id=iid,
                    ticker=ticker,
                    as_of_date=decision_date,
                    predicted_return_20d=0.0,
                    fold_id=fold_id,
                    sample_id=sample_id,
                    metadata={"segment": bundle.segment, "candidate_version": bundle.candidate_version},
                    prediction_semantic="RANKING_SCORE",
                    prediction_score=score,
                )
            )
        else:
            out.append(
                PredictionSignal(
                    instrument_id=iid,
                    ticker=ticker,
                    as_of_date=decision_date,
                    predicted_return_20d=score,
                    fold_id=fold_id,
                    sample_id=sample_id,
                    metadata={"segment": bundle.segment},
                    prediction_semantic="EXPECTED_RETURN",
                )
            )
    return out


def prediction_date_bounds(bundle: PredictionBundle) -> tuple[date, date]:
    dates = sorted(set(bundle.frame["as_of_date"].tolist()))
    if not dates:
        raise PredictionProvenanceError("empty prediction bundle")
    return dates[0], dates[-1]


def summarize_bundle(bundle: PredictionBundle) -> dict[str, Any]:
    d0, d1 = prediction_date_bounds(bundle)
    return {
        "segment": bundle.segment,
        "artifact_dir": str(bundle.artifact_dir),
        "candidate_config_hash": bundle.candidate_config_hash,
        "dataset_values_hash": bundle.dataset_values_hash,
        "prediction_hash": bundle.prediction_hash,
        "rows": int(len(bundle.frame)),
        "date_from": d0.isoformat(),
        "date_to": d1.isoformat(),
        "fold_aware": bundle.fold_aware,
    }
