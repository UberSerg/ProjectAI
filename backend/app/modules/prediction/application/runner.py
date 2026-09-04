"""Offline Candidate V0 walk-forward + holdout runner."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.modules.prediction.application.baselines import RidgeBaseline, TrainMeanBaseline, ZeroBaseline
from app.modules.prediction.application.dataset_loader import (
    assert_no_label_leakage_in_features,
    feature_matrix,
    load_candidate_frame,
)
from app.modules.prediction.application.metrics import evaluate_predictions
from app.modules.prediction.application.splits import (
    build_expanding_folds,
    count_purged_at_boundary,
    select_eval_rows,
    select_train_rows,
)
from app.modules.prediction.application.verdict import decide_research_verdict
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config
from app.modules.prediction.infrastructure.artifacts import (
    candidate_artifact_dir,
    persist_candidate_bundle,
)
from app.modules.prediction.infrastructure.catboost_adapter import CatBoostRegressorAdapter
from app.modules.prediction.infrastructure.registry import upsert_model_registry_row


def _sanitize(obj: Any) -> Any:
    """Replace NaN/Inf with None for JSON-safe metrics payloads."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    if isinstance(obj, np.floating):
        val = float(obj)
        if val != val or val in (float("inf"), float("-inf")):
            return None
        return val
    return obj


