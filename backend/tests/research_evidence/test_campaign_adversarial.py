"""Adversarial verifier for Canonical Evidence Campaign V1 invariants."""

from __future__ import annotations

import ast
import inspect
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.learning.application.research_eval import FairCompareError
from app.modules.learning.dataset_config import V4_FUNDAMENTAL_FEATURE_NAMES
from app.modules.research_evidence.ablation import apply_ablation_mask
from app.modules.research_evidence.campaign_contract import (
    CAMPAIGN_VERSION,
    CanonicalEvidenceCampaignV1,
    default_economic_primary_contract,
)
from app.modules.research_evidence.campaign_dossier import (
    FORBIDDEN_DOSSIER_KEYS,
    STATUS_EMPTY,
    STATUS_INSUFFICIENT_SAMPLE,
    STATUS_OBSERVED,
    DossierImmutabilityError,
    build_evidence_dossier_v1,
    classify_prospective_completeness,
    persist_evidence_dossier,
)
from app.modules.research_evidence.campaign_runner import (
    PUBLIC_CAMPAIGN_VERSION,
    jsonable_campaign_payload,
    map_data_quality,
    map_identity_for_ui,
    run_canonical_evidence_campaign_v1,
    stamp_oos_predictions_for_economics,
)
from app.modules.research_evidence.campaign_window import (
    PRIMARY_DATE_FROM,
    campaign_primary_bounds,
    latest_mature_20d_as_of,
    resolve_campaign_window,
)
from app.modules.research_evidence.economics import SKIPPED_BY_BOUNDARY, validate_oos_prediction_frame
from app.modules.research_evidence.oos import REGRESSION_METRIC_KEYS, ranking_metrics

RESEARCH_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules" / "research_evidence"


def _weekdays(start: date, count: int) -> list[date]:
    day = start
    out: list[date] = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _inspect_ready() -> dict:
    return {
        "equity_instruments": 10,
        "daily_equity_candles": 1000,
        "instruments_with_daily_history": 10,
        "fns_gir_bo_reports": 5,
        "fundamentals_schema_ready": True,
    }


def _nested_ok_snapshot() -> dict:
    window = resolve_campaign_window(_weekdays(date(2022, 4, 1), 1100))
    assert "date_from" not in window
    assert window["primary"]["date_from"] == "2022-04-01"
    return {
        "schema": "research_data_snapshot_v1",
        "data_snapshot_hash": "ab" * 32,
        "created_at": "2026-01-01T00:00:00+00:00",
        "campaign_window_status": window["status"],
        "campaign_window": window,
        "domains": [],
        "overall_availability": "PARTIAL",
    }


def _pair_ok(*, fingerprint: str = "cafef00d" * 8, identity_tag: str = "ok", **extra: object) -> dict:
    proof = {
        "dataset_v3_run_id": 3,
        "dataset_v4_run_id": 4,
        "fair_contract_status": "PASS",
        "sample_identity_match": True,
        "target_identity_match": True,
        "pit_status": "PASS",
        "pit_violations": 0,
        "v3": {"pit_status": "PASS", "pit_violations": 0},
        "v4": {"pit_status": "PASS", "pit_violations": 0},
        "dataset_v4_values_hash": "vh",
        "date_from": "2022-04-01",
        "date_to": "2025-06-01",
    }
    proof.update(extra)
    return {
        "campaign_fingerprint": fingerprint,
        "campaign": {
            "campaign_fingerprint": fingerprint,
            "identity": {
                "campaign_version": CAMPAIGN_VERSION,
                "date_from": "2022-04-01",
                "date_to": "2025-06-01",
                "identity_tag": identity_tag,
            },
        },
        "proof": proof,
        "fair_contract_status": "PASS",
    }


