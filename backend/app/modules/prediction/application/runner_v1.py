"""Offline Candidate V1 Ranker walk-forward (DEVELOPMENT only — no FINAL_HOLDOUT)."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.modules.prediction.application.dataset_loader import (
    assert_no_label_leakage_in_features,
    feature_matrix,
    load_candidate_frame,
)
from app.modules.prediction.application.metrics import (
    cross_sectional_ic,
    top_bottom_spread,
)
from app.modules.prediction.application.relevance import (
    cross_sectional_percentile_relevance,
    group_id_codes,
)
from app.modules.prediction.application.splits import (
    build_expanding_folds,
    count_purged_at_boundary,
    select_eval_rows,
    select_train_rows,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG, CandidateV1RankerConfig
from app.modules.prediction.infrastructure.artifacts import (
    candidate_artifact_dir,
    persist_candidate_bundle,
    prediction_hash,
    write_json,
)
from app.modules.prediction.infrastructure.catboost_ranker_adapter import CatBoostRankerAdapter
from app.modules.prediction.infrastructure.registry import upsert_model_registry_row


def _sanitize(obj: Any) -> Any:
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


def _assert_groups_intact(train_df: pd.DataFrame, val_df: pd.DataFrame) -> None:
    train_dates = set(train_df["as_of_date"].unique()) if len(train_df) else set()
    val_dates = set(val_df["as_of_date"].unique()) if len(val_df) else set()
    overlap = train_dates & val_dates
    if overlap:
        raise RuntimeError(f"ranking group leakage across folds: {sorted(overlap)[:5]}")


def _ranking_metrics(frame: pd.DataFrame, *, min_ic: int, top_q: float) -> dict[str, Any]:
    """Rank-IC / top-bottom only — no MAE/RMSE/R² (score ≠ return)."""
    ic = cross_sectional_ic(frame, min_instruments=min_ic, pred_col="y_pred", actual_col="y")
    spread = top_bottom_spread(
        frame, quantile=top_q, pred_col="y_pred", actual_col="y"
    )
    return {
        "prediction_semantic": "RANKING_SCORE",
        "rank_ic": ic,
        "top_bottom": spread,
        "n": int(len(frame)),
        "regression_metrics_skipped": True,
        "regression_metrics_note": (
            "MAE/RMSE/R² and sign accuracy are semantically invalid for RANKING_SCORE."
        ),
    }


def _daily_spearman_ic(
    frame: pd.DataFrame,
    *,
    pred_col: str,
    min_ic: int,
) -> dict[Any, float]:
    """One Spearman IC per as_of_date (skip thin/degenerate cross-sections)."""
    out: dict[Any, float] = {}
    for as_of, group in frame.groupby("as_of_date", sort=True):
        if len(group) < min_ic:
            continue
        if group[pred_col].nunique(dropna=True) < 2 or group["y"].nunique(dropna=True) < 2:
            continue
        corr = float(group[pred_col].rank().corr(group["y"].rank(), method="pearson"))
        if corr == corr:
            out[as_of] = corr
    return out


def _bootstrap_ic_delta(
    v1: pd.DataFrame,
    v0: pd.DataFrame,
    *,
    min_ic: int,
    seed: int,
    iterations: int,
) -> dict[str, Any]:
    """Bootstrap by trading date for mean(IC_V1 - IC_V0).

    Precomputes daily ICs once, then resamples date-level deltas (O(iterations × dates)).
    """
    if v1.empty or v0.empty:
        return {"status": "insufficient"}
    merged = v1[["as_of_date", "instrument_id", "y_pred", "y"]].merge(
        v0[["as_of_date", "instrument_id", "y_pred"]].rename(columns={"y_pred": "y_pred_v0"}),
        on=["as_of_date", "instrument_id"],
        how="inner",
    )
    ic1_by_date = _daily_spearman_ic(merged, pred_col="y_pred", min_ic=min_ic)
    ic0_by_date = _daily_spearman_ic(merged, pred_col="y_pred_v0", min_ic=min_ic)
    common = sorted(set(ic1_by_date) & set(ic0_by_date))
    if len(common) < 10:
        return {"status": "insufficient_dates", "n_dates": len(common)}
    deltas_by_date = np.asarray(
        [ic1_by_date[d] - ic0_by_date[d] for d in common], dtype=float
    )
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=float)
    n = len(deltas_by_date)
    for i in range(iterations):
        sample = rng.choice(deltas_by_date, size=n, replace=True)
        means[i] = float(np.mean(sample))
    return {
        "status": "ok",
        "method": "bootstrap_trading_dates",
        "iterations": iterations,
        "seed": seed,
        "mean_delta": float(np.mean(means)),
        "ci95_low": float(np.percentile(means, 2.5)),
        "ci95_high": float(np.percentile(means, 97.5)),
        "n_dates": n,
    }


def _decide_ranker_verdict(
    *,
    v1_mean_ic: float,
    v0_mean_ic: float,
    positive_delta_folds: int,
    ok_folds: int,
    annual: list[dict[str, Any]],
) -> str:
    delta = v1_mean_ic - v0_mean_ic
    if ok_folds <= 0 or v1_mean_ic != v1_mean_ic:
        return "NO_IMPROVEMENT"
    majority = positive_delta_folds >= max(1, (ok_folds + 1) // 2)
    # Material improvement threshold (absolute IC points)
    material = delta >= 0.01
    # Annual: not dominated by a single year (max share of positive delta years)
    year_pos = sum(1 for a in annual if (a.get("delta_ic") or 0) > 0)
    year_n = len([a for a in annual if a.get("delta_ic") is not None])
    diversified = year_n == 0 or year_pos >= max(2, year_n // 2)
    if material and majority and diversified and v1_mean_ic > 0:
        return "RANKING_IMPROVEMENT"
    if delta > 0 or (v1_mean_ic > v0_mean_ic and majority):
        return "MIXED"
    return "NO_IMPROVEMENT"


def run_candidate_v1_ranker(
    session: Session,
    *,
    config: CandidateV1RankerConfig | None = None,
    artifact_root: Path | None = None,
    smoke: bool = False,
    v0_development_predictions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Train/evaluate V1 Ranker on DEVELOPMENT only. Never uses FINAL_HOLDOUT for selection."""
    cfg = config or CANDIDATE_V1_RANKER_CONFIG
    cfg.assert_feature_contract()
    # Reuse V0 leakage assert via duck-typed feature_names
    v0_like = CandidateV0Config(
        feature_names=cfg.feature_names,
        required_values_hash=cfg.required_values_hash,
        preferred_dataset_run_id=cfg.preferred_dataset_run_id,
    )
    assert_no_label_leakage_in_features(v0_like)

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    run, frame = load_candidate_frame(session, v0_like)
    timings["dataset_load_sec"] = round(time.perf_counter() - t0, 3)

    if (run.manifest or {}).get("values_hash") != cfg.required_values_hash:
        raise ValueError("Dataset values_hash mismatch for V1")

    t_rel = time.perf_counter()
    frame = cross_sectional_percentile_relevance(frame)
    timings["relevance_transform_sec"] = round(time.perf_counter() - t_rel, 3)

    eligible = frame["y"].notna() & frame["label_valid_20d"] & frame["eligible_20d"]
    data_start = frame.loc[eligible, "as_of_date"].min()
    holdout_start = cfg.holdout_start

    if smoke:
        train_start = date(2019, 1, 1)
        train_end = date(2022, 1, 1)
        val_start = date(2022, 1, 1)
        val_end = date(2022, 7, 1)
        fold_specs = [(train_start, train_end, val_start, val_end)]
        folds_meta = [
            {
                "fold_id": 0,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "validation_start": val_start.isoformat(),
                "validation_end": val_end.isoformat(),
            }
        ]
    else:
        folds = build_expanding_folds(
            data_start=data_start,
            development_end_exclusive=holdout_start,
            config=v0_like,
        )
        folds_meta = [f.to_dict() for f in folds]
        fold_specs = [
            (f.train_start, f.train_end, f.validation_start, f.validation_end) for f in folds
        ]

    t_wf = time.perf_counter()
    fold_reports: list[dict[str, Any]] = []
    dev_pred_parts: list[pd.DataFrame] = []
    last_model: CatBoostRankerAdapter | None = None
    last_importance: dict[str, float] = {}
    positive_delta_folds = 0
    ok_folds = 0

    # Optional V0 preds for fold deltas
    v0_preds = v0_development_predictions
    if v0_preds is None:
        v0_dir = candidate_artifact_dir(
            candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
            candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
            config_hash=CANDIDATE_V0_CONFIG.config_hash(),
            root=artifact_root,
        )
        v0_csv = v0_dir / "predictions_development.csv"
        if v0_csv.exists():
            v0_preds = pd.read_csv(v0_csv)
            v0_preds["as_of_date"] = pd.to_datetime(v0_preds["as_of_date"]).dt.date

    for fold_id, (train_start, train_end, val_start, val_end) in enumerate(fold_specs):
        train_df = select_train_rows(
            frame,
            as_of_end_exclusive=train_end,
            target_must_be_before=val_start,
            config=v0_like,
        )
        if smoke:
            train_df = train_df.loc[train_df["as_of_date"] >= train_start]
        val_df = select_eval_rows(
            frame, as_of_start=val_start, as_of_end_exclusive=val_end, config=v0_like
        )
        _assert_groups_intact(train_df, val_df)
        purged = count_purged_at_boundary(
            frame,
            as_of_end_exclusive=train_end,
            target_must_be_before=val_start,
            config=v0_like,
        )
        report: dict[str, Any] = {
            "fold_id": fold_id,
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "validation_start": val_start.isoformat(),
            "validation_end": val_end.isoformat(),
            "train_n": int(len(train_df)),
            "val_n": int(len(val_df)),
            "train_groups": int(train_df["as_of_date"].nunique()) if len(train_df) else 0,
            "val_groups": int(val_df["as_of_date"].nunique()) if len(val_df) else 0,
            "purged": purged,
        }
        if len(train_df) < 100 or len(val_df) < 20:
            report["status"] = "invalid"
            report["reason"] = "insufficient_samples"
            fold_reports.append(report)
            continue

        # Sort by group for CatBoost
        train_df = train_df.sort_values(["as_of_date", "instrument_id"], kind="mergesort")
        val_df = val_df.sort_values(["as_of_date", "instrument_id"], kind="mergesort")
        x_train = feature_matrix(train_df, v0_like)
        rel_train = train_df["relevance"].to_numpy(dtype=float)
        gid_train = group_id_codes(train_df["as_of_date"])

        ranker = CatBoostRankerAdapter(
            model_id=cfg.candidate_name,
            model_version=cfg.candidate_version,
            hyperparameters=cfg.catboost_hyperparameters,
            feature_names=list(cfg.feature_names),
        )
        ranker.fit(x_train, rel_train, gid_train)
        last_model = ranker
        last_importance = ranker.feature_importance()
        print(
            f"[v1_ranker] fold {fold_id + 1}/{len(fold_specs)} "
            f"train_n={len(train_df)} val_n={len(val_df)} fitted",
            flush=True,
        )

        x_val = feature_matrix(val_df, v0_like)
        val_pred = val_df.copy()
        val_pred["y_pred"] = ranker.predict_many(x_val)
        metrics = _ranking_metrics(
            val_pred, min_ic=cfg.min_ic_instruments, top_q=cfg.top_bottom_quantile
        )
        report["status"] = "ok"
        report["v1"] = metrics
        ok_folds += 1

        v0_mean = float("nan")
        if v0_preds is not None and not v0_preds.empty:
            v0_fold = v0_preds.loc[
                (v0_preds["as_of_date"] >= val_start) & (v0_preds["as_of_date"] < val_end)
            ]
            if len(v0_fold):
                v0_m = _ranking_metrics(
                    v0_fold, min_ic=cfg.min_ic_instruments, top_q=cfg.top_bottom_quantile
                )
                v0_mean = float(v0_m["rank_ic"]["mean_ic"])
                report["v0_mean_ic"] = v0_mean
                delta = float(metrics["rank_ic"]["mean_ic"]) - v0_mean
                report["delta_ic"] = delta
                if delta >= 0:
                    positive_delta_folds += 1

        fold_reports.append(report)
        tagged = val_pred.copy()
        tagged["fold_id"] = fold_id
        tagged["prediction_semantic"] = "RANKING_SCORE"
        tagged["prediction_score"] = tagged["y_pred"]
        dev_pred_parts.append(tagged)

    timings["walk_forward_sec"] = round(time.perf_counter() - t_wf, 3)
    development_predictions = (
        pd.concat(dev_pred_parts, ignore_index=True) if dev_pred_parts else pd.DataFrame()
    )

    if development_predictions.empty:
        development_metrics: dict[str, Any] = {"status": "no_valid_folds", "folds": fold_reports}
        research_verdict = "NO_IMPROVEMENT"
        annual: list[dict[str, Any]] = []
        bootstrap: dict[str, Any] = {"status": "skipped"}
        v0_mean_ic = float("nan")
        v1_mean_ic = float("nan")
    else:
        development_metrics = _ranking_metrics(
            development_predictions,
            min_ic=cfg.min_ic_instruments,
            top_q=cfg.top_bottom_quantile,
        )
        development_metrics["folds"] = fold_reports
        v1_mean_ic = float(development_metrics["rank_ic"]["mean_ic"])

        # V0 comparison on overlapping dates
        v0_mean_ic = float("nan")
        if v0_preds is not None and not v0_preds.empty:
            overlap = development_predictions.merge(
                v0_preds[["as_of_date", "instrument_id", "y_pred"]].rename(
                    columns={"y_pred": "y_pred_v0"}
                ),
                on=["as_of_date", "instrument_id"],
                how="inner",
            )
            if len(overlap):
                # Keep V0 scores only — do not rename onto existing V1 y_pred (duplicate cols).
                v0_frame = overlap[["as_of_date", "instrument_id", "y", "y_pred_v0"]].rename(
                    columns={"y_pred_v0": "y_pred"}
                )
                v0_m = _ranking_metrics(
                    v0_frame, min_ic=cfg.min_ic_instruments, top_q=cfg.top_bottom_quantile
                )
                v0_mean_ic = float(v0_m["rank_ic"]["mean_ic"])
                development_metrics["v0_comparison"] = {
                    "overlap_n": int(len(overlap)),
                    "v0_mean_ic": v0_mean_ic,
                    "v1_mean_ic": v1_mean_ic,
                    "delta_ic": v1_mean_ic - v0_mean_ic,
                }
                bootstrap = _bootstrap_ic_delta(
                    development_predictions,
                    v0_preds,
                    min_ic=cfg.min_ic_instruments,
                    seed=cfg.random_seed,
                    iterations=cfg.bootstrap_date_iterations if not smoke else 50,
                )
            else:
                bootstrap = {"status": "no_overlap"}
        else:
            bootstrap = {"status": "v0_predictions_missing"}

        # Annual diagnostics
        annual = []
        tmp = development_predictions.copy()
        tmp["year"] = pd.to_datetime(tmp["as_of_date"]).dt.year
        for year, group in tmp.groupby("year"):
            m = _ranking_metrics(group, min_ic=cfg.min_ic_instruments, top_q=cfg.top_bottom_quantile)
            row = {
                "year": int(year),
                "samples": int(len(group)),
                "mean_ic": m["rank_ic"]["mean_ic"],
                "positive_ic_pct": m["rank_ic"]["positive_ic_pct"],
                "top_bottom_spread": (m.get("top_bottom") or {}).get("top_minus_bottom"),
                "n_dates": m["rank_ic"]["n_dates"],
            }
            if v0_preds is not None and not v0_preds.empty:
                v0_y = v0_preds.loc[pd.to_datetime(v0_preds["as_of_date"]).dt.year == int(year)]
                if len(v0_y):
                    v0_ym = _ranking_metrics(
                        v0_y, min_ic=cfg.min_ic_instruments, top_q=cfg.top_bottom_quantile
                    )
                    row["v0_mean_ic"] = v0_ym["rank_ic"]["mean_ic"]
                    row["delta_ic"] = float(row["mean_ic"]) - float(v0_ym["rank_ic"]["mean_ic"])
            annual.append(row)
        development_metrics["annual"] = annual
        development_metrics["bootstrap_delta_ic"] = bootstrap

        research_verdict = _decide_ranker_verdict(
            v1_mean_ic=v1_mean_ic,
            v0_mean_ic=v0_mean_ic if v0_mean_ic == v0_mean_ic else -1.0,
            positive_delta_folds=positive_delta_folds,
            ok_folds=ok_folds,
            annual=annual,
        )

    # Final model: retrain on all development train-eligible before holdout
    t_final = time.perf_counter()
    if last_model is None:
        raise RuntimeError("no successful V1 fold to persist")
    # Prefer last fold model for smoke; full run: refit on all purged-safe pre-holdout data
    if not smoke:
        train_all = select_train_rows(
            frame,
            as_of_end_exclusive=holdout_start,
            target_must_be_before=holdout_start,
            config=v0_like,
        )
        train_all = train_all.sort_values(["as_of_date", "instrument_id"], kind="mergesort")
        if len(train_all) >= 100:
            final = CatBoostRankerAdapter(
                model_id=cfg.candidate_name,
                model_version=cfg.candidate_version,
                hyperparameters=cfg.catboost_hyperparameters,
                feature_names=list(cfg.feature_names),
            )
            final.fit(
                feature_matrix(train_all, v0_like),
                train_all["relevance"].to_numpy(dtype=float),
                group_id_codes(train_all["as_of_date"]),
            )
            last_model = final
            last_importance = final.feature_importance()
    timings["final_fit_sec"] = round(time.perf_counter() - t_final, 3)

    out_dir = candidate_artifact_dir(
        candidate_name=cfg.candidate_name,
        candidate_version=cfg.candidate_version,
        config_hash=cfg.config_hash(),
        root=artifact_root,
    )
    model_path = out_dir / "model.cbm"
    last_model.save(model_path)

    # Export prediction artifact without implying return %
    export_cols = [
        c
        for c in (
            "sample_id",
            "instrument_id",
            "as_of_date",
            "y_pred",
            "prediction_score",
            "prediction_semantic",
            "fold_id",
            "y",
            "relevance",
        )
        if c in development_predictions.columns
    ]
    if development_predictions.empty:
        export_df = development_predictions
    else:
        export_df = development_predictions.loc[:, export_cols].copy()

    config_payload = cfg.to_dict()
    config_payload["config_hash"] = cfg.config_hash()
    config_payload["feature_schema_hash"] = cfg.feature_schema_hash()
    config_payload["dataset_run_id"] = int(run.id)
    config_payload["objective_rationale"] = (
        "YetiRank is CatBoost's ranking loss over query groups; "
        "labels are cross-sectional percentile relevance of forward_return_20d "
        "(relative attractiveness, not return magnitude)."
    )

    # holdout_metrics intentionally empty / blocked
    holdout_metrics = {
        "status": "SKIPPED",
        "reason": (
            "Candidate V1 must NOT use already-observed 2026 FINAL_HOLDOUT "
            "for model selection or headline verdict."
        ),
        "evaluate_final_holdout": False,
    }

    walk_forward_metrics = _sanitize(
        {
            "folds_meta": folds_meta,
            "development": development_metrics,
            "research_verdict": research_verdict,
            "prediction_semantic": "RANKING_SCORE",
            "v0_mean_ic": v0_mean_ic if v0_mean_ic == v0_mean_ic else None,
            "v1_mean_ic": v1_mean_ic if v1_mean_ic == v1_mean_ic else None,
            "positive_delta_folds": positive_delta_folds,
            "ok_folds": ok_folds,
        }
    )

    timings["total_sec"] = round(time.perf_counter() - t0, 3)
    persist_candidate_bundle(
        out_dir=out_dir,
        config_payload=config_payload,
        walk_forward_metrics=walk_forward_metrics,
        holdout_metrics=holdout_metrics,
        feature_importance=last_importance,
        development_predictions=export_df if not export_df.empty else None,
        holdout_predictions=None,
        research_verdict=research_verdict,
        timings=timings,
        model_path=model_path,
        holdout_evaluated=False,
    )
    write_json(
        out_dir / "relevance_transform.json",
        {
            "transform": cfg.relevance_transform,
            "group": cfg.ranking_group,
            "raw_outcome": cfg.target,
            "tie_handling": "average_rank_then_instrument_id_sort",
            "note": "Relevance is Y only; never enters feature vector X.",
        },
    )
    write_json(
        out_dir / "feature_list.json",
        {"feature_names": list(cfg.feature_names), "count": len(cfg.feature_names)},
    )

    upsert_model_registry_row(
        session,
        model_name=cfg.candidate_name,
        model_version=cfg.candidate_version,
        parameters={
            "config_hash": cfg.config_hash(),
            "prediction_semantic": "RANKING_SCORE",
            "model_family": cfg.model_family,
            "human_name": cfg.human_name,
            "artifact_dir": str(out_dir),
            "objective": cfg.ranking_objective,
        },
        training_dataset=f"{cfg.dataset_spec_code}/v{cfg.dataset_spec_version}",
        metrics={
            "mean_ic": float(v1_mean_ic) if v1_mean_ic == v1_mean_ic else 0.0,
            "v0_mean_ic": float(v0_mean_ic) if v0_mean_ic == v0_mean_ic else 0.0,
        },
        status=f"candidate/{research_verdict}",
    )
    session.flush()

    return _sanitize(
        {
            "candidate": f"{cfg.candidate_name}/{cfg.candidate_version}",
            "config_hash": cfg.config_hash(),
            "artifact_dir": str(out_dir),
            "research_verdict": research_verdict,
            "prediction_semantic": "RANKING_SCORE",
            "development_prediction_hash": (
                prediction_hash(export_df) if not export_df.empty else None
            ),
            "metrics": walk_forward_metrics,
            "timings": timings,
            "holdout_evaluated": False,
        }
    )
