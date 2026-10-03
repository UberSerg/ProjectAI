"""Focused tests for Evidence Engine overview contract and API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.modules.research_evidence.bundle import write_evidence_bundle
from app.modules.research_evidence.overview_map import (
    FORBIDDEN_OVERVIEW_KEYS,
    empty_overview,
    overview_from_dir,
)
from app.modules.research_evidence.service import get_latest_evidence


def test_empty_overview_has_no_master_score() -> None:
    payload = empty_overview()
    assert FORBIDDEN_OVERVIEW_KEYS.isdisjoint(payload.keys())
    assert payload["experiment"]["status"] == "EMPTY"
    assert payload["prospective"]["empty"] is True
    text = str(payload).lower()
    assert "live ready" not in text
    assert "production ready" not in text
    assert "kraken accuracy" not in text


def test_overview_from_bundle_dir(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "abc123", "research_only": True},
            "dataset_compare": {
                "sample_identity_match": True,
                "schema": {"v3_feature_count": 10, "v4_feature_count": 20},
                "v4": {"pit_violations": 0},
            },
            "model_regression": {
                "status": "ok",
                "metrics": {
                    "n": 12,
                    "rank_ic": {"mean_ic": 0.1},
                    "top_bottom": {"top_minus_bottom": 0.02},
                },
                "folds": [],
                "note": "CHRONOLOGICAL OOS RESEARCH",
            },
            "model_ranker": {
                "status": "ok",
                "metrics": {"n": 12, "mean_ic": 0.08, "top_bottom": {"top_minus_bottom": 0.01}},
                "folds": [],
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    assert payload["dataset"]["sample_identity_match"] is True
    assert payload["dataset"]["pit_violations"] == 0
    assert payload["historical_models"]["regression"]["rank_ic"] == 0.1
    assert "mae" not in (payload["historical_models"]["ranker"] or {})
    assert FORBIDDEN_OVERVIEW_KEYS.isdisjoint(payload.keys())


def test_latest_evidence_empty(tmp_path: Path) -> None:
    payload = get_latest_evidence(artifact_root=tmp_path / "missing")
    assert payload["experiment"]["status"] == "EMPTY"


def test_run_requires_explicit_ids_or_window() -> None:
    from app.api.v1.research_evidence import EvidenceRunRequest, evidence_run

    with pytest.raises(HTTPException) as exc:
        evidence_run(EvidenceRunRequest())
    assert exc.value.status_code == 400
    assert "v3_run_id" in str(exc.value.detail)