def _run(
    tmp_path: Path,
    *,
    workflow_id: int,
    snapshot: dict,
    pair_fn,
    oos_fn=None,
    economics_fn=None,
    market_loader=None,
):
    return run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id=workflow_id,
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: snapshot,
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
        pair_fn=pair_fn,
        oos_fn=oos_fn or (lambda **_k: (_ for _ in ()).throw(AssertionError("oos"))),
        economics_fn=economics_fn or (lambda **_k: (_ for _ in ()).throw(AssertionError("econ"))),
        market_loader=market_loader,
    )


def test_01_window_not_from_performance_and_nested_bounds(tmp_path: Path) -> None:
    source = inspect.getsource(
        __import__("app.modules.research_evidence.campaign_window", fromlist=["x"])
    )
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    joined = " ".join(imported)
    assert "research_evidence.oos" not in joined
    assert "research_evidence.economics" not in joined
    assert "cross_sectional_ic" not in source
    sessions = _weekdays(date(2022, 4, 1), 1100)
    window = resolve_campaign_window(sessions)
    assert window["primary"]["date_from"] == PRIMARY_DATE_FROM.isoformat()
    assert date.fromisoformat(window["primary"]["date_to"]) == latest_mature_20d_as_of(sessions)
    date_from, date_to = campaign_primary_bounds(window)
    captured: dict = {}

    def pair_fn(*_a: object, **kwargs: object) -> dict:
        captured.update(kwargs)
        raise FairCompareError("FAIR_CONTRACT_FAIL: stop after reading window")

    result = _run(tmp_path, workflow_id=101, snapshot=_nested_ok_snapshot(), pair_fn=pair_fn)
    assert captured["date_from"] == date.fromisoformat(str(date_from))
    assert captured["date_to"] == date.fromisoformat(str(date_to))
    assert captured["instrument_ids"] is None
    assert result["block_code"] == "FAIR_CONTRACT_FAIL"


def test_02_sample_mismatch_stops_historical(tmp_path: Path) -> None:
    oos_calls: list[int] = []

    def pair_fn(*_a: object, **_k: object) -> dict:
        return {
            "fair_contract_status": "FAIR_CONTRACT_FAIL",
            "proof": {"fair_contract_status": "FAIR_CONTRACT_FAIL", "pit_status": "PASS", "pit_violations": 0},
        }

    result = _run(
        tmp_path,
        workflow_id=102,
        snapshot=_nested_ok_snapshot(),
        pair_fn=pair_fn,
        oos_fn=lambda **_k: oos_calls.append(1) or (_ for _ in ()).throw(AssertionError("oos")),
    )
    assert result["block_code"] == "FAIR_CONTRACT_FAIL"
    assert oos_calls == []


def test_03_missing_pit_is_not_pass_and_blocks_oos(tmp_path: Path) -> None:
    oos_calls: list[int] = []
    quality = map_data_quality(
        {"domains": []},
        {"proof": {"pit_violations": 0}},
    )
    assert quality["pit_status"] == {"missing": True}

    def missing_pit(*_a: object, **_k: object) -> dict:
        return _pair_ok(fingerprint="aa" * 32, identity_tag="missing-pit", pit_status=None, pit_violations=None)

    result = _run(
        tmp_path,
        workflow_id=103,
        snapshot=_nested_ok_snapshot(),
        pair_fn=missing_pit,
        oos_fn=lambda **_k: oos_calls.append(1) or (_ for _ in ()).throw(AssertionError("oos")),
    )
    assert result["block_code"] == "PIT_FAIL"
    assert oos_calls == []

    def violations(*_a: object, **_k: object) -> dict:
        return _pair_ok(fingerprint="bb" * 32, identity_tag="pit-violations", pit_status="PASS", pit_violations=2)

    result2 = _run(
        tmp_path,
        workflow_id=104,
        snapshot=_nested_ok_snapshot(),
        pair_fn=violations,
        oos_fn=lambda **_k: oos_calls.append(1) or (_ for _ in ()).throw(AssertionError("oos")),
    )
    assert result2["block_code"] == "PIT_FAIL"
    assert oos_calls == []