def _eval_model(
    model: Any,
    frame: pd.DataFrame,
    config: CandidateV0Config,
    *,
    pred_col: str = "y_pred",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = frame.copy()
    x = feature_matrix(out, config)
    out[pred_col] = model.predict(x) if hasattr(model, "predict") else model.predict_many(x)
    metrics = evaluate_predictions(
        out,
        min_ic_instruments=config.min_ic_instruments,
        top_bottom_quantile=config.top_bottom_quantile,
        pred_col=pred_col,
    )
    return out, metrics


def _annual_diagnostics(preds: pd.DataFrame, config: CandidateV0Config) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if preds.empty:
        return rows
    tmp = preds.copy()
    tmp["year"] = pd.to_datetime(tmp["as_of_date"]).dt.year
    for year, group in tmp.groupby("year"):
        metrics = evaluate_predictions(
            group,
            min_ic_instruments=config.min_ic_instruments,
            top_bottom_quantile=config.top_bottom_quantile,
        )
        rows.append(
            {
                "year": int(year),
                "samples": int(len(group)),
                "mae": metrics["mae"],
                "rmse": metrics["rmse"],
                "mean_ic": metrics["rank_ic"]["mean_ic"],
                "positive_ic_pct": metrics["rank_ic"]["positive_ic_pct"],
            }
        )
    return rows


def _instrument_diagnostics(preds: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if preds.empty:
        return rows
    for instrument_id, group in preds.groupby("instrument_id"):
        y = group["y"].to_numpy(dtype=float)
        p = group["y_pred"].to_numpy(dtype=float)
        err = p - y
        sign_ok = np.mean(np.sign(p[y != 0]) == np.sign(y[y != 0])) if np.any(y != 0) else float("nan")
        rows.append(
            {
                "instrument_id": int(instrument_id),
                "samples": int(len(group)),
                "mae": float(np.mean(np.abs(err))),
                "mean_prediction": float(np.mean(p)),
                "mean_actual": float(np.mean(y)),
                "directional_accuracy": float(sign_ok),
            }
        )
    rows.sort(key=lambda r: r["mae"])
    return rows


def run_candidate_v0(
    session: Session,
    *,
    config: CandidateV0Config | None = None,
    artifact_root: Path | None = None,
    smoke: bool = False,
    smoke_train_start: date | None = None,
    smoke_train_end: date | None = None,
    smoke_val_start: date | None = None,
    smoke_val_end: date | None = None,
) -> dict[str, Any]:
    """Train/evaluate Candidate V0. ``smoke=True`` runs a single bounded fold only."""
    cfg = config or CANDIDATE_V0_CONFIG
    assert_no_label_leakage_in_features(cfg)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    run, frame = load_candidate_frame(session, cfg)
    timings["dataset_load_sec"] = round(time.perf_counter() - t0, 3)

    eligible = frame["y"].notna() & frame["label_valid_20d"] & frame["eligible_20d"]
    data_start = frame.loc[eligible, "as_of_date"].min()
    holdout_start = cfg.holdout_start

    if smoke:
        train_start = smoke_train_start or date(2019, 1, 1)
        train_end = smoke_train_end or date(2022, 1, 1)
        val_start = smoke_val_start or date(2022, 1, 1)
        val_end = smoke_val_end or date(2022, 7, 1)
        folds_meta = [
            {
                "fold_id": 0,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "validation_start": val_start.isoformat(),
                "validation_end": val_end.isoformat(),
            }
        ]
        fold_specs = [(train_start, train_end, val_start, val_end)]
    else:
        folds = build_expanding_folds(
            data_start=data_start,
            development_end_exclusive=holdout_start,
            config=cfg,
        )
        folds_meta = [f.to_dict() for f in folds]
        fold_specs = [
            (f.train_start, f.train_end, f.validation_start, f.validation_end) for f in folds
        ]

    t_wf = time.perf_counter()
    fold_reports: list[dict[str, Any]] = []
    dev_pred_parts: list[pd.DataFrame] = []
    fold_ics: list[float] = []

    for fold_id, (train_start, train_end, val_start, val_end) in enumerate(fold_specs):
        train_df = select_train_rows(
            frame,
            as_of_end_exclusive=train_end,
            target_must_be_before=val_start,
            config=cfg,
        )
        # Restrict train_start for smoke clarity
        if smoke:
            train_df = train_df.loc[train_df["as_of_date"] >= train_start]
        val_df = select_eval_rows(
            frame, as_of_start=val_start, as_of_end_exclusive=val_end, config=cfg
        )
        purged = count_purged_at_boundary(
            frame,
            as_of_end_exclusive=train_end,
            target_must_be_before=val_start,
            config=cfg,
        )
        report: dict[str, Any] = {
            "fold_id": fold_id,
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "validation_start": val_start.isoformat(),
            "validation_end": val_end.isoformat(),
            "train_n": int(len(train_df)),
            "val_n": int(len(val_df)),
            "purged": purged,
            "instruments_train": int(train_df["instrument_id"].nunique()) if len(train_df) else 0,
            "instruments_val": int(val_df["instrument_id"].nunique()) if len(val_df) else 0,
        }
        if len(train_df) < 100 or len(val_df) < 20:
            report["status"] = "invalid"
            report["reason"] = "insufficient_samples"
            fold_reports.append(report)
            continue

        x_train = feature_matrix(train_df, cfg)
        y_train = train_df["y"].to_numpy(dtype=float)

        cat = CatBoostRegressorAdapter(
            model_id=cfg.candidate_name,
            model_version=cfg.candidate_version,
            hyperparameters=cfg.catboost_hyperparameters,
            feature_names=list(cfg.feature_names),
        )
        cat.fit(x_train, y_train)
        val_pred, cat_metrics = _eval_model(cat, val_df, cfg)
        report["status"] = "ok"
        report["catboost"] = cat_metrics
        fold_ics.append(float(cat_metrics["rank_ic"]["mean_ic"]))

        baselines: dict[str, Any] = {}
        for baseline in (
            ZeroBaseline(),
            TrainMeanBaseline(),
            RidgeBaseline(alpha=cfg.ridge_alpha, random_state=cfg.random_seed),
        ):
            baseline.fit(x_train, y_train)
            _, bmetrics = _eval_model(baseline, val_df, cfg)
            baselines[baseline.name] = bmetrics
        report["baselines"] = baselines
        fold_reports.append(report)
        tagged = val_pred.copy()
        tagged["fold_id"] = fold_id
        dev_pred_parts.append(tagged)

    timings["walk_forward_sec"] = round(time.perf_counter() - t_wf, 3)
    development_predictions = (
        pd.concat(dev_pred_parts, ignore_index=True) if dev_pred_parts else pd.DataFrame()
    )
    development_metrics: dict[str, Any]
    if development_predictions.empty:
        development_metrics = {"status": "no_valid_folds", "folds": fold_reports}
    else:
        development_metrics = evaluate_predictions(
            development_predictions,
            min_ic_instruments=cfg.min_ic_instruments,
            top_bottom_quantile=cfg.top_bottom_quantile,
        )
        # Aggregate baseline metrics on pooled development predictions using last fold's
        # train_mean is fold-specific; report fold-level baselines instead.
        development_metrics["folds"] = fold_reports
        development_metrics["baselines"] = {
            "note": "baseline metrics are per-fold; see folds[].baselines",
            "zero": {"rank_ic": {"mean_ic": 0.0}},
            "train_mean": {
                "rank_ic": {
                    "mean_ic": float(
                        np.nanmean(
                            [
                                ((f.get("baselines") or {}).get("train_mean") or {})
                                .get("rank_ic", {})
                                .get("mean_ic", float("nan"))
                                for f in fold_reports
                                if f.get("status") == "ok"
                            ]
                        )
                    )
                }
            },
        }
        development_metrics["annual"] = _annual_diagnostics(development_predictions, cfg)
        development_metrics["by_instrument"] = _instrument_diagnostics(development_predictions)

    # Freeze config hash before holdout
    config_payload = cfg.to_dict()
    config_payload["config_hash"] = cfg.config_hash()
    config_payload["feature_schema_hash"] = cfg.feature_schema_hash()
    config_payload["dataset_run_id"] = run.id
    config_payload["folds"] = folds_meta
    config_payload["smoke"] = smoke

    holdout_metrics: dict[str, Any]
    holdout_predictions = pd.DataFrame()
    feature_importance: dict[str, float] = {}
    model_path = Path(".")
    if smoke:
        holdout_metrics = {"status": "skipped_for_smoke"}
        research_verdict, verdict_reason = "MIXED", "smoke run only"
        final_model = None
        holdout_evaluated_flag = False
    else:
        holdout_evaluated_flag = True
        t_fit = time.perf_counter()
        train_final = select_train_rows(
            frame,
            as_of_end_exclusive=holdout_start,
            target_must_be_before=holdout_start,
            config=cfg,
        )
        holdout_df = select_eval_rows(
            frame,
            as_of_start=holdout_start,
            as_of_end_exclusive=date(2100, 1, 1),
            config=cfg,
        )
        final_model = CatBoostRegressorAdapter(
            model_id=cfg.candidate_name,
            model_version=cfg.candidate_version,
            hyperparameters=cfg.catboost_hyperparameters,
            feature_names=list(cfg.feature_names),
        )
        final_model.fit(feature_matrix(train_final, cfg), train_final["y"].to_numpy(dtype=float))
        timings["final_fit_sec"] = round(time.perf_counter() - t_fit, 3)
        feature_importance = final_model.feature_importance()

        t_ho = time.perf_counter()
        holdout_predictions, holdout_metrics = _eval_model(final_model, holdout_df, cfg)
        # Baselines on holdout with train-only fit
        x_tr = feature_matrix(train_final, cfg)
        y_tr = train_final["y"].to_numpy(dtype=float)
        holdout_baselines: dict[str, Any] = {}
        for baseline in (
            ZeroBaseline(),
            TrainMeanBaseline(),
            RidgeBaseline(alpha=cfg.ridge_alpha, random_state=cfg.random_seed),
        ):
            baseline.fit(x_tr, y_tr)
            _, bmetrics = _eval_model(baseline, holdout_df, cfg)
            holdout_baselines[baseline.name] = bmetrics
        holdout_metrics["baselines"] = holdout_baselines
        holdout_metrics["train_n"] = int(len(train_final))
        holdout_metrics["holdout_n"] = int(len(holdout_df))
        holdout_metrics["purged_at_holdout"] = count_purged_at_boundary(
            frame,
            as_of_end_exclusive=holdout_start,
            target_must_be_before=holdout_start,
            config=cfg,
        )
        holdout_metrics["period"] = {
            "start": holdout_start.isoformat(),
            "end": (
                holdout_df["as_of_date"].max().isoformat()
                if len(holdout_df)
                else None
            ),
        }
        timings["holdout_sec"] = round(time.perf_counter() - t_ho, 3)
        research_verdict, verdict_reason = decide_research_verdict(
            development=development_metrics,
            holdout=holdout_metrics,
            fold_ics=fold_ics,
        )

    out_dir = candidate_artifact_dir(
        candidate_name=cfg.candidate_name,
        candidate_version=cfg.candidate_version,
        config_hash=cfg.config_hash(),
        root=artifact_root,
    )
    if final_model is not None:
        model_path = out_dir / "model.cbm"
        final_model.save(model_path)
        # Round-trip sanity
        loaded = CatBoostRegressorAdapter.load(
            model_path,
            model_id=cfg.candidate_name,
            model_version=cfg.candidate_version,
            hyperparameters=cfg.catboost_hyperparameters,
            feature_names=list(cfg.feature_names),
        )
        if len(holdout_predictions):
            x_ho = feature_matrix(holdout_predictions, cfg)
            a = final_model.predict_many(x_ho)
            b = loaded.predict_many(x_ho)
            if not np.allclose(a, b, rtol=0, atol=1e-12):
                raise RuntimeError("CatBoost artifact round-trip mismatch")

    timings["total_sec"] = round(time.perf_counter() - t0, 3)
    marker = persist_candidate_bundle(
        out_dir=out_dir,
        config_payload=config_payload,
        walk_forward_metrics=_sanitize(development_metrics),
        holdout_metrics=_sanitize(holdout_metrics),
        feature_importance=feature_importance,
        development_predictions=development_predictions[
            ["sample_id", "instrument_id", "as_of_date", "y", "y_pred", "fold_id"]
        ]
        if not development_predictions.empty
        else development_predictions,
        holdout_predictions=holdout_predictions[
            ["sample_id", "instrument_id", "as_of_date", "y", "y_pred"]
        ]
        if not holdout_predictions.empty
        else holdout_predictions,
        research_verdict=research_verdict,
        timings=timings,
        model_path=model_path,
        holdout_evaluated=holdout_evaluated_flag,
    )

    if not smoke:
        upsert_model_registry_row(
            session,
            model_name=cfg.candidate_name,
            model_version=cfg.candidate_version,
            parameters={
                "config_hash": cfg.config_hash(),
                "feature_schema_hash": cfg.feature_schema_hash(),
                "hyperparameters": cfg.catboost_hyperparameters,
                "artifact_dir": str(out_dir),
                "dataset_values_hash": cfg.required_values_hash,
                "target": cfg.target,
                "research_verdict": research_verdict,
            },
            training_dataset=f"{cfg.dataset_spec_code}:v{cfg.dataset_spec_version}:run{run.id}",
            metrics={
                "dev_mean_ic": float(
                    (development_metrics.get("rank_ic") or {}).get("mean_ic") or float("nan")
                ),
                "holdout_mean_ic": float(
                    (holdout_metrics.get("rank_ic") or {}).get("mean_ic") or float("nan")
                ),
            },
            status="evaluated",
        )
        session.commit()

    return {
        "dataset_run_id": run.id,
        "values_hash": cfg.required_values_hash,
        "config_hash": cfg.config_hash(),
        "artifact_dir": str(out_dir),
        "timings": timings,
        "development": development_metrics,
        "holdout": holdout_metrics,
        "research_verdict": research_verdict,
        "verdict_reason": verdict_reason,
        "marker": marker,
        "eligibility": {
            "total_samples": int(len(frame)),
            "eligible_20d": int(eligible.sum()),
            "development_predictions": int(len(development_predictions)),
            "holdout_predictions": int(len(holdout_predictions)),
        },
        "feature_importance_top20": sorted(feature_importance.items(), key=lambda x: -x[1])[:20],
    }
