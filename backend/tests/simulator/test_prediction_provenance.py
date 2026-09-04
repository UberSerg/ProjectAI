"""OOS prediction provenance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.modules.prediction.infrastructure.artifacts import prediction_hash
from app.modules.simulator.application.predictions import (
    PredictionProvenanceError,
    load_oos_predictions,
)


def _write_bundle(tmp: Path, *, with_fold: bool) -> str:
    rows = [
        {"sample_id": 1, "instrument_id": 10, "as_of_date": "2024-01-02", "y_pred": 0.1},
        {"sample_id": 2, "instrument_id": 11, "as_of_date": "2024-01-02", "y_pred": 0.2},
    ]
    if with_fold:
        for r in rows:
            r["fold_id"] = "fold_0"
    frame = pd.DataFrame(rows)
    ph = prediction_hash(frame)
    frame.to_csv(tmp / "predictions_development.csv", index=False)
    hold = frame.drop(columns=["fold_id"], errors="ignore")
    hold.to_csv(tmp / "predictions_holdout.csv", index=False)
    (tmp / "candidate_config.json").write_text(
        json.dumps(
            {
                "config_hash": "abc",
                "required_values_hash": "values",
            }
        ),
        encoding="utf-8",
    )
    (tmp / "holdout_evaluated_marker.json").write_text(
        json.dumps(
            {
                "development_prediction_hash": ph,
                "holdout_prediction_hash": prediction_hash(hold),
            }
        ),
        encoding="utf-8",
    )
    return ph


def test_load_development_requires_fold_id(tmp_path: Path) -> None:
    _write_bundle(tmp_path, with_fold=False)
    # overwrite development without fold
    pd.DataFrame(
        [{"sample_id": 1, "instrument_id": 10, "as_of_date": "2024-01-02", "y_pred": 0.1}]
    ).to_csv(tmp_path / "predictions_development.csv", index=False)
    with pytest.raises(PredictionProvenanceError, match="fold_id"):
        load_oos_predictions("DEVELOPMENT_OOS", artifact_dir=tmp_path)


def test_load_oos_hash_and_segment(tmp_path: Path) -> None:
    ph = _write_bundle(tmp_path, with_fold=True)
    dev = load_oos_predictions("DEVELOPMENT_OOS", artifact_dir=tmp_path)
    assert dev.segment == "DEVELOPMENT_OOS"
    assert dev.fold_aware is True
    assert dev.prediction_hash == ph
    hold = load_oos_predictions("FINAL_HOLDOUT", artifact_dir=tmp_path)
    assert hold.segment == "FINAL_HOLDOUT"
    assert hold.fold_aware is False
    with pytest.raises(PredictionProvenanceError):
        load_oos_predictions(
            "DEVELOPMENT_OOS",
            artifact_dir=tmp_path,
            expected_prediction_hash="0" * 64,
        )