def test_04_campaign_does_not_pass_current_active_universe() -> None:
    runner_src = (RESEARCH_ROOT / "campaign_runner.py").read_text(encoding="utf-8")
    pair_src = (RESEARCH_ROOT / "campaign_pair.py").read_text(encoding="utf-8")
    assert "instrument_ids=None" in runner_src
    assert "currently_active" not in runner_src
    assert "UNIVERSE_POLICY_CURRENT_ACTIVE" not in pair_src
    assert "HISTORICAL_EQUITY_UNIVERSE_V2" in pair_src


def test_05_nan_not_converted_to_zero() -> None:
    col = V4_FUNDAMENTAL_FEATURE_NAMES[0]
    frame = pd.DataFrame({"y": [1.0, 2.0], col: [0.5, 0.5]})
    masked = apply_ablation_mask(frame, "BASE")
    assert masked[col].isna().all()
    assert not bool((masked[col].fillna(1) == 0).any())
    payload = jsonable_campaign_payload({"coverage": float("nan"), "n": 3})
    assert payload["coverage"] is None
    assert payload["n"] == 3
    quality = map_data_quality(None, None)
    assert quality["price_coverage"]["missing"] is True
    assert 0 not in quality["price_coverage"].values()


def test_06_in_sample_rows_not_stamped_as_oos() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [date(2024, 6, 3), date(2024, 6, 4)],
            "instrument_id": [1, 2],
            "y_pred": [0.2, -0.1],
            "fold_id": [0, 0],
            "split": ["train", "oos"],
        }
    )
    stamped = stamp_oos_predictions_for_economics(
        frame,
        model_variant="V4_FULL",
        folds=[{"fold_id": 0, "train_end": "2024-06-01"}],
    )
    assert len(stamped) == 1
    assert stamped["is_oos"].all()
    assert list(stamped["split"].unique()) == ["oos"]
    checked = validate_oos_prediction_frame(stamped, model_variant="V4_FULL")
    assert len(checked) == 1
    mixed = frame.copy()
    mixed["is_oos"] = [False, True]
    mixed = mixed.drop(columns=["split"])
    only_oos = stamp_oos_predictions_for_economics(mixed, model_variant="V4_FULL")
    assert len(only_oos) == 1


def test_07_08_09_10_economics_contract_surfaced_by_runner(tmp_path: Path) -> None:
    settings = default_economic_primary_contract()
    assert settings["execution"] == "next_open"
    assert settings["return_semantic"] == "PRICE_RETURN"
    assert settings["dividends"] == "excluded"
    assert SKIPPED_BY_BOUNDARY == "SKIPPED_BY_BOUNDARY"

    def pair_fn(*_a: object, **_k: object) -> dict:
        return _pair_ok()

    preds = pd.DataFrame(
        {
            "as_of_date": [date(2024, 6, 3)],
            "instrument_id": [1],
            "y_pred": [0.2],
            "fold_id": [0],
        }
    )

    def oos_fn(**_k: object) -> dict:
        return {
            "regression": {"metrics": {"mae": 0.1}},
            "ranking": {"metrics": {"mean_ic": 0.01, "regression_metrics_skipped": True}},
            "ablation": {
                "variants": {
                    "V4_FULL": {
                        "predictions": preds,
                        "folds": [{"fold_id": 0, "train_end": "2024-06-01"}],
                    }
                }
            },
            "stability": {"status": "ok"},
        }

    def economics_fn(*, predictions: pd.DataFrame, **_k: object) -> dict:
        assert predictions["is_oos"].all()
        return {
            "primary_settings": settings,
            "primary_chosen_as_best_cell": True,
            "cells_enumerated_before_metrics": True,
            "predeclared_cells": [],
            "matrix": [],
            "primary": {
                "cell": {"cost_bps": 30, "rebalance_every_n_sessions": 20, "top_quantile": 0.2},
                "strategy": {
                    "status": "PARTIAL",
                    "return_semantic": "PRICE_RETURN",
                    "dividends": "excluded",
                    "terminal_rebalance_without_execution_session": SKIPPED_BY_BOUNDARY,
                    "fills": [
                        {"decision_date": "2024-06-03", "execution_date": "2024-06-04"},
                    ],
                    "unresolved_exit_events": [
                        {"status": "UNRESOLVED_EXIT", "instrument_id": 1},
                    ],
                },
            },
        }

    days = _weekdays(date(2024, 6, 3), 40)

    def market_loader(*_a: object, **_k: object):
        return SimpleNamespace(trading_days=days)

    result = _run(
        tmp_path,
        workflow_id=107,
        snapshot=_nested_ok_snapshot(),
        pair_fn=pair_fn,
        oos_fn=oos_fn,
        economics_fn=economics_fn,
        market_loader=market_loader,
    )
    assert result["block_code"] is None
    artifact = Path(result["artifact_dir"]) / "economics_primary.json"
    import json

    body = json.loads(artifact.read_text(encoding="utf-8"))
    assert body["status"] == "PARTIAL"
    assert body["unresolved_exit_events"]
    assert body["unresolved_exit_events"][0]["status"] == "UNRESOLVED_EXIT"
    assert body["primary_settings"]["return_semantic"] == "PRICE_RETURN"
    assert body["primary_settings"]["dividends"] == "excluded"
    assert body["score_is_not_return_pct"] is True
    robust = json.loads((Path(result["artifact_dir"]) / "economics_robustness.json").read_text(encoding="utf-8"))
    assert robust["primary_chosen_as_best_cell"] is False


