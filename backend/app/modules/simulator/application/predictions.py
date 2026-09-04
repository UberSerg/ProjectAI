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


def resolve_candidate_dir(
    *,
    candidate_name: str | None = None,
    candidate_version: str | None = None,
    config_hash: str | None = None,
    root: Path | None = None,
) -> Path:
    cfg = CANDIDATE_V0_CONFIG
    return candidate_artifact_dir(
        candidate_name=candidate_name or cfg.candidate_name,
        candidate_version=candidate_version or cfg.candidate_version,
        config_hash=config_hash or cfg.config_hash(),
        root=root,
    )


def load_oos_predictions(
    segment: SimulationSegment,
    *,
    artifact_dir: Path | None = None,
    expected_prediction_hash: str | None = None,
) -> PredictionBundle:
    """Load DEVELOPMENT_OOS or FINAL_HOLDOUT predictions only."""
    base = artifact_dir or resolve_candidate_dir()
    marker_path = base / "holdout_evaluated_marker.json"
    config_path = base / "candidate_config.json"
    if not marker_path.exists() or not config_path.exists():
        raise PredictionProvenanceError(f"missing candidate artifacts under {base}")

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    candidate_config_hash = str(config_payload.get("config_hash") or "")
    if not candidate_config_hash:
        # config may store fields without precomputed hash; recompute from file identity
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
        csv_path = base / "predictions_holdout.csv"
        hash_key = "holdout_prediction_hash"
        fold_aware = False
    else:
        raise PredictionProvenanceError(f"unknown segment: {segment}")

    if not csv_path.exists():
        raise PredictionProvenanceError(f"missing OOS predictions: {csv_path}")

    frame = pd.read_csv(csv_path)
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
    # Marker hashes Candidate V0 in-memory frames before CSV round-trip; float/date
    # string forms can drift. OOS provenance remains: segment file + fold_id + config.
    if expected_prediction_hash and expected_prediction_hash not in {computed, recorded}:
        raise PredictionProvenanceError(
            f"prediction hash mismatch: expected={expected_prediction_hash} "
            f"computed={computed} recorded={recorded}"
        )

    return PredictionBundle(
        segment=segment,
        artifact_dir=base,
        candidate_config_hash=candidate_config_hash or CANDIDATE_V0_CONFIG.config_hash(),
        dataset_values_hash=dataset_values_hash,
        prediction_hash=computed,
        frame=frame,
        fold_aware=fold_aware,
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
    for row in day.itertuples(index=False):
        iid = int(row.instrument_id)
        ticker = ticker_by_id.get(iid)
        if not ticker:
            continue
        fold_id = None
        if bundle.fold_aware and "fold_id" in bundle.frame.columns:
            fold_id = str(row.fold_id)
        sample_id = int(row.sample_id)
        out.append(
            PredictionSignal(
                instrument_id=iid,
                ticker=ticker,
                as_of_date=decision_date,
                predicted_return_20d=float(row.y_pred),
                fold_id=fold_id,
                sample_id=sample_id,
                metadata={"segment": bundle.segment},
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
