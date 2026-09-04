"""Prediction ML Candidate V0 unit tests (no live external APIs)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.modules.prediction.application.baselines import TrainMeanBaseline, ZeroBaseline
from app.modules.prediction.application.metrics import (
    cross_sectional_ic,
    evaluate_predictions,
    top_bottom_spread,
)
from app.modules.prediction.application.splits import (
    build_expanding_folds,
    count_purged_at_boundary,
    select_eval_rows,
    select_train_rows,
)
from app.modules.prediction.application.verdict import decide_research_verdict
from app.modules.prediction.candidate_config import (
    CANDIDATE_V0_CONFIG,
    CANONICAL_DATASET_VALUES_HASH,
    TARGET_LABEL,
)
from app.modules.prediction.infrastructure.catboost_adapter import CatBoostRegressorAdapter


def test_candidate_pins_dataset_v2_contract() -> None:
    cfg = CANDIDATE_V0_CONFIG
    assert cfg.dataset_spec_code == "pit_daily_core"
    assert cfg.dataset_spec_version == 2
    assert cfg.required_values_hash == CANONICAL_DATASET_VALUES_HASH
    assert cfg.target == TARGET_LABEL == "forward_return_20d"
    assert len(cfg.feature_names) == 90
    assert not any(n.startswith("forward_return_") for n in cfg.feature_names)
    assert not any(n.startswith("target_date_") for n in cfg.feature_names)


def test_config_hash_stable() -> None:
    a = CANDIDATE_V0_CONFIG.config_hash()
    b = CANDIDATE_V0_CONFIG.config_hash()
    assert a == b
    assert len(a) == 64


def test_no_random_split_in_fold_builder() -> None:
    folds = build_expanding_folds(
        data_start=date(2014, 1, 6),
        development_end_exclusive=date(2026, 1, 1),
        config=CANDIDATE_V0_CONFIG,
    )
    assert folds
    assert folds[0].validation_start == date(2017, 1, 1)
    # Expanding: each next fold keeps same train_start, later validation
    assert all(f.train_start == date(2014, 1, 6) for f in folds)
    for i in range(1, len(folds)):
        assert folds[i].validation_start >= folds[i - 1].validation_start
        assert folds[i].train_end == folds[i].validation_start
    assert folds[-1].validation_end <= date(2026, 1, 1)


def test_holdout_boundary_constant() -> None:
    assert CANDIDATE_V0_CONFIG.holdout_start == date(2026, 1, 1)


def _toy_frame() -> pd.DataFrame:
    rows = []
    for i, d in enumerate(
        [
            date(2020, 1, 2),
            date(2020, 1, 3),
            date(2020, 6, 1),
            date(2020, 6, 2),
            date(2021, 1, 4),
            date(2021, 1, 5),
        ]
    ):
        for inst in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
            rows.append(
                {
                    "sample_id": i * 100 + inst,
                    "instrument_id": inst,
                    "as_of_date": d,
                    "y": 0.01 * inst + 0.001 * i,
                    "target_date_20d": date(d.year, d.month, min(28, d.day + 20))
                    if d.month < 12
                    else date(d.year + 1, 1, 15),
                    "label_valid_20d": True,
                    "eligible_20d": True,
                    **{name: float(inst) for name in CANDIDATE_V0_CONFIG.feature_names},
                }
            )
    return pd.DataFrame(rows)


def test_target_date_purge_before_validation() -> None:
    frame = _toy_frame()
    # Force one train-as_of row whose target crosses validation start
    frame.loc[0, "as_of_date"] = date(2020, 5, 20)
    frame.loc[0, "target_date_20d"] = date(2020, 6, 15)
    val_start = date(2020, 6, 1)
    train = select_train_rows(
        frame,
        as_of_end_exclusive=val_start,
        target_must_be_before=val_start,
        config=CANDIDATE_V0_CONFIG,
    )
    assert (train["target_date_20d"] < val_start).all()
    purged = count_purged_at_boundary(
        frame,
        as_of_end_exclusive=val_start,
        target_must_be_before=val_start,
        config=CANDIDATE_V0_CONFIG,
    )
    assert purged >= 1


def test_holdout_train_targets_do_not_cross() -> None:
    frame = _toy_frame()
    holdout = date(2021, 1, 1)
    train = select_train_rows(
        frame,
        as_of_end_exclusive=holdout,
        target_must_be_before=holdout,
        config=CANDIDATE_V0_CONFIG,
    )
    assert (train["target_date_20d"] < holdout).all()
    eval_df = select_eval_rows(
        frame, as_of_start=holdout, as_of_end_exclusive=date(2022, 1, 1), config=CANDIDATE_V0_CONFIG
    )
    assert (eval_df["as_of_date"] >= holdout).all()


def test_train_mean_baseline_uses_train_only() -> None:
    x = np.zeros((5, 3))
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    model = TrainMeanBaseline().fit(x, y)
    pred = model.predict(np.zeros((2, 3)))
    assert np.allclose(pred, 3.0)


def test_zero_baseline() -> None:
    pred = ZeroBaseline().fit(np.zeros((3, 2)), np.ones(3)).predict(np.zeros((4, 2)))
    assert np.allclose(pred, 0.0)


def test_rank_ic_and_min_instruments() -> None:
    rows = []
    d = date(2024, 1, 2)
    for inst in range(1, 12):
        rows.append({"as_of_date": d, "y": float(inst), "y_pred": float(inst)})
    # Small cross-section day should be skipped
    for inst in range(1, 5):
        rows.append({"as_of_date": date(2024, 1, 3), "y": float(inst), "y_pred": float(inst)})
    frame = pd.DataFrame(rows)
    ic = cross_sectional_ic(frame, min_instruments=10)
    assert ic["n_dates"] == 1
    assert ic["skipped_dates"] >= 1
    assert ic["mean_ic"] == pytest.approx(1.0)


def test_top_bottom_diagnostic() -> None:
    rows = []
    d = date(2024, 2, 1)
    for inst in range(1, 21):
        rows.append({"as_of_date": d, "y": float(inst), "y_pred": float(inst)})
    out = top_bottom_spread(pd.DataFrame(rows), quantile=0.2)
    assert out["top_minus_bottom"] > 0
    assert "not Simulator" in out["note"]


def test_catboost_round_trip(tmp_path: Path) -> None:
    cfg = CANDIDATE_V0_CONFIG
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, len(cfg.feature_names)))
    y = x[:, 0] * 0.1 + rng.normal(scale=0.01, size=200)
    model = CatBoostRegressorAdapter(
        model_id="t",
        model_version="v0",
        hyperparameters={**cfg.catboost_hyperparameters, "iterations": 50},
        feature_names=list(cfg.feature_names),
    )
    model.fit(x, y)
    path = tmp_path / "m.cbm"
    model.save(path)
    loaded = CatBoostRegressorAdapter.load(
        path,
        model_id="t",
        model_version="v0",
        hyperparameters=cfg.catboost_hyperparameters,
        feature_names=list(cfg.feature_names),
    )
    assert np.allclose(model.predict_many(x[:5]), loaded.predict_many(x[:5]), atol=1e-12)
    # Domain predict_one does not touch DB
    out = loaded.predict_one(x[0])
    assert isinstance(out.expected_return, float)


def test_verdict_no_edge() -> None:
    development = {
        "rank_ic": {"mean_ic": -0.05},
        "baselines": {
            "zero": {"rank_ic": {"mean_ic": 0.0}},
            "train_mean": {"rank_ic": {"mean_ic": 0.0}},
        },
    }
    verdict, _ = decide_research_verdict(
        development=development,
        holdout={"rank_ic": {"mean_ic": -0.04}},
        fold_ics=[-0.1, -0.2, 0.01],
    )
    assert verdict == "NO_EDGE"


def test_evaluate_predictions_bundle() -> None:
    rows = []
    for day in range(1, 6):
        d = date(2024, 3, day)
        for inst in range(1, 15):
            rows.append(
                {
                    "as_of_date": d,
                    "y": float(inst) / 100.0,
                    "y_pred": float(inst) / 100.0 + 0.001,
                }
            )
    metrics = evaluate_predictions(
        pd.DataFrame(rows),
        min_ic_instruments=10,
        top_bottom_quantile=0.2,
    )
    assert "mae" in metrics and "rank_ic" in metrics and "top_bottom" in metrics
