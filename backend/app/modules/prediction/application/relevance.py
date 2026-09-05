"""Cross-sectional relevance labels for Candidate V1 Ranker (Y only — never in X)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def cross_sectional_percentile_relevance(
    frame: pd.DataFrame,
    *,
    actual_col: str = "y",
    date_col: str = "as_of_date",
    instrument_col: str = "instrument_id",
    out_col: str = "relevance",
) -> pd.DataFrame:
    """Within each date, map realized forward returns to [0, 1] percentile ranks.

    Best realized return → 1.0, worst → 0.0.
    Ties: average rank (pandas default), deterministic given stable sort keys.
    """
    if frame.empty:
        out = frame.copy()
        out[out_col] = pd.Series(dtype=float)
        return out

    parts: list[pd.DataFrame] = []
    for _, group in frame.groupby(date_col, sort=True):
        g = group.copy()
        # rank: higher return → higher rank; pct = (rank-1)/(n-1)
        n = len(g)
        if n == 1:
            g[out_col] = 1.0
        else:
            # method=average for ties; secondary sort by instrument_id for stability of equals
            ordered = g.sort_values([actual_col, instrument_col], kind="mergesort")
            ranks = ordered[actual_col].rank(method="average", ascending=True)
            ordered[out_col] = (ranks - 1.0) / (n - 1.0)
            g = ordered.sort_index()
        parts.append(g)
    return pd.concat(parts, axis=0).sort_index()


def assert_best_gets_highest_relevance(
    frame: pd.DataFrame,
    *,
    actual_col: str = "y",
    date_col: str = "as_of_date",
    relevance_col: str = "relevance",
) -> None:
    for _, group in frame.groupby(date_col, sort=True):
        if group.empty:
            continue
        best_idx = group[actual_col].idxmax()
        worst_idx = group[actual_col].idxmin()
        if group.loc[best_idx, relevance_col] + 1e-12 < group[relevance_col].max():
            raise AssertionError("best realized return must have max relevance")
        if group.loc[worst_idx, relevance_col] - 1e-12 > group[relevance_col].min():
            raise AssertionError("worst realized return must have min relevance")


def group_id_codes(as_of_dates: pd.Series) -> np.ndarray:
    """Dense integer group ids for CatBoost (same date → same group)."""
    codes, _ = pd.factorize(pd.to_datetime(as_of_dates).dt.strftime("%Y-%m-%d"), sort=True)
    return np.asarray(codes, dtype=np.int32)
