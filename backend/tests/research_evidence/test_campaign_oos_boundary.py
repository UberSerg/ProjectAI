"""Canonical campaign OOS must evaluate campaign date_to, not Candidate HOLDOUT_START."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
from app.modules.prediction.application.splits import build_expanding_folds
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, HOLDOUT_START, CandidateV0Config
from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig
from app.modules.research_evidence.campaign_contract import (
    EVALUATION_END_POLICY,
    SUPERSEDED_CAMPAIGN_FINGERPRINTS,
    CanonicalEvidenceCampaignV1,
)
from app.modules.research_evidence.campaign_dossier import (
    DossierImmutabilityError,
    campaign_artifact_dir,
    persist_evidence_dossier,
)
from app.modules.research_evidence.campaign_oos import run_paired_v3_v4_evidence_campaign
from app.modules.research_evidence.campaign_runner import run_canonical_evidence_campaign_v1
from app.modules.research_evidence.campaign_window import (
    CampaignOosBoundaryError,
    assert_canonical_oos_schedule,
    campaign_development_end_exclusive,
    expanding_oos_fold_count,
)
from app.modules.research_evidence.oos import normalize_folds
from tests.research_evidence.test_campaign_adversarial import _inspect_ready, _pair_ok
from tests.research_evidence.test_campaign_oos import FEATURE_NAMES, _factory, _panel_frame
from tests.research_evidence.test_campaign_runner import _ok_snapshot


def _canonical_snapshot(*, date_to: date = date(2026, 9, 1)) -> dict:
    date_from = date(2022, 4, 1)
    fold_n = expanding_oos_fold_count(date_from=date_from, date_to=date_to)
    payload = _ok_snapshot()
    payload["campaign_window_status"] = "OK"
    payload["campaign_window"] = {
        "status": "OK",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "primary": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "expanding_oos": {"fold_count": fold_n, "shortened_training": False},
    }
    return payload


def _eligible_frame(*, start: date, end: date) -> pd.DataFrame:
    rows: list[dict] = []
    day = start
    sample_id = 1
    while day <= end:
        if day.weekday() < 5:
            rows.append(
                {
                    "sample_id": sample_id,
                    "as_of_date": day,
                    "instrument_id": 1,
                    "y": 0.01,
                    "label_valid_20d": True,
                    "eligible_20d": True,
                    "target_date_20d": day + timedelta(days=40),
                }
            )
            sample_id += 1
        day += timedelta(days=1)
    return pd.DataFrame(rows)


def test_canonical_oos_does_not_truncate_at_holdout_start() -> None:
    date_to = date(2026, 9, 1)
    exclusive = campaign_development_end_exclusive(date_to)
    assert exclusive == date(2026, 9, 2)
    assert date_to > HOLDOUT_START
    frame = _eligible_frame(start=date(2022, 4, 1), end=date_to)
    folds = normalize_folds(None, frame, development_end_exclusive=exclusive)
    holdout_folds = normalize_folds(None, frame)
    assert folds[-1].validation_end == exclusive
    assert folds[-1].validation_end > HOLDOUT_START
    assert holdout_folds[-1].validation_end == HOLDOUT_START
    assert len(folds) > len(holdout_folds)
    expected = expanding_oos_fold_count(date_from=date(2022, 4, 1), date_to=date_to)
    assert_canonical_oos_schedule(
        folds,
        date_from=date(2022, 4, 1),
        date_to=date_to,
        expected_fold_count=expected,
        development_end_exclusive=exclusive,
    )


def test_fold_count_matches_campaign_window_and_last_fold_clips() -> None:
    date_from = date(2022, 4, 1)
    date_to = date(2026, 9, 1)
    exclusive = campaign_development_end_exclusive(date_to)
    expected = expanding_oos_fold_count(date_from=date_from, date_to=date_to)
    folds = build_expanding_folds(
        data_start=date_from,
        development_end_exclusive=exclusive,
        config=CANDIDATE_V0_CONFIG,
    )
    assert len(folds) == expected
    assert folds[0].validation_start == date(2025, 4, 1)
    assert folds[-1].validation_end == exclusive
    with pytest.raises(CampaignOosBoundaryError, match="fold count"):
        assert_canonical_oos_schedule(
            folds[:2],
            date_from=date_from,
            date_to=date_to,
            expected_fold_count=expected,
            development_end_exclusive=exclusive,
        )
    with pytest.raises(CampaignOosBoundaryError, match="date_to \\+ 1 day"):
        assert_canonical_oos_schedule(
            folds,
            date_from=date_from,
            date_to=date_to,
            expected_fold_count=expected,
            development_end_exclusive=HOLDOUT_START,
        )


def test_runner_passes_date_to_plus_one_and_fold_count(tmp_path: Path) -> None:
    captured: dict = {}
    snapshot = _canonical_snapshot()
    expected_folds = snapshot["campaign_window"]["expanding_oos"]["fold_count"]

    def oos_fn(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "status": "ok",
            "regression": {"status": "ok", "folds": []},
            "ranking": {"status": "ok"},
            "ablation": {"variants": {}},
            "stability": {},
        }

    def economics_fn(**_k: object) -> dict:
        return {"status": "INSUFFICIENT"}

    run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id="oos-boundary",
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: snapshot,
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run, "before": {}, "after": {}},
        pair_fn=lambda *_a, **_k: _pair_ok(date_to="2026-09-01"),
        oos_fn=oos_fn,
        economics_fn=economics_fn,
        market_loader=lambda *_a, **_k: SimpleNamespace(trading_days=[]),
    )
    assert captured["development_end_exclusive"] == date(2026, 9, 2)
    assert captured["campaign_date_to"] == date(2026, 9, 1)
    assert captured["campaign_date_from"] == date(2022, 4, 1)
    assert captured["expected_fold_count"] == expected_folds


def test_economics_receives_canonical_oos_prediction_dates(tmp_path: Path) -> None:
    late = date(2026, 6, 15)
    frame = pd.DataFrame(
        {
            "as_of_date": [late, late],
            "instrument_id": [1, 2],
            "y_pred": [0.2, -0.1],
            "fold_id": [2, 2],
        }
    )
    captured: dict = {}

    def oos_fn(**_k: object) -> dict:
        variant = {
            "predictions": frame,
            "folds": [{"fold_id": 2, "train_end": "2026-04-01"}],
        }
        return {
            "status": "ok",
            "regression": {"status": "ok"},
            "ranking": {"status": "ok"},
            "ablation": {
                "variants": {
                    "BASE": variant,
                    "BASE+FUNDAMENTALS": variant,
                    "BASE+EVENTS": variant,
                    "V4_FULL": variant,
                }
            },
            "stability": {},
        }

    def economics_fn(*, predictions: pd.DataFrame, market: object) -> dict:
        captured["max_decision"] = pd.to_datetime(predictions["decision_date"]).max().date()
        captured["n"] = int(len(predictions))
        return {
            "status": "COMPLETE",
            "primary_settings": {},
            "primary": {},
            "matrix": [],
            "cells_enumerated_before_metrics": True,
        }

    days = [late + timedelta(days=i) for i in range(1, 40) if (late + timedelta(days=i)).weekday() < 5]
    run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id="econ-boundary",
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _canonical_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run, "before": {}, "after": {}},
        pair_fn=lambda *_a, **_k: _pair_ok(date_to="2026-09-01"),
        oos_fn=oos_fn,
        economics_fn=economics_fn,
        market_loader=lambda *_a, **_k: SimpleNamespace(trading_days=days),
    )
    assert captured["max_decision"] == late
    assert captured["max_decision"] > HOLDOUT_START


def test_candidate_v0_v1_keep_holdout_start() -> None:
    assert CandidateV0Config().holdout_start == HOLDOUT_START == date(2026, 1, 1)
    assert CandidateV1RankerConfig().holdout_start == HOLDOUT_START
    assert CandidateV0Config().dataset_spec_version == 2
    assert CandidateV1RankerConfig().dataset_spec_version == 2
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    pred_root = Path(__file__).resolve().parents[2] / "app" / "modules" / "prediction" / "application"
    assert "development_end_exclusive=holdout_start" in (pred_root / "runner.py").read_text(
        encoding="utf-8"
    )
    assert "development_end_exclusive=holdout_start" in (pred_root / "runner_v1.py").read_text(
        encoding="utf-8"
    )


def test_identity_includes_campaign_date_to_evaluation_policy() -> None:
    campaign = CanonicalEvidenceCampaignV1(
        dataset_v3_run_id=655,
        dataset_v4_run_id=659,
        dataset_v3_hash="v3",
        dataset_v4_hash="v4",
        date_from="2022-04-01",
        date_to="2026-09-01",
    )
    wf = campaign.identity_payload()["walk_forward_contract"]
    assert wf["evaluation_end_policy"] == EVALUATION_END_POLICY
    assert wf["evaluation_end_inclusive"] == "2026-09-01"
    assert wf["development_end_exclusive"] == "2026-09-02"
    assert campaign.campaign_fingerprint not in SUPERSEDED_CAMPAIGN_FINGERPRINTS


def test_superseded_dossier_is_not_overwritten(tmp_path: Path) -> None:
    fp = next(iter(SUPERSEDED_CAMPAIGN_FINGERPRINTS))
    dest = campaign_artifact_dir(fp, root=tmp_path)
    dest.mkdir(parents=True)
    marker = dest / "evidence_dossier.json"
    marker.write_text(
        f'{{"campaign_fingerprint":"{fp}","marker":"immutable-old"}}',
        encoding="utf-8",
    )
    with pytest.raises(DossierImmutabilityError, match="OOS_EVALUATION_BOUNDARY_MISMATCH"):
        persist_evidence_dossier({"campaign_fingerprint": fp, "identity": {}}, artifact_root=tmp_path)
    assert "immutable-old" in marker.read_text(encoding="utf-8")
    with pytest.raises(DossierImmutabilityError, match="superseded"):
        run_canonical_evidence_campaign_v1(
            MagicMock(),
            None,
            workflow_id="must-not-reuse-old-fp",
            persist_registry=False,
            artifact_root=tmp_path,
            snapshot_builder=lambda _s: _canonical_snapshot(),
            inspect_fn=lambda _s: _inspect_ready(),
            refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run, "before": {}, "after": {}},
            pair_fn=lambda *_a, **_k: _pair_ok(fingerprint=fp, date_to="2026-09-01"),
            oos_fn=lambda **_k: {"status": "ok", "ablation": {"variants": {}}},
            economics_fn=lambda **_k: {"status": "COMPLETE"},
        )
    assert "immutable-old" in marker.read_text(encoding="utf-8")


def test_synthetic_campaign_oos_without_boundary_still_runs() -> None:
    out = run_paired_v3_v4_evidence_campaign(
        _panel_frame(),
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=None,
        min_train_n=5,
        min_val_n=5,
    )
    assert out["status"] in {"ok", "insufficient", "INSUFFICIENT"}
