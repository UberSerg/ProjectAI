"""Focused tests for Canonical Evidence Campaign V1 runner and API wiring."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.learning.application.research_eval import FairCompareError
from app.modules.research_evidence.campaign_runner import (
    CAMPAIGN_WORKFLOW_STEPS,
    PUBLIC_CAMPAIGN_VERSION,
    jsonable_campaign_payload,
    run_canonical_evidence_campaign_v1,
    stamp_oos_predictions_for_economics,
)
from app.modules.research_evidence.campaign_window import STATUS_INSUFFICIENT as CAMPAIGN_DATA_INSUFFICIENT
from app.modules.research_evidence.economics import MODEL_VARIANTS, validate_oos_prediction_frame


def _ok_snapshot() -> dict:
    return {
        "schema": "research_data_snapshot_v1",
        "data_snapshot_hash": "ab" * 32,
        "created_at": "2026-01-01T00:00:00+00:00",
        "campaign_window_status": "OK",
        "campaign_window": {
            "status": "OK",
            "date_from": "2022-04-01",
            "date_to": "2025-06-01",
        },
        "domains": [],
        "overall_availability": "PARTIAL",
    }


def _insufficient_snapshot() -> dict:
    payload = _ok_snapshot()
    payload["campaign_window_status"] = CAMPAIGN_DATA_INSUFFICIENT
    payload["campaign_window"] = {
        "status": CAMPAIGN_DATA_INSUFFICIENT,
        "date_from": "2022-04-01",
        "date_to": "2023-01-01",
        "reason": "window too short",
    }
    return payload


def _inspect_ready() -> dict:
    return {
        "equity_instruments": 10,
        "daily_equity_candles": 1000,
        "instruments_with_daily_history": 10,
        "fns_gir_bo_reports": 5,
        "fundamentals_schema_ready": True,
    }


def test_campaign_window_source_independent_of_oos_economics() -> None:
    import inspect

    import app.modules.research_evidence.campaign_window as mod

    source = inspect.getsource(mod)
    assert "research_evidence.oos" not in source
    assert "research_evidence.economics" not in source
    assert "run_research_economics" not in source
    assert "cross_sectional_ic" not in source


def test_campaign_data_insufficient_skips_oos_economics(tmp_path: Path) -> None:
    oos_calls: list[int] = []
    econ_calls: list[int] = []
    pair_calls: list[int] = []

    def oos_fn(**_k: object) -> dict:
        oos_calls.append(1)
        raise AssertionError("OOS must not run")

    def economics_fn(**_k: object) -> dict:
        econ_calls.append(1)
        raise AssertionError("economics must not run")

    def pair_fn(*_a: object, **_k: object) -> dict:
        pair_calls.append(1)
        raise AssertionError("pair must not run")

    result = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=1,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _insufficient_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run, "before": {}, "after": {}},
        pair_fn=pair_fn,
        oos_fn=oos_fn,
        economics_fn=economics_fn,
    )
    assert result["block_code"] == CAMPAIGN_DATA_INSUFFICIENT
    assert oos_calls == []
    assert econ_calls == []
    assert pair_calls == []
    assert result["persist_registry"] is False


def test_fair_contract_fail_skips_oos_economics(tmp_path: Path) -> None:
    oos_calls: list[int] = []
    econ_calls: list[int] = []

    def pair_fn(*_a: object, **_k: object) -> dict:
        raise FairCompareError("FAIR_CONTRACT_FAIL: sample identity mismatch")

    def oos_fn(**_k: object) -> dict:
        oos_calls.append(1)
        raise AssertionError("OOS must not run")

    def economics_fn(**_k: object) -> dict:
        econ_calls.append(1)
        raise AssertionError("economics must not run")

    result = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=2,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _ok_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
        pair_fn=pair_fn,
        oos_fn=oos_fn,
        economics_fn=economics_fn,
    )
    assert result["block_code"] == "FAIR_CONTRACT_FAIL"
    assert oos_calls == []
    assert econ_calls == []


def test_resume_skips_completed_stages_with_matching_identity(tmp_path: Path) -> None:
    snaps = {"n": 0}

    def snapshot_builder(_s: object) -> dict:
        snaps["n"] += 1
        return _insufficient_snapshot()

    first = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=3,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=snapshot_builder,
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
        oos_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("oos")),
        economics_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("econ")),
    )
    second = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=3,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=snapshot_builder,
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
        oos_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("oos")),
        economics_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("econ")),
    )
    assert first["block_code"] == CAMPAIGN_DATA_INSUFFICIENT
    assert "DATA_SNAPSHOT" in second["skipped_stages"]
    assert "SAFE_DATA_REFRESH" in second["skipped_stages"]
    assert snaps["n"] == 1


def test_route_campaigns_not_swallowed_by_experiment_id() -> None:
    from app.api.v1.research_evidence import list_evidence_campaigns, router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert "/campaigns" in paths
    assert "/{experiment_id}" in paths
    assert paths.index("/campaigns") < paths.index("/{experiment_id}")
    payload = list_evidence_campaigns()
    assert "items" in payload
    assert "campaigns" in payload


def test_launch_rejects_wrong_campaign_version() -> None:
    from app.api.v1.research_evidence import CanonicalCampaignLaunchRequest, launch_canonical_campaign_v1

    with pytest.raises(HTTPException) as exc:
        launch_canonical_campaign_v1(CanonicalCampaignLaunchRequest(campaign_version="other"))
    assert exc.value.status_code == 400


def test_launch_request_only_version_and_exact_rerun() -> None:
    from app.api.v1.research_evidence import CanonicalCampaignLaunchRequest

    fields = set(CanonicalCampaignLaunchRequest.model_fields)
    assert fields == {"campaign_version", "exact_rerun"}
    with pytest.raises(ValidationError):
        CanonicalCampaignLaunchRequest(
            campaign_version=PUBLIC_CAMPAIGN_VERSION,
            instrument_ids=[1],
            date_from="2022-04-01",
        )


def test_persist_registry_false(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="persist_registry"):
        run_canonical_evidence_campaign_v1(
            MagicMock(),
            workflow_id=9,
            persist_registry=True,
            artifact_root=tmp_path,
        )
    result = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=10,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _insufficient_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
    )
    assert result["persist_registry"] is False
    root = Path(__file__).resolve().parents[2] / "app" / "modules" / "research_evidence"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    assert "persist_registry=True" not in text
    assert "persist_registry = True" not in text


def test_production_isolation_still_holds() -> None:
    from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
    from app.modules.prediction.candidate_config import CandidateV0Config
    from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig

    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    assert CandidateV0Config().dataset_spec_version == 2
    assert CandidateV1RankerConfig().dataset_spec_version == 2


def test_dataframes_not_in_dossier_json(tmp_path: Path) -> None:
    frame = pd.DataFrame({"y_pred": [0.1], "instrument_id": [1]})
    payload = jsonable_campaign_payload(
        {
            "metrics": {"n": 1, "rank_ic": {"mean_ic": 0.2}},
            "predictions": frame,
            "nested": {"predictions": frame, "ok": 1},
        }
    )
    assert "predictions" not in payload
    assert payload["nested"]["ok"] == 1
    assert "predictions" not in payload["nested"]
    import json

    json.dumps(payload)

    result = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=11,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _insufficient_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
    )
    dossier_dirs = list((tmp_path / "research_evidence" / "campaigns").glob("*"))
    assert dossier_dirs or result["fingerprint"]
    from app.modules.research_evidence.campaign_dossier import DOSSIER_FILENAME, campaign_artifact_dir

    fp = result["fingerprint"]
    path = campaign_artifact_dir(str(fp), root=tmp_path) / DOSSIER_FILENAME
    raw = path.read_text(encoding="utf-8")
    assert "DataFrame" not in raw
    assert '"predictions"' not in raw or "null" in raw


def test_economics_receives_stamped_oos_frames() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [date(2024, 6, 3), date(2024, 6, 4)],
            "instrument_id": [1, 2],
            "y_pred": [0.2, -0.1],
            "fold_id": [0, 0],
        }
    )
    stamped = stamp_oos_predictions_for_economics(
        frame,
        model_variant="BASE+FUNDAMENTALS",
        folds=[{"fold_id": 0, "train_end": "2024-06-01"}],
        fingerprint="fp",
        values_hash="vh",
    )
    assert list(stamped["model_variant"].unique()) == ["FUNDAMENTALS"]
    assert stamped["is_oos"].all()
    assert "decision_date" in stamped.columns
    assert stamped["train_cutoff"].notna().all()
    assert stamped["score_is_not_return_pct"].all()
    checked = validate_oos_prediction_frame(stamped, model_variant="FUNDAMENTALS")
    assert not checked.empty
    assert "FUNDAMENTALS" in MODEL_VARIANTS


def test_workflow_step_names() -> None:
    assert CAMPAIGN_WORKFLOW_STEPS == (
        "DATA_SNAPSHOT",
        "SAFE_DATA_REFRESH",
        "BUILD_V3",
        "BUILD_V4",
        "FAIR_PAIR_PROOF",
        "OOS_REGRESSION",
        "OOS_RANKER",
        "ABLATION",
        "STABILITY",
        "ECONOMICS_PRIMARY",
        "ECONOMICS_ROBUSTNESS",
        "PROSPECTIVE_SNAPSHOT",
        "DOSSIER",
        "FINALIZE",
    )
