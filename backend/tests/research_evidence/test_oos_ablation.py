"""Research Evidence Engine V1 — chronological OOS, ablation, paired delta."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.modules.learning.dataset_config import (
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
)
from app.modules.prediction.application.splits import WalkForwardFold
from app.modules.research_evidence.ablation import (
    VARIANT_BASE,
    VARIANT_BASE_EVENTS,
    VARIANT_BASE_FUNDAMENTALS,
    VARIANT_V4_FULL,
    apply_ablation_mask,
    run_v4_ablation,
)
from app.modules.research_evidence.oos import (
    EVALUATION_KIND,
    REGRESSION_METRIC_KEYS,
    STATUS_INSUFFICIENT,
    ResearchOosError,
    ranking_metrics,
    run_chronological_oos,
    train_val_split_purged,
)
from app.modules.research_evidence.paired_delta import paired_v4_vs_base
from app.modules.research_evidence.stability import slice_stability

BASE_FEAT = "return_1d"
FUND_FEAT = V4_FUNDAMENTAL_FEATURE_NAMES[0]
EVENT_FEAT = V4_EVENT_FEATURE_NAMES[0]
FEATURE_NAMES = [BASE_FEAT, FUND_FEAT, EVENT_FEAT]


class DummyRegressor:
    """Tiny injectable model — no CatBoost, ignores NaNs in unused columns."""

    def fit(self, x: np.ndarray, y: np.ndarray, group_id: np.ndarray | None = None) -> DummyRegressor:
        x0 = np.asarray(x, dtype=float)[:, 0]
        y = np.asarray(y, dtype=float)
        self.mean_ = float(np.nanmean(y))
        valid = ~np.isnan(x0)
        self.scale_ = float(np.nanstd(x0[valid])) if valid.any() else 1.0
        if self.scale_ == 0:
            self.scale_ = 1.0
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        x0 = np.asarray(x, dtype=float)[:, 0]
        filled = np.where(np.isnan(x0), 0.0, x0)
        return filled / self.scale_ * 0.01 + self.mean_


def _factory(_names: list[str]) -> DummyRegressor:
    return DummyRegressor()


def _walk_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, val in obj.items():
            found.add(str(key))
            found |= _walk_keys(val)
    elif isinstance(obj, list):
        for item in obj:
            found |= _walk_keys(item)
    return found


def _row(
    *,
    sample_id: int,
    instrument_id: int,
    as_of: date,
    target: date | None,
    y: float,
    fund: float | None = 0.4,
    event: float | None = 2.0,
    base: float = 0.01,
    valid: bool = True,
    eligible: bool = True,
    is_active: bool = True,
    issuer_resolution_basis: str = "DATED_WINDOW",
) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "instrument_id": instrument_id,
        "as_of_date": as_of,
        "y": y,
        "target_date_20d": target,
        "label_valid_20d": valid,
        "eligible_20d": eligible,
        BASE_FEAT: base,
        FUND_FEAT: np.nan if fund is None else fund,
        EVENT_FEAT: np.nan if event is None else event,
        "currently_active": is_active,
        "issuer_resolution_basis": issuer_resolution_basis,
    }


def test_chronological_purge_excludes_label_overlap() -> None:
    val_start = date(2024, 6, 1)
    val_end = date(2024, 7, 1)
    frame = pd.DataFrame(
        [
            _row(
                sample_id=1,
                instrument_id=1,
                as_of=date(2024, 5, 1),
                target=date(2024, 5, 29),
                y=0.01,
            ),
            _row(
                sample_id=2,
                instrument_id=1,
                as_of=date(2024, 5, 20),
                target=date(2024, 6, 17),
                y=0.02,
            ),
            _row(
                sample_id=3,
                instrument_id=1,
                as_of=val_start,
                target=date(2024, 6, 28),
                y=0.03,
            ),
            _row(
                sample_id=4,
                instrument_id=1,
                as_of=date(2024, 5, 10),
                target=None,
                y=0.04,
            ),
        ]
    )
    split = train_val_split_purged(frame, validation_start=val_start, validation_end=val_end)
    train_ids = set(split["train_df"]["sample_id"].tolist())
    val_ids = set(split["val_df"]["sample_id"].tolist())
    assert train_ids == {1}
    assert val_ids == {3}
    assert split["purged_train_boundary_rows"] >= 2
    assert (split["train_df"]["as_of_date"] < val_start).all()
    assert (split["train_df"]["target_date_20d"] < val_start).all()
    assert split["train_df"]["target_date_20d"].notna().all()


def test_ablation_identical_rows_and_mask_to_nan_not_zero() -> None:
    frame = pd.DataFrame(
        [
            _row(
                sample_id=1,
                instrument_id=1,
                as_of=date(2024, 1, 2),
                target=date(2024, 2, 1),
                y=0.05,
                fund=1.25,
                event=3.5,
                base=0.0,
            )
        ]
    )
    variants = {
        VARIANT_BASE: apply_ablation_mask(frame, VARIANT_BASE),
        VARIANT_BASE_FUNDAMENTALS: apply_ablation_mask(frame, VARIANT_BASE_FUNDAMENTALS),
        VARIANT_BASE_EVENTS: apply_ablation_mask(frame, VARIANT_BASE_EVENTS),
        VARIANT_V4_FULL: apply_ablation_mask(frame, VARIANT_V4_FULL),
    }
    for masked in variants.values():
        assert len(masked) == len(frame)
        assert masked["y"].tolist() == frame["y"].tolist()
        assert masked["sample_id"].tolist() == frame["sample_id"].tolist()
        assert masked[BASE_FEAT].iloc[0] == 0.0

    base = variants[VARIANT_BASE]
    assert pd.isna(base[FUND_FEAT].iloc[0])
    assert pd.isna(base[EVENT_FEAT].iloc[0])

    fund_only = variants[VARIANT_BASE_FUNDAMENTALS]
    assert fund_only[FUND_FEAT].iloc[0] == 1.25
    assert pd.isna(fund_only[EVENT_FEAT].iloc[0])

    event_only = variants[VARIANT_BASE_EVENTS]
    assert pd.isna(event_only[FUND_FEAT].iloc[0])
    assert event_only[EVENT_FEAT].iloc[0] == 3.5

    full = variants[VARIANT_V4_FULL]
    assert full[FUND_FEAT].iloc[0] == 1.25
    assert full[EVENT_FEAT].iloc[0] == 3.5


def test_ranking_metrics_do_not_expose_regression_keys() -> None:
    rows = []
    for day in range(5):
        as_of = date(2024, 3, 1) + timedelta(days=day)
        for inst in range(1, 13):
            rows.append(
                {
                    "as_of_date": as_of,
                    "instrument_id": inst,
                    "y": 0.01 * inst - 0.05,
                    "y_pred": float(inst) + day,
                }
            )
    metrics = ranking_metrics(pd.DataFrame(rows), min_ic_instruments=5, top_bottom_quantile=0.2)
    keys = _walk_keys(metrics)
    assert metrics["prediction_semantic"] == "RANKING_SCORE"
    assert "n" in metrics
    assert "rank_ic" in metrics
    assert "median_ic" in metrics
    assert "ic_dispersion" in metrics
    assert "positive_ic_date_share" in metrics
    assert "top_bottom" in metrics
    assert keys.isdisjoint(REGRESSION_METRIC_KEYS)
    assert "mae" not in metrics
    assert "rmse" not in metrics
    assert "r2" not in metrics


def _panel(*, n_dates: int, n_inst: int, start: date, pred_shift: float = 0.0) -> pd.DataFrame:
    rows = []
    for d in range(n_dates):
        as_of = start + timedelta(days=d)
        for inst in range(1, n_inst + 1):
            y = 0.01 * inst + 0.001 * d
            pred = float(inst) + pred_shift * d
            rows.append(
                {
                    "as_of_date": as_of,
                    "instrument_id": inst,
                    "y": y,
                    "y_pred": pred,
                }
            )
    return pd.DataFrame(rows)


def test_paired_bootstrap_deterministic() -> None:
    v4 = _panel(n_dates=12, n_inst=12, start=date(2024, 1, 1), pred_shift=0.2)
    base = _panel(n_dates=12, n_inst=12, start=date(2024, 1, 1), pred_shift=0.0)
    a = paired_v4_vs_base(v4, base, seed=42, iterations=200, min_ic_instruments=5, min_common_dates=10)
    b = paired_v4_vs_base(v4, base, seed=42, iterations=200, min_ic_instruments=5, min_common_dates=10)
    assert a["status"] == "ok"
    assert a["ic_delta"]["status"] == "ok"
    assert a["ic_delta"]["mean_delta"] == b["ic_delta"]["mean_delta"]
    assert a["ic_delta"]["ci95_low"] == b["ic_delta"]["ci95_low"]
    assert a["ic_delta"]["ci95_high"] == b["ic_delta"]["ci95_high"]
    assert a["top_bucket_realized_return_delta"]["mean_delta"] == b["top_bucket_realized_return_delta"][
        "mean_delta"
    ]
    assert a.get("p_value") is None
    assert "p_value" not in a["ic_delta"]
    assert a["n_common_dates"] >= 10


def test_paired_insufficient_dates_honest() -> None:
    v4 = _panel(n_dates=3, n_inst=12, start=date(2024, 1, 1), pred_shift=0.2)
    base = _panel(n_dates=3, n_inst=12, start=date(2024, 1, 1), pred_shift=0.0)
    out = paired_v4_vs_base(v4, base, seed=42, iterations=50, min_ic_instruments=5, min_common_dates=10)
    assert out["status"] == STATUS_INSUFFICIENT
    assert out["ic_delta"]["status"] == STATUS_INSUFFICIENT
    assert out["ic_delta"]["mean_delta"] is None
    assert out["ic_delta"]["ci95_low"] is None
    assert out.get("p_value") is None
    assert "p_value" not in out["ic_delta"]


def test_insufficient_oos_samples_honest() -> None:
    frame = pd.DataFrame(
        [
            _row(
                sample_id=1,
                instrument_id=1,
                as_of=date(2023, 1, 2),
                target=date(2023, 1, 20),
                y=0.01,
            ),
            _row(
                sample_id=2,
                instrument_id=1,
                as_of=date(2024, 6, 3),
                target=date(2024, 6, 28),
                y=0.02,
            ),
        ]
    )
    folds = [
        WalkForwardFold(
            fold_id=0,
            train_start=date(2023, 1, 1),
            train_end=date(2024, 6, 1),
            validation_start=date(2024, 6, 1),
            validation_end=date(2024, 7, 1),
        )
    ]
    out = run_chronological_oos(
        frame,
        semantic="regression",
        feature_names=FEATURE_NAMES,
        persist_registry=False,
        model_factory=_factory,
        folds=folds,
        min_train_n=100,
        min_val_n=20,
    )
    assert out["status"] == STATUS_INSUFFICIENT
    assert out["metrics"] is None
    assert out["persist_registry"] is False
    assert out["evaluation_kind"] == EVALUATION_KIND
    assert out["evaluation_kind"] == "CHRONOLOGICAL OOS RESEARCH"
    assert "holdout" not in out["evaluation_kind"].lower()


def test_ablation_suite_same_rows_no_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def _forbid_upsert(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        raise AssertionError("ModelRegistry upsert is forbidden on research OOS")

    monkeypatch.setattr(
        "app.modules.prediction.infrastructure.registry.upsert_model_registry_row",
        _forbid_upsert,
    )

    rows = []
    sample_id = 1
    train_days = [date(2023, 1, 2) + timedelta(days=i) for i in range(8)]
    val_days = [date(2024, 6, 3) + timedelta(days=i) for i in range(6)]
    for as_of in train_days + val_days:
        for inst in range(1, 6):
            rows.append(
                _row(
                    sample_id=sample_id,
                    instrument_id=inst,
                    as_of=as_of,
                    target=as_of + timedelta(days=10),
                    y=0.01 * inst,
                    fund=0.2 * inst,
                    event=1.0 * inst,
                    base=0.01 * inst,
                    is_active=inst % 2 == 0,
                    issuer_resolution_basis="DATED_WINDOW" if inst < 4 else "CURRENT_ONLY",
                )
            )
            sample_id += 1
    frame = pd.DataFrame(rows)
    folds = [
        WalkForwardFold(
            fold_id=0,
            train_start=date(2023, 1, 1),
            train_end=date(2024, 6, 1),
            validation_start=date(2024, 6, 1),
            validation_end=date(2024, 7, 1),
        )
    ]
    out = run_v4_ablation(
        frame,
        semantic="ranking",
        feature_names=FEATURE_NAMES,
        persist_registry=False,
        model_factory=_factory,
        folds=folds,
        min_train_n=5,
        min_val_n=5,
        random_seed=42,
    )
    assert calls == []
    assert out["persist_registry"] is False
    assert out["same_rows"] is True
    assert out["n_rows"] == len(frame)
    for name in (VARIANT_BASE, VARIANT_BASE_FUNDAMENTALS, VARIANT_BASE_EVENTS, VARIANT_V4_FULL):
        payload = out["variants"][name]
        assert payload["n_rows"] == len(frame)
        assert payload["persist_registry"] is False
        assert payload["evaluation_kind"] == EVALUATION_KIND
        assert payload["status"] == "ok"
        metrics = payload["metrics"]
        assert metrics is not None
        assert _walk_keys(metrics).isdisjoint(REGRESSION_METRIC_KEYS)
        preds = payload["predictions"]
        assert len(preds) == len(out["variants"][VARIANT_V4_FULL]["predictions"])

    with pytest.raises(ResearchOosError, match="must not persist"):
        run_v4_ablation(
            frame,
            semantic="ranking",
            feature_names=FEATURE_NAMES,
            persist_registry=True,
            model_factory=_factory,
            folds=folds,
            min_train_n=5,
            min_val_n=5,
        )
    assert calls == []


def test_stability_skips_ungrounded_and_slices_grounded() -> None:
    rows = []
    for d in range(4):
        as_of = date(2024, 1, 1) + timedelta(days=d)
        for inst in range(1, 10):
            rows.append(
                {
                    "as_of_date": as_of,
                    "instrument_id": inst,
                    "y": 0.01 * inst,
                    "y_pred": float(inst),
                    "fold_id": 0,
                    "currently_active": inst < 6,
                    "issuer_resolution_basis": "DATED_WINDOW" if inst < 5 else "CURRENT_ONLY",
                    FUND_FEAT: 0.3 if inst < 5 else np.nan,
                    EVENT_FEAT: 2.0 if inst >= 5 else np.nan,
                }
            )
    report = slice_stability(
        pd.DataFrame(rows),
        semantic="ranking",
        min_ic_instruments=3,
        min_rows=8,
    )
    assert "by_fold" in report["slices"]
    assert "by_calendar_year" in report["slices"]
    assert "current_active" in report["slices"]
    assert "currently_inactive" in report["slices"]
    assert "issuer_identity_DATED_WINDOW" in report["slices"]
    assert "fund_features_present" in report["slices"]
    bare = pd.DataFrame(
        [{"as_of_date": date(2024, 1, 1), "instrument_id": 1, "y": 0.1, "y_pred": 0.2, "fold_id": 0}]
        * 12
    )
    bare_report = slice_stability(bare, semantic="regression", min_rows=8)
    assert "current_active" not in bare_report["slices"]
    assert "issuer_identity_DATED_WINDOW" not in bare_report["slices"]
    assert "fund_features_present" not in bare_report["slices"]
