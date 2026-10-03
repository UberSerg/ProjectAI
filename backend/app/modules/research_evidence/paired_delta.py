"""Paired V4 vs BASE deltas: daily IC and top-bucket realized return, bootstrap by date.

Algorithm matches runner_v1._bootstrap_ic_delta (method bootstrap_trading_dates):
precompute daily ICs, resample dates with a fixed seed. This module does not import
runner_v1 (CatBoost/registry). No fabricated p-values.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.modules.prediction.candidate_config import (
    MIN_IC_INSTRUMENTS,
    RANDOM_SEED,
    TOP_BOTTOM_QUANTILE,
)
from app.modules.research_evidence.oos import STATUS_INSUFFICIENT, STATUS_OK

MIN_COMMON_DATES = 10
BOOTSTRAP_ITERATIONS = 1000


def _normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    return out


def daily_ic_series(
    frame: pd.DataFrame,
    *,
    pred_col: str = "y_pred",
    min_ic_instruments: int = MIN_IC_INSTRUMENTS,
) -> dict[Any, float]:
    """One Spearman IC per as_of_date — same skip rules as runner_v1._daily_spearman_ic."""
    out: dict[Any, float] = {}
    for as_of, group in frame.groupby("as_of_date", sort=True):
        if len(group) < min_ic_instruments:
            continue
        if group[pred_col].nunique(dropna=True) < 2 or group["y"].nunique(dropna=True) < 2:
            continue
        corr = float(group[pred_col].rank().corr(group["y"].rank(), method="pearson"))
        if corr == corr:
            out[as_of] = corr
    return out


def daily_top_bucket_realized(
    frame: pd.DataFrame,
    *,
    quantile: float,
    pred_col: str = "y_pred",
) -> dict[Any, float]:
    """Mean realized forward return in the top predicted quantile per date."""
    out: dict[Any, float] = {}
    for as_of, group in frame.groupby("as_of_date", sort=True):
        n = len(group)
        k = max(1, int(np.floor(n * quantile)))
        if n < 2 * k:
            continue
        ordered = group.sort_values(pred_col)
        out[as_of] = float(ordered.tail(k)["y"].mean())
    return out


def _bootstrap_mean_delta(
    deltas: np.ndarray,
    *,
    seed: int,
    iterations: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = len(deltas)
    means = np.empty(iterations, dtype=float)
    for i in range(iterations):
        sample = rng.choice(deltas, size=n, replace=True)
        means[i] = float(np.mean(sample))
    return {
        "status": STATUS_OK,
        "method": "bootstrap_trading_dates",
        "iterations": iterations,
        "seed": seed,
        "mean_delta": float(np.mean(means)),
        "ci95_low": float(np.percentile(means, 2.5)),
        "ci95_high": float(np.percentile(means, 97.5)),
        "n_common_dates": n,
    }


def _insufficient(*, n_common_dates: int, reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_INSUFFICIENT,
        "method": "bootstrap_trading_dates",
        "n_common_dates": int(n_common_dates),
        "mean_delta": None,
        "ci95_low": None,
        "ci95_high": None,
        "reason": reason,
    }


def _paired_series_delta(
    left: dict[Any, float],
    right: dict[Any, float],
    *,
    seed: int,
    iterations: int,
    min_common_dates: int,
) -> dict[str, Any]:
    common = sorted(set(left) & set(right))
    if len(common) < min_common_dates:
        return _insufficient(n_common_dates=len(common), reason="insufficient_dates")
    deltas = np.asarray([left[d] - right[d] for d in common], dtype=float)
    return _bootstrap_mean_delta(deltas, seed=seed, iterations=iterations)


def paired_v4_vs_base(
    pred_v4: pd.DataFrame,
    pred_base: pd.DataFrame,
    *,
    seed: int = RANDOM_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    min_ic_instruments: int = MIN_IC_INSTRUMENTS,
    min_common_dates: int = MIN_COMMON_DATES,
    quantile: float = TOP_BOTTOM_QUANTILE,
) -> dict[str, Any]:
    """Paired daily (IC_V4 - IC_BASE) and top-bucket realized-return delta.

    Bootstrap resamples trading dates with replacement. No p-values.
    """
    v4 = _normalize_dates(pred_v4)
    base = _normalize_dates(pred_base)
    if v4.empty or base.empty:
        empty = _insufficient(n_common_dates=0, reason="empty_predictions")
        return {
            "status": STATUS_INSUFFICIENT,
            "ic_delta": empty,
            "top_bucket_realized_return_delta": empty,
            "n_common_dates": 0,
            "p_value": None,
        }

    merged = v4[["as_of_date", "instrument_id", "y_pred", "y"]].merge(
        base[["as_of_date", "instrument_id", "y_pred"]].rename(columns={"y_pred": "y_pred_base"}),
        on=["as_of_date", "instrument_id"],
        how="inner",
    )
    ic_v4 = daily_ic_series(merged, pred_col="y_pred", min_ic_instruments=min_ic_instruments)
    ic_base = daily_ic_series(merged, pred_col="y_pred_base", min_ic_instruments=min_ic_instruments)
    ic_delta = _paired_series_delta(
        ic_v4, ic_base, seed=seed, iterations=iterations, min_common_dates=min_common_dates
    )

    top_v4 = daily_top_bucket_realized(merged, quantile=quantile, pred_col="y_pred")
    top_base = daily_top_bucket_realized(
        merged.rename(columns={"y_pred": "y_pred_v4", "y_pred_base": "y_pred"}),
        quantile=quantile,
        pred_col="y_pred",
    )
    top_delta = _paired_series_delta(
        top_v4, top_base, seed=seed, iterations=iterations, min_common_dates=min_common_dates
    )

    n_ic = int(ic_delta.get("n_common_dates") or 0)
    n_common = n_ic if n_ic else int(top_delta.get("n_common_dates") or 0)
    ic_ok = ic_delta.get("status") == STATUS_OK
    top_ok = top_delta.get("status") == STATUS_OK
    status = STATUS_OK if ic_ok and top_ok else STATUS_INSUFFICIENT

    return {
        "status": status,
        "method": "bootstrap_trading_dates",
        "seed": seed,
        "iterations": iterations,
        "n_common_dates": n_common,
        "ic_delta": ic_delta,
        "top_bucket_realized_return_delta": top_delta,
        "p_value": None,
        "p_values_note": "p-values are not fabricated for this research delta.",
        "note": (
            "Paired CHRONOLOGICAL OOS RESEARCH delta V4 vs BASE. "
            "Bootstrap by date, fixed seed. Not a production Candidate comparison."
        ),
    }
