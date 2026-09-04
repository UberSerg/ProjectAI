"""Durable Candidate V0 artifact storage under MODELS_DATA_PATH."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings


def candidate_artifact_dir(
    *,
    candidate_name: str,
    candidate_version: str,
    config_hash: str,
    root: Path | None = None,
) -> Path:
    base = root or Path(get_settings().models_data_path)
    return base / candidate_name / candidate_version / config_hash[:16]


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(v) for v in obj]
        if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
            return None
        return obj

    path.write_text(
        json.dumps(_clean(payload), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def prediction_hash(frame: pd.DataFrame, *, pred_col: str = "y_pred") -> str:
    cols = ["sample_id", "instrument_id", "as_of_date", pred_col]
    subset = frame.loc[:, [c for c in cols if c in frame.columns]].copy()
    subset["sample_id"] = subset["sample_id"].astype(int)
    subset["instrument_id"] = subset["instrument_id"].astype(int)
    subset["as_of_date"] = pd.to_datetime(subset["as_of_date"]).dt.strftime("%Y-%m-%d")
    subset[pred_col] = subset[pred_col].map(lambda x: f"{float(x):.12g}")
    canonical = subset.sort_values(["as_of_date", "instrument_id", "sample_id"]).to_csv(
        index=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def persist_candidate_bundle(
    *,
    out_dir: Path,
    config_payload: dict[str, Any],
    walk_forward_metrics: dict[str, Any],
    holdout_metrics: dict[str, Any],
    feature_importance: dict[str, float],
    development_predictions: pd.DataFrame | None,
    holdout_predictions: pd.DataFrame | None,
    research_verdict: str,
    timings: dict[str, float],
    model_path: Path,
    holdout_evaluated: bool = True,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "candidate_config.json", config_payload)
    write_json(out_dir / "walk_forward_metrics.json", walk_forward_metrics)
    write_json(out_dir / "holdout_metrics.json", holdout_metrics)
    write_json(
        out_dir / "feature_importance.json",
        {
            "importance_is_causal": False,
            "note": "CatBoost feature importance ≠ causality",
            "values": feature_importance,
            "top_20": sorted(feature_importance.items(), key=lambda x: -x[1])[:20],
        },
    )
    if development_predictions is not None and not development_predictions.empty:
        development_predictions.to_csv(out_dir / "predictions_development.csv", index=False)
    if holdout_predictions is not None and not holdout_predictions.empty:
        holdout_predictions.to_csv(out_dir / "predictions_holdout.csv", index=False)
    marker = {
        "holdout_evaluated": holdout_evaluated,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "research_verdict": research_verdict,
        "model_artifact": str(model_path),
        "timings": timings,
        "development_prediction_hash": (
            prediction_hash(development_predictions)
            if development_predictions is not None and not development_predictions.empty
            else None
        ),
        "holdout_prediction_hash": (
            prediction_hash(holdout_predictions)
            if holdout_predictions is not None and not holdout_predictions.empty
            else None
        ),
    }
    write_json(out_dir / "holdout_evaluated_marker.json", marker)
    write_json(out_dir / "feature_list.json", {"features": config_payload.get("feature_names", [])})
    return marker