def test_11_ranker_score_is_not_return() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [date(2024, 1, 2)] * 6,
            "instrument_id": list(range(1, 7)),
            "y_pred": [0.9, 0.1, 0.2, 0.3, 0.4, 0.5],
            "y": [0.01, -0.02, 0.0, 0.03, -0.01, 0.02],
        }
    )
    metrics = ranking_metrics(frame, min_ic_instruments=3, top_bottom_quantile=0.3)
    leaked = REGRESSION_METRIC_KEYS.intersection(metrics)
    assert not leaked
    assert "mae" not in metrics
    assert "rmse" not in metrics
    stamped = stamp_oos_predictions_for_economics(frame.assign(fold_id=0), model_variant="V4_FULL")
    assert stamped["score_is_not_return_pct"].all()


def test_12_primary_never_renamed_from_best_cell() -> None:
    from app.modules.research_evidence.campaign_economics import PRIMARY_CELL, primary_settings

    settings = primary_settings()
    assert settings["rebalance_every_n_sessions"] == 20
    assert settings["top_quantile"] == 0.20
    assert settings["assumed_all_in_cost_bps_per_side"] == 30
    assert settings["primary_is_best_matrix_cell"] is False
    assert PRIMARY_CELL.cost_bps == 30
    src = (RESEARCH_ROOT / "campaign_runner.py").read_text(encoding="utf-8")
    assert '"primary_chosen_as_best_cell": False' in src


def test_13_captures_are_not_matured() -> None:
    snap = {
        "empty": False,
        "personal_decision_memory": {
            "captures_total": 20,
            "horizons": [{"horizon_sessions": 20, "matured_count": 0, "status": "EMPTY"}],
        },
        "forward_predictions": {"freshness": {"matured_count": 0}},
    }
    assert classify_prospective_completeness(snap) == STATUS_INSUFFICIENT_SAMPLE
    assert classify_prospective_completeness(snap) != STATUS_OBSERVED
    empty = classify_prospective_completeness({"empty": True, "personal_decision_memory": {"captures_total": 0}})
    assert empty == STATUS_EMPTY


def test_14_no_combined_historical_prospective_score() -> None:
    dossier = build_evidence_dossier_v1(
        identity={"campaign_version": CAMPAIGN_VERSION, "date_from": "2022-04-01", "date_to": "2025-01-01"},
        historical_oos={"status": "COMPLETE", "accuracy": 0.9, "combined_score": 1},
        prospective={"status": "OBSERVED", "kraken_score": 9},
    )
    blob = str(dossier).lower()
    for banned in FORBIDDEN_DOSSIER_KEYS:
        assert banned not in dossier
    assert "combined_score" not in blob
    assert "overall_accuracy" not in blob
    assert "NO_COMBINED_MASTER_SCORE" in dossier["limitations"]


