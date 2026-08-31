"""Pure RelationCalculator — statistical relations, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import numpy as np


@dataclass(frozen=True, slots=True)
class InputSeries:
    """Dated observations for one relation input (already filtered / transformed)."""

    input_id: UUID
    dates: tuple[date, ...]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class LagMetricResult:
    leader_input_id: UUID
    follower_input_id: UUID
    lag: int
    pearson: float | None
    spearman: float | None
    sample_count: int
    coverage_ratio: float


@dataclass(frozen=True, slots=True)
class PairRelationResult:
    input_a_id: UUID
    input_b_id: UUID
    as_of_date: date
    window_observations: int
    sample_count: int
    coverage_ratio: float
    pearson: float | None
    spearman: float | None
    rolling_corr_mean: float | None
    rolling_corr_std: float | None
    sign_consistency: float | None
    best_leader_input_id: UUID | None
    best_follower_input_id: UUID | None
    best_lag: int | None
    best_lag_pearson: float | None
    best_lag_spearman: float | None
    is_valid: bool
    quality_flags: dict[str, Any] = field(default_factory=dict)
    lag_metrics: tuple[LagMetricResult, ...] = ()


def _ordered_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if a < b else (b, a)


def _average_rank(a: np.ndarray) -> np.ndarray:
    """Average ranks with tie handling (Spearman) — pure numpy, no pandas/scipy."""
    n = len(a)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i + 1
        while j < n and a[order[j]] == a[order[i]]:
            j += 1
        # ranks are 1-based; ties get the average of their ordinal positions
        avg = 0.5 * (i + 1 + j)
        ranks[order[i:j]] = avg
        i = j
    return ranks


def _safe_corr(x: np.ndarray, y: np.ndarray, method: str) -> float | None:
    if len(x) < 2:
        return None
    if np.allclose(x, x[0]) or np.allclose(y, y[0]):
        return None
    if method == "spearman":
        rx = _average_rank(x)
        ry = _average_rank(y)
        if np.allclose(rx, rx[0]) or np.allclose(ry, ry[0]):
            return None
        value = float(np.corrcoef(rx, ry)[0, 1])
    else:
        value = float(np.corrcoef(x, y)[0, 1])
    if np.isnan(value) or np.isinf(value):
        return None
    return value


def _window_slice(
    dates: list[date],
    values: list[float | None],
    *,
    as_of: date,
    window: int,
) -> tuple[list[date], list[float | None]]:
    """Take last `window` observations with date <= as_of (no look-ahead)."""
    eligible = [(d, v) for d, v in zip(dates, values, strict=True) if d <= as_of]
    if not eligible:
        return [], []
    tail = eligible[-window:]
    return [d for d, _ in tail], [v for _, v in tail]


def _aligned_arrays(
    dates_a: list[date],
    vals_a: list[float | None],
    dates_b: list[date],
    vals_b: list[float | None],
) -> tuple[np.ndarray, np.ndarray, int, float]:
    """Inner-join on dates; drop None pairs. Returns x, y, sample_count, coverage vs max(len)."""
    map_a = {d: v for d, v in zip(dates_a, vals_a, strict=True)}
    map_b = {d: v for d, v in zip(dates_b, vals_b, strict=True)}
    common = sorted(set(map_a) & set(map_b))
    xs: list[float] = []
    ys: list[float] = []
    for d in common:
        va, vb = map_a[d], map_b[d]
        if va is None or vb is None:
            continue
        if isinstance(va, float) and (np.isnan(va) or np.isinf(va)):
            continue
        if isinstance(vb, float) and (np.isnan(vb) or np.isinf(vb)):
            continue
        xs.append(float(va))
        ys.append(float(vb))
    sample = len(xs)
    denom = max(len(dates_a), len(dates_b), 1)
    coverage = sample / denom
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), sample, coverage


def _lag_pair_arrays(
    dates: list[date],
    leader_vals: list[float | None],
    follower_vals: list[float | None],
    lag: int,
) -> tuple[np.ndarray, np.ndarray, int, float]:
    """leader(t) vs follower(t+lag) on shared observation index; all dates already <= as_of."""
    n = len(dates)
    xs: list[float] = []
    ys: list[float] = []
    for i in range(n - lag):
        lv = leader_vals[i]
        fv = follower_vals[i + lag]
        if lv is None or fv is None:
            continue
        if isinstance(lv, float) and (np.isnan(lv) or np.isinf(lv)):
            continue
        if isinstance(fv, float) and (np.isnan(fv) or np.isinf(fv)):
            continue
        xs.append(float(lv))
        ys.append(float(fv))
    sample = len(xs)
    # Coverage vs possible lag-aligned slots in the window
    possible = max(n - lag, 1)
    coverage = sample / possible
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), sample, coverage


def _stability_metrics(
    x: np.ndarray,
    y: np.ndarray,
    *,
    subwindow: int,
) -> tuple[float | None, float | None, float | None]:
    """Rolling pearson mean/std and sign consistency over already-aligned arrays."""
    if len(x) < subwindow:
        return None, None, None
    corrs: list[float] = []
    for start in range(0, len(x) - subwindow + 1):
        c = _safe_corr(x[start : start + subwindow], y[start : start + subwindow], "pearson")
        if c is not None:
            corrs.append(c)
    if not corrs:
        return None, None, None
    arr = np.asarray(corrs, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    signs = np.sign(arr)
    nonzero = signs[signs != 0]
    if len(nonzero) == 0:
        consistency = 1.0
    else:
        pos = float(np.mean(nonzero > 0))
        consistency = max(pos, 1.0 - pos)
    return mean, std, consistency


class RelationCalculator:
    """Pure deterministic relation calculator over in-memory input series."""

    def __init__(self, parameters: dict[str, Any] | None = None) -> None:
        params = parameters or {}
        self.windows: list[int] = list(params.get("windows", [20, 60, 120]))
        self.lead_lags: list[int] = list(params.get("lead_lags", [1, 2, 3, 4, 5]))
        self.minimum_coverage_ratio: float = float(params.get("minimum_coverage_ratio", 0.8))
        self.stability_subwindow: int = int(params.get("stability_subwindow", 20))
        methods = params.get("correlation_methods", ["pearson", "spearman"])
        self.use_pearson = "pearson" in methods
        self.use_spearman = "spearman" in methods

    def calculate_as_of(
        self,
        series_by_id: dict[UUID, InputSeries],
        *,
        as_of_date: date,
        input_ids: list[UUID] | None = None,
    ) -> list[PairRelationResult]:
        ids = input_ids or sorted(series_by_id.keys(), key=str)
        # Pre-materialize date/value lists filtered to as_of (no look-ahead at source)
        prepared: dict[UUID, tuple[list[date], list[float]]] = {}
        for iid in ids:
            series = series_by_id.get(iid)
            if series is None:
                continue
            dates: list[date] = []
            values: list[float] = []
            for d, v in zip(series.dates, series.values, strict=True):
                if d > as_of_date:
                    break
                dates.append(d)
                values.append(v)
            prepared[iid] = (dates, values)

        results: list[PairRelationResult] = []
        # Pre-slice each input once per window (not once per pair).
        for window in self.windows:
            sliced: dict[UUID, tuple[list[date], list[float | None]]] = {}
            for iid, (dates_full, vals_full) in prepared.items():
                sliced[iid] = _window_slice(
                    dates_full, list(vals_full), as_of=as_of_date, window=window
                )
            for i, id_a in enumerate(ids):
                if id_a not in sliced:
                    continue
                for id_b in ids[i + 1 :]:
                    if id_b not in sliced:
                        continue
                    a_id, b_id = _ordered_pair(id_a, id_b)
                    dates_a, vals_a = sliced[a_id]
                    dates_b, vals_b = sliced[b_id]
                    results.append(
                        self._calculate_pair_window(
                            a_id,
                            b_id,
                            dates_a,
                            vals_a,
                            dates_b,
                            vals_b,
                            as_of_date=as_of_date,
                            window=window,
                        )
                    )
        return results

    def _calculate_pair_window(
        self,
        a_id: UUID,
        b_id: UUID,
        dates_a: list[date],
        vals_a: list[float | None],
        dates_b: list[date],
        vals_b: list[float | None],
        *,
        as_of_date: date,
        window: int,
    ) -> PairRelationResult:
        x, y, sample, coverage = _aligned_arrays(dates_a, vals_a, dates_b, vals_b)
        quality: dict[str, Any] = {}
        pearson = _safe_corr(x, y, "pearson") if self.use_pearson else None
        spearman = _safe_corr(x, y, "spearman") if self.use_spearman else None

        is_valid = True
        if coverage < self.minimum_coverage_ratio or sample < 2:
            is_valid = False
            quality["insufficient_samples"] = True
        if pearson is None and spearman is None and sample >= 2:
            quality["undefined_correlation"] = True
            is_valid = False

        rolling_mean = rolling_std = sign_consistency = None
        if window > self.stability_subwindow and sample >= self.stability_subwindow:
            rolling_mean, rolling_std, sign_consistency = _stability_metrics(
                x,
                y,
                subwindow=self.stability_subwindow,
            )
        # window == stability_subwindow (20): stability intentionally NULL

        # Lead-lag uses observation index on common dates; all observations <= as_of.
        map_a = {d: v for d, v in zip(dates_a, vals_a, strict=True)}
        map_b = {d: v for d, v in zip(dates_b, vals_b, strict=True)}
        common_dates = sorted(set(map_a) & set(map_b))
        common_a = [map_a[d] for d in common_dates]
        common_b = [map_b[d] for d in common_dates]

        lag_results: list[LagMetricResult] = []
        best_leader: UUID | None = None
        best_follower: UUID | None = None
        best_lag: int | None = None
        best_pearson: float | None = None
        best_spearman: float | None = None
        best_abs = -1.0

        for lag in self.lead_lags:
            for leader_id, follower_id, leader_vals, follower_vals in (
                (a_id, b_id, common_a, common_b),
                (b_id, a_id, common_b, common_a),
            ):
                lx, ly, lag_sample, lag_cov = _lag_pair_arrays(
                    common_dates, leader_vals, follower_vals, lag
                )
                lp = _safe_corr(lx, ly, "pearson") if self.use_pearson else None
                ls = _safe_corr(lx, ly, "spearman") if self.use_spearman else None
                lag_results.append(
                    LagMetricResult(
                        leader_input_id=leader_id,
                        follower_input_id=follower_id,
                        lag=lag,
                        pearson=lp,
                        spearman=ls,
                        sample_count=lag_sample,
                        coverage_ratio=lag_cov,
                    )
                )
                # Best lag by max |pearson| (fallback spearman), tie-break smaller lag
                score_src = lp if lp is not None else ls
                if score_src is None:
                    continue
                score = abs(score_src)
                if score > best_abs or (
                    score == best_abs and best_lag is not None and lag < best_lag
                ):
                    best_abs = score
                    best_leader = leader_id
                    best_follower = follower_id
                    best_lag = lag
                    best_pearson = lp
                    best_spearman = ls
                elif score == best_abs and best_lag == lag:
                    # Same lag magnitude: prefer already chosen (stable), no change
                    pass

        return PairRelationResult(
            input_a_id=a_id,
            input_b_id=b_id,
            as_of_date=as_of_date,
            window_observations=window,
            sample_count=sample,
            coverage_ratio=coverage,
            pearson=pearson,
            spearman=spearman,
            rolling_corr_mean=rolling_mean,
            rolling_corr_std=rolling_std,
            sign_consistency=sign_consistency,
            best_leader_input_id=best_leader,
            best_follower_input_id=best_follower,
            best_lag=best_lag,
            best_lag_pearson=best_pearson,
            best_lag_spearman=best_spearman,
            is_valid=is_valid,
            quality_flags=quality,
            lag_metrics=tuple(lag_results),
        )
