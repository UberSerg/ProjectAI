"""Offline prediction metrics (regression + cross-sectional ranking)."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd


def regression_metrics(y_true: npt.NDArray[np.floating], y_pred: npt.NDArray[np.floating]) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err))) if len(err) else float("nan")
    rmse = float(np.sqrt(np.mean(err**2))) if len(err) else float("nan")
    if len(y_true) < 2:
        r2 = float("nan")
    else:
        ss_res = float(np.sum(err**2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        r2 = float("nan") if ss_tot == 0 else 1.0 - ss_res / ss_tot
    return {"mae": mae, "rmse": rmse, "r2": r2, "n": float(len(y_true))}


def directional_accuracy(y_true: npt.NDArray[np.floating], y_pred: npt.NDArray[np.floating]) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) == 0:
        return float("nan")
    # Zero realized treated as miss for sign equality (conservative).
    mask = y_true != 0
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.sign(y_pred[mask]) == np.sign(y_true[mask])))


def positive_precision(y_true: npt.NDArray[np.floating], y_pred: npt.NDArray[np.floating]) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    pred_pos = y_pred > 0
    if not np.any(pred_pos):
        return float("nan")
    return float(np.mean(y_true[pred_pos] > 0))


def cross_sectional_ic(
    frame: pd.DataFrame,
    *,
    min_instruments: int,
    pred_col: str = "y_pred",
    actual_col: str = "y",
    date_col: str = "as_of_date",
) -> dict[str, Any]:
    """Daily Spearman IC across instruments. ICIR = mean(IC)/std(IC), not portfolio Sharpe."""
    daily: list[float] = []
    skipped = 0
    for _, group in frame.groupby(date_col, sort=True):
        if len(group) < min_instruments:
            skipped += 1
            continue
        if group[pred_col].nunique(dropna=True) < 2 or group[actual_col].nunique(dropna=True) < 2:
            skipped += 1
            continue
        corr = float(group[pred_col].rank().corr(group[actual_col].rank(), method="pearson"))
        if corr is None or np.isnan(corr):
            skipped += 1
            continue
        daily.append(corr)
    arr = np.asarray(daily, dtype=float)
    if len(arr) == 0:
        return {
            "mean_ic": float("nan"),
            "median_ic": float("nan"),
            "std_ic": float("nan"),
            "positive_ic_pct": float("nan"),
            "icir": float("nan"),
            "n_dates": 0,
            "skipped_dates": skipped,
            "min_instruments": min_instruments,
            "note": "ICIR is mean(IC)/std(IC) rank consistency — not portfolio Sharpe",
        }
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else float("nan")
    mean = float(np.mean(arr))
    return {
        "mean_ic": mean,
        "median_ic": float(np.median(arr)),
        "std_ic": std,
        "positive_ic_pct": float(np.mean(arr > 0) * 100.0),
        "icir": float(mean / std) if std and not np.isnan(std) and std != 0 else float("nan"),
        "n_dates": int(len(arr)),
        "skipped_dates": skipped,
        "min_instruments": min_instruments,
        "note": "ICIR is mean(IC)/std(IC) rank consistency — not portfolio Sharpe",
    }


def top_bottom_spread(
    frame: pd.DataFrame,
    *,
    quantile: float,
    pred_col: str = "y_pred",
    actual_col: str = "y",
    date_col: str = "as_of_date",
) -> dict[str, Any]:
    """Non-trading ranking diagnostic: mean realized top vs bottom quantile per date."""
    tops: list[float] = []
    bottoms: list[float] = []
    for _, group in frame.groupby(date_col, sort=True):
        n = len(group)
        k = max(1, int(np.floor(n * quantile)))
        if n < 2 * k:
            continue
        ordered = group.sort_values(pred_col)
        bottom = ordered.head(k)[actual_col].mean()
        top = ordered.tail(k)[actual_col].mean()
        bottoms.append(float(bottom))
        tops.append(float(top))
    if not tops:
        return {
            "top_realized_mean": float("nan"),
            "bottom_realized_mean": float("nan"),
            "top_minus_bottom": float("nan"),
            "n_dates": 0,
            "quantile": quantile,
            "note": "ranking diagnostic only — not Simulator PnL / Sharpe",
        }
    top_m = float(np.mean(tops))
    bot_m = float(np.mean(bottoms))
    return {
        "top_realized_mean": top_m,
        "bottom_realized_mean": bot_m,
        "top_minus_bottom": top_m - bot_m,
        "n_dates": len(tops),
        "quantile": quantile,
        "note": "ranking diagnostic only — not Simulator PnL / Sharpe",
    }


def evaluate_predictions(
    frame: pd.DataFrame,
    *,
    min_ic_instruments: int,
    top_bottom_quantile: float,
    pred_col: str = "y_pred",
) -> dict[str, Any]:
    y_true = frame["y"].to_numpy(dtype=float)
    y_pred = frame[pred_col].to_numpy(dtype=float)
    out = {
        **regression_metrics(y_true, y_pred),
        "directional_accuracy": directional_accuracy(y_true, y_pred),
        "positive_precision": positive_precision(y_true, y_pred),
        "rank_ic": cross_sectional_ic(
            frame, min_instruments=min_ic_instruments, pred_col=pred_col
        ),
        "top_bottom": top_bottom_spread(
            frame, quantile=top_bottom_quantile, pred_col=pred_col
        ),
    }
    return out
