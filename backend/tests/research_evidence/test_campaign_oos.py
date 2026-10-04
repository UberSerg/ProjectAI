"""Paired V3/V4 evidence campaign — synthetic DummyRegressor frames only."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
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
)
from app.modules.research_evidence.campaign_oos import (
    PAIRED_DELTA_SPECS,
    run_paired_v3_v4_evidence_campaign,
)
from app.modules.research_evidence.oos import (
    EVALUATION_KIND,
    REGRESSION_METRIC_KEYS,
    STATUS_INSUFFICIENT,
    ResearchOosError,
    train_val_split_purged,
)

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
        "currently_active": True,
        "issuer_resolution_basis": "DATED_WINDOW",
    }


def _campaign_folds() -> list[WalkForwardFold]:
    return [
        WalkForwardFold(
            fold_id=0,
            train_start=date(2023, 1, 1),
            train_end=date(2024, 6, 1),
            validation_start=date(2024, 6, 1),
            validation_end=date(2024, 7, 1),
        )
    ]


def _panel_frame(*, extra_purge: bool = False) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
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
                )
            )
            sample_id += 1
    if extra_purge:
        rows.append(
            _row(
                sample_id=sample_id,
                instrument_id=1,
                as_of=date(2024, 5, 20),
                target=date(2024, 6, 17),
                y=0.99,
            )
        )
        rows.append(
            _row(
                sample_id=sample_id + 1,
                instrument_id=1,
                as_of=date(2024, 5, 10),
                target=None,
                y=0.88,
            )
        )
    return pd.DataFrame(rows)


def test_campaign_purge_excludes_label_overlap() -> None:
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
    assert set(split["train_df"]["sample_id"].tolist()) == {1}
    assert set(split["val_df"]["sample_id"].tolist()) == {3}
    assert split["purged_train_boundary_rows"] >= 2

    panel = _panel_frame(extra_purge=True)
    out = run_paired_v3_v4_evidence_campaign(
        panel,
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=_campaign_folds(),
        min_train_n=5,
        min_val_n=5,
    )
    fold = out["regression"]["folds"][0]
    assert fold["purged_train_boundary_rows"] >= 2
    assert (split["train_df"]["as_of_date"] < val_start).all()
    assert (split["train_df"]["target_date_20d"] < val_start).all()


def test_campaign_identical_ablation_rows_mask_nan_not_drop() -> None:
    frame = _panel_frame()
    out = run_paired_v3_v4_evidence_campaign(
        frame,
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=_campaign_folds(),
        min_train_n=5,
        min_val_n=5,
    )
    ablation = out["ablation"]
    assert ablation["same_rows"] is True
    assert ablation["same_y"] is True
    assert ablation["n_rows"] == len(frame)
    assert out["n_rows"] == len(frame)
    for name in (VARIANT_BASE, VARIANT_BASE_FUNDAMENTALS, VARIANT_BASE_EVENTS, VARIANT_V4_FULL):
        payload = ablation["variants"][name]
        assert payload["n_rows"] == len(frame)
        assert len(payload["predictions"]) == len(ablation["variants"][VARIANT_V4_FULL]["predictions"])
        masked = payload["masked_columns"]
        if name == VARIANT_BASE:
            assert FUND_FEAT in masked and EVENT_FEAT in masked
        if name == VARIANT_V4_FULL:
            assert masked == []
    assert tuple(label for label, _variant in PAIRED_DELTA_SPECS) == (
        "V4_FULL_vs_BASE",
        "FUNDAMENTALS_vs_BASE",
        "EVENTS_vs_BASE",
    )
    for label, _variant in PAIRED_DELTA_SPECS:
        delta = out["paired_deltas"][label]
        assert "ic_delta" in delta
        assert delta.get("p_value") is None
        assert delta["method"] == "bootstrap_trading_dates"


def test_campaign_insufficient_honest() -> None:
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
    out = run_paired_v3_v4_evidence_campaign(
        frame,
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=_campaign_folds(),
        min_train_n=100,
        min_val_n=20,
    )
    assert out["status"] == STATUS_INSUFFICIENT
    assert out["regression"]["status"] == STATUS_INSUFFICIENT
    assert out["ranking"]["status"] == STATUS_INSUFFICIENT
    assert out["regression"]["metrics"] is None
    assert out["ranking"]["metrics"] is None
    for label, _variant in PAIRED_DELTA_SPECS:
        delta = out["paired_deltas"][label]
        assert delta["status"] == STATUS_INSUFFICIENT
        assert delta["ic_delta"]["mean_delta"] is None
        assert delta["ic_delta"]["ci95_low"] is None
        assert delta.get("p_value") is None
    assert out["optuna"] is False
    assert out["hyperparameter_search"] is None
    assert "winner" not in out["note"].lower()
    assert out["evaluation_kind"] == EVALUATION_KIND
    assert "holdout" not in out["evaluation_kind"].lower()


def test_winner_wording_allows_coverage_disclaimer() -> None:
    from app.modules.research_evidence.campaign_oos import assert_no_winner_wording

    assert_no_winner_wording(
        {
            "notes": [
                "Never interpret as Candidate promotion, live-money readiness, or 'V4 wins'.",
            ]
        }
    )
    with pytest.raises(ResearchOosError, match="winner wording"):
        assert_no_winner_wording({"note": "V4 wins the campaign"})


def test_campaign_no_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def _forbid_upsert(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        raise AssertionError("ModelRegistry upsert is forbidden on research campaign")

    monkeypatch.setattr(
        "app.modules.prediction.infrastructure.registry.upsert_model_registry_row",
        _forbid_upsert,
    )
    frame = _panel_frame()
    out = run_paired_v3_v4_evidence_campaign(
        frame,
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=_campaign_folds(),
        min_train_n=5,
        min_val_n=5,
    )
    assert calls == []
    assert out["persist_registry"] is False
    assert out["regression"]["persist_registry"] is False
    assert out["ranking"]["persist_registry"] is False
    assert out["ablation"]["persist_registry"] is False
    ranking_keys = _walk_keys(out["ranking"]["metrics"])
    assert ranking_keys.isdisjoint(REGRESSION_METRIC_KEYS)
    assert "mae" not in out["ranking"]["metrics"]
    assert "rmse" not in out["ranking"]["metrics"]
    with pytest.raises(ResearchOosError, match="must not persist"):
        run_paired_v3_v4_evidence_campaign(
            frame,
            persist_registry=True,
            model_factory=_factory,
            feature_names=FEATURE_NAMES,
            folds=_campaign_folds(),
            min_train_n=5,
            min_val_n=5,
        )
    assert calls == []


def test_campaign_session_loads_dataset_run(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _panel_frame()
    loaded_ids: list[int] = []

    def _fake_prove(session: Any, v3_run_id: int, v4_run_id: int) -> dict[str, Any]:
        assert v3_run_id == 3
        assert v4_run_id == 4
        return {"fair_contract_status": "PASS", "sample_identity_match": True}

    def _fake_load(session: Any, *, dataset_spec_version: int, dataset_run_id: int) -> tuple[Any, pd.DataFrame]:
        loaded_ids.append(dataset_run_id)
        assert dataset_spec_version == 4
        return SimpleNamespace(id=dataset_run_id), frame.copy()

    monkeypatch.setattr(
        "app.modules.research_evidence.campaign_oos.prove_paired_v3_v4",
        _fake_prove,
    )
    monkeypatch.setattr(
        "app.modules.research_evidence.campaign_oos.load_research_frame",
        _fake_load,
    )
    out = run_paired_v3_v4_evidence_campaign(
        session=object(),
        v3_run_id=3,
        v4_run_id=4,
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=_campaign_folds(),
        min_train_n=5,
        min_val_n=5,
    )
    assert loaded_ids == [4]
    assert out["dataset_v4_run_id"] == 4
    assert out["pairing"]["fair_contract_status"] == "PASS"
    assert out["persist_registry"] is False
