"""Stability slices for chronological OOS research predictions.

Only grounded classifications present on the frame are reported.
Model-native importance, if supplied, is labeled ASSOCIATIONAL MODEL IMPORTANCE (not causal).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.modules.fundamentals.application.pit import BASIS_CURRENT_ONLY, BASIS_DATED_WINDOW
from app.modules.learning.dataset_config import (
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
)
from app.modules.research_evidence.oos import (
    STATUS_INSUFFICIENT,
    STATUS_OK,
    SemanticName,
    ranking_metrics,
    regression_metrics_payload,
)

ACTIVE_COLUMNS = ("currently_active", "instrument_is_active", "is_active")
ISSUER_BASIS_COLUMNS = ("issuer_resolution_basis",)
MIN_SLICE_ROWS = 8


def _first_present(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _metrics_for(
    frame: pd.DataFrame,
    *,
    semantic: SemanticName,
    min_ic_instruments: int,
    top_bottom_quantile: float,
) -> dict[str, Any]:
    if semantic == "ranking":
        return ranking_metrics(
            frame,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
        )
    return regression_metrics_payload(
        frame,
        min_ic_instruments=min_ic_instruments,
        top_bottom_quantile=top_bottom_quantile,
    )


def _slice_report(
    name: str,
    subset: pd.DataFrame,
    *,
    semantic: SemanticName,
    min_ic_instruments: int,
    top_bottom_quantile: float,
    min_rows: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {"slice": name, "n": int(len(subset))}
    if len(subset) < min_rows:
        report["status"] = STATUS_INSUFFICIENT
        report["metrics"] = None
        report["reason"] = "insufficient_samples"
        return report
    report["status"] = STATUS_OK
    report["metrics"] = _metrics_for(
        subset,
        semantic=semantic,
        min_ic_instruments=min_ic_instruments,
        top_bottom_quantile=top_bottom_quantile,
    )
    return report


def _pack_present_mask(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series | None:
    cols = [c for c in names if c in frame.columns]
    if not cols:
        return None
    return frame[cols].notna().any(axis=1)


def slice_stability(
    predictions: pd.DataFrame,
    *,
    semantic: SemanticName = "regression",
    min_ic_instruments: int = 10,
    top_bottom_quantile: float = 0.2,
    min_rows: int = MIN_SLICE_ROWS,
    associational_importance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Slice OOS predictions by fold, year, activity, issuer basis, fund/event presence."""
    if predictions.empty:
        return {
            "status": STATUS_INSUFFICIENT,
            "slices": {},
            "reason": "empty_predictions",
        }

    frame = predictions.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"])
    slices: dict[str, Any] = {}

    if "fold_id" in frame.columns:
        by_fold = []
        for fold_id, group in frame.groupby("fold_id", sort=True):
            by_fold.append(
                _slice_report(
                    f"fold={fold_id}",
                    group,
                    semantic=semantic,
                    min_ic_instruments=min_ic_instruments,
                    top_bottom_quantile=top_bottom_quantile,
                    min_rows=min_rows,
                )
            )
        slices["by_fold"] = by_fold

    by_year = []
    years = frame["as_of_date"].dt.year
    for year, group in frame.groupby(years, sort=True):
        by_year.append(
            _slice_report(
                f"year={int(year)}",
                group,
                semantic=semantic,
                min_ic_instruments=min_ic_instruments,
                top_bottom_quantile=top_bottom_quantile,
                min_rows=min_rows,
            )
        )
    slices["by_calendar_year"] = by_year

    active_col = _first_present(frame, ACTIVE_COLUMNS)
    if active_col is not None:
        active = frame[active_col].astype("boolean")
        slices["current_active"] = _slice_report(
            "current_active",
            frame.loc[active == True],  # noqa: E712
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )
        slices["currently_inactive"] = _slice_report(
            "currently_inactive",
            frame.loc[active == False],  # noqa: E712
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )

    basis_col = _first_present(frame, ISSUER_BASIS_COLUMNS)
    if basis_col is not None:
        basis = frame[basis_col].astype(str)
        dated = frame.loc[basis == BASIS_DATED_WINDOW]
        current_only = frame.loc[basis == BASIS_CURRENT_ONLY]
        slices["issuer_identity_DATED_WINDOW"] = _slice_report(
            "issuer_identity_DATED_WINDOW",
            dated,
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )
        slices["issuer_identity_CURRENT_ONLY"] = _slice_report(
            "issuer_identity_CURRENT_ONLY",
            current_only,
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )

    fund_mask = _pack_present_mask(frame, V4_FUNDAMENTAL_FEATURE_NAMES)
    if fund_mask is not None:
        slices["fund_features_present"] = _slice_report(
            "fund_features_present",
            frame.loc[fund_mask],
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )
        slices["fund_features_absent"] = _slice_report(
            "fund_features_absent",
            frame.loc[~fund_mask],
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )

    event_mask = _pack_present_mask(frame, V4_EVENT_FEATURE_NAMES)
    if event_mask is not None:
        slices["event_features_present"] = _slice_report(
            "event_features_present",
            frame.loc[event_mask],
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )
        slices["event_features_absent"] = _slice_report(
            "event_features_absent",
            frame.loc[~event_mask],
            semantic=semantic,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
            min_rows=min_rows,
        )

    payload: dict[str, Any] = {
        "status": STATUS_OK,
        "evaluation_kind": "CHRONOLOGICAL OOS RESEARCH",
        "slices": slices,
        "note": (
            "Stability slices use only grounded columns on the prediction frame. "
            "Ungrounded classifications are omitted, not invented."
        ),
    }
    if associational_importance:
        payload["associational_model_importance"] = {
            "label": "ASSOCIATIONAL MODEL IMPORTANCE",
            "causal": False,
            **associational_importance,
        }
    return payload