def test_15_dossier_immutability(tmp_path: Path) -> None:
    first = build_evidence_dossier_v1(
        identity={"campaign_version": CAMPAIGN_VERSION, "k": 1},
        historical_oos={"status": "COMPLETE", "mean_ic": 0.01},
    )
    persist_evidence_dossier(first, artifact_root=tmp_path)
    drifted = build_evidence_dossier_v1(
        identity={"campaign_version": CAMPAIGN_VERSION, "k": 1},
        historical_oos={"status": "COMPLETE", "mean_ic": 0.99},
    )
    with pytest.raises(DossierImmutabilityError):
        persist_evidence_dossier(drifted, artifact_root=tmp_path)


def test_16_hash_from_on_disk_payload_excludes_timestamps(tmp_path: Path) -> None:
    from app.modules.research_evidence.bundle import payload_file_hash

    a = persist_evidence_dossier(
        build_evidence_dossier_v1(
            identity={"campaign_version": CAMPAIGN_VERSION, "created_at": "2020-01-01T00:00:00+00:00"},
            historical_oos={"status": "COMPLETE", "mean_ic": 0.01},
        ),
        artifact_root=tmp_path / "a",
    )
    b = persist_evidence_dossier(
        build_evidence_dossier_v1(
            identity={"campaign_version": CAMPAIGN_VERSION, "created_at": "2099-01-01T00:00:00+00:00"},
            historical_oos={"status": "COMPLETE", "mean_ic": 0.01},
        ),
        artifact_root=tmp_path / "b",
    )
    assert a["dossier_hash"] == b["dossier_hash"]
    disk = Path(a["path"]).read_text(encoding="utf-8")
    import json

    assert a["dossier_hash"] == payload_file_hash(json.loads(disk))


def test_17_persist_registry_true_forbidden() -> None:
    with pytest.raises(ValueError, match="persist_registry"):
        CanonicalEvidenceCampaignV1(
            dataset_v3_run_id=1,
            dataset_v4_run_id=2,
            dataset_v3_hash="a",
            dataset_v4_hash="b",
            date_from="2022-04-01",
            date_to="2025-01-01",
            persist_registry=True,
        )
    text = "\n".join(p.read_text(encoding="utf-8") for p in RESEARCH_ROOT.glob("*.py"))
    assert "persist_registry=True" not in text
    assert "persist_registry = True" not in text
    identity = CanonicalEvidenceCampaignV1(
        dataset_v3_run_id=1,
        dataset_v4_run_id=2,
        dataset_v3_hash="a",
        dataset_v4_hash="b",
        date_from="2022-04-01",
        date_to="2025-01-01",
        persist_registry=False,
    ).identity_payload()
    assert identity["campaign_version"] == CAMPAIGN_VERSION
    assert identity["campaign_version"] != PUBLIC_CAMPAIGN_VERSION
    ui = map_identity_for_ui(identity, "fp")
    assert ui["campaign_version"] == PUBLIC_CAMPAIGN_VERSION


def test_api_campaigns_before_experiment_id_and_launch_contract() -> None:
    from app.api.v1.research_evidence import CanonicalCampaignLaunchRequest, launch_canonical_campaign_v1, router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.index("/campaigns") < paths.index("/{experiment_id}")
    assert CanonicalCampaignLaunchRequest.model_fields.keys() == {"campaign_version", "exact_rerun"}
    with pytest.raises(ValidationError):
        CanonicalCampaignLaunchRequest(
            campaign_version=PUBLIC_CAMPAIGN_VERSION,
            instrument_ids=[1],
            date_from="2022-04-01",
        )
    with pytest.raises(HTTPException) as exc:
        launch_canonical_campaign_v1(CanonicalCampaignLaunchRequest(campaign_version=CAMPAIGN_VERSION))
    assert exc.value.status_code == 400
