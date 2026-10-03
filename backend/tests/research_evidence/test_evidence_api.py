"""Focused tests for Evidence Engine overview contract and API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.modules.research_evidence.bundle import write_evidence_bundle
from app.modules.research_evidence.overview_map import (
    FORBIDDEN_OVERVIEW_KEYS,
    empty_overview,
    map_prospective_ui,
    overview_from_dir,
)
from app.modules.research_evidence.service import get_latest_evidence, resolve_frozen_run_ids


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


def test_missing_pit_violations_are_not_coerced_to_zero(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "no-pit", "research_only": True},
            "dataset_compare": {
                "sample_identity_match": True,
                "schema": {"v3_feature_count": 10, "v4_feature_count": 20},
                "v4": {},
                "v3": {},
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    assert payload["dataset"]["pit_violations"] is None


def test_zero_pit_violations_not_replaced_by_other_side(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "pit-zero", "research_only": True},
            "dataset_compare": {
                "sample_identity_match": True,
                "v4": {"pit_violations": 0},
                "v3": {"pit_violations": 5},
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    assert payload["dataset"]["pit_violations"] == 0


def test_run_requires_explicit_ids_or_window() -> None:
    from app.api.v1.research_evidence import EvidenceRunRequest, evidence_run

    with pytest.raises(HTTPException) as exc:
        evidence_run(EvidenceRunRequest())
    assert exc.value.status_code == 400
    assert "v3_run_id" in str(exc.value.detail)


REALISTIC_V4 = {
    "fundamental_sample_coverage_pct": 32.5,
    "event_sample_coverage_pct": 14.2,
    "issuer_resolution_basis_counts": {
        "DATED_WINDOW": 70,
        "CURRENT_ONLY": 20,
        "UNMAPPED": 8,
        "AMBIGUOUS": 2,
    },
    "bank_fi_unsupported_samples": 7,
}
REALISTIC_RETURN_TRUTH = {
    "primary_label_family": "MECHANICAL_PRICE_RETURN",
    "total_return": False,
    "total_return_enrichment_status": "NOT_READY",
}


def _assert_realistic_coverage(dataset: dict) -> None:
    assert dataset["fund_coverage"] == 32.5
    assert dataset["event_coverage"] == 14.2
    assert dataset["bank_fi_unsupported"] == 7
    assert dataset["current_only_share"] == pytest.approx(0.2)
    assert dataset["v4_coverage"]["fundamental_sample_coverage_pct"] == 32.5
    assert dataset["v4_coverage"]["current_only_share"] == pytest.approx(0.2)
    assert dataset["return_truth"]["primary_label_family"] == "MECHANICAL_PRICE_RETURN"


def test_v4_coverage_path_a_run_coverage_summary(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "cov-a", "research_only": True},
            "dataset_compare": {
                "sample_identity_match": True,
                "v4": {
                    "pit_violations": 0,
                    "coverage_summary": {"v4": REALISTIC_V4, "return_truth": REALISTIC_RETURN_TRUTH},
                },
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    _assert_realistic_coverage(payload["dataset"])


def test_v4_coverage_path_b_compare_artifact(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "cov-b", "research_only": True},
            "dataset_compare": {
                "sample_identity_match": True,
                "v4": {"v4": REALISTIC_V4, "return_truth": REALISTIC_RETURN_TRUTH},
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    _assert_realistic_coverage(payload["dataset"])


def test_v4_coverage_missing_is_null_zero_stays_zero(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "cov-zero", "research_only": True},
            "dataset_compare": {
                "v4": {
                    "v4": {
                        "fundamental_sample_coverage_pct": 0,
                        "event_sample_coverage_pct": 0,
                        "bank_fi_unsupported_samples": 0,
                    }
                }
            },
        },
    )
    payload = overview_from_dir(tmp_path)
    assert payload["dataset"]["fund_coverage"] == 0
    assert payload["dataset"]["event_coverage"] == 0
    assert payload["dataset"]["bank_fi_unsupported"] == 0
    assert payload["dataset"]["current_only_share"] is None

    write_evidence_bundle(
        tmp_path / "missing",
        {
            "manifest": {"experiment_fingerprint": "cov-miss", "research_only": True},
            "dataset_compare": {"v4": {}},
        },
    )
    missing = overview_from_dir(tmp_path / "missing")
    assert missing["dataset"]["fund_coverage"] is None
    assert missing["dataset"]["event_coverage"] is None
    assert missing["dataset"]["bank_fi_unsupported"] is None
    assert missing["dataset"]["current_only_share"] is None


def test_oos_insufficient_hides_metrics(tmp_path: Path) -> None:
    write_evidence_bundle(
        tmp_path,
        {
            "manifest": {"experiment_fingerprint": "oos-ins", "research_only": True},
            "model_regression": {
                "status": "INSUFFICIENT",
                "metrics": {"n": 2, "rank_ic": {"mean_ic": 0.99}},
                "reason": "insufficient_samples",
            },
            "model_ranker": {
                "status": "insufficient",
                "metrics": {"n": 2, "mean_ic": 0.4},
            },
            "ablation": {"status": "INSUFFICIENT", "variants": {}},
        },
    )
    payload = overview_from_dir(tmp_path)
    for family in ("regression", "ranker"):
        signal = payload["historical_models"][family]
        assert signal["available"] is False
        assert signal["rank_ic"] is None
        assert signal["spread"] is None
        assert signal["n"] is None
    assert payload["ablation"]["partial"] is True


def test_resolve_frozen_run_ids_reads_manifest_identity(tmp_path: Path) -> None:
    exp = tmp_path / "research_evidence" / "frozen-exp"
    write_evidence_bundle(
        exp,
        {
            "manifest": {
                "experiment_fingerprint": "frozen-exp",
                "identity": {"dataset_v3_run_id": 11, "dataset_v4_run_id": 22},
            }
        },
    )
    assert resolve_frozen_run_ids("frozen-exp", artifact_root=tmp_path) == {
        "dataset_v3_run_id": 11,
        "dataset_v4_run_id": 22,
    }
    assert resolve_frozen_run_ids("no-such-exp", artifact_root=tmp_path) is None


def test_run_missing_experiment_is_structured_404() -> None:
    from app.api.v1.research_evidence import EvidenceRunRequest, evidence_run

    with pytest.raises(HTTPException) as exc:
        evidence_run(EvidenceRunRequest(experiment_id="missing-exp"))
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "EXPERIMENT_NOT_FOUND"


def test_run_frozen_ids_gone_is_structured_409(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import research_evidence as api

    monkeypatch.setattr(
        api,
        "resolve_frozen_run_ids",
        lambda _eid: {"dataset_v3_run_id": 11, "dataset_v4_run_id": 22},
    )

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, _model: object, _ident: object) -> None:
            return None

        def commit(self) -> None:
            return None

    monkeypatch.setattr(api, "core_session", lambda: _Session())
    with pytest.raises(HTTPException) as exc:
        api.evidence_run(api.EvidenceRunRequest(experiment_id="frozen-exp"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "FROZEN_RUN_MISSING"


def test_run_by_experiment_id_enqueues_exact_frozen_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.api.v1 import research_evidence as api

    monkeypatch.setattr(
        api,
        "resolve_frozen_run_ids",
        lambda _eid: {"dataset_v3_run_id": 11, "dataset_v4_run_id": 22},
    )
    captured: dict[str, object] = {}

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, _model: object, ident: object) -> object:
            return object() if ident in {11, 22} else None

        def commit(self) -> None:
            return None

    monkeypatch.setattr(api, "core_session", lambda: _Session())
    monkeypatch.setattr(
        api,
        "create_workflow",
        lambda *_a, **_k: SimpleNamespace(id=99),
    )

    def _delay(*args: object) -> None:
        captured["args"] = args

    monkeypatch.setattr(api.worker_tasks.research_evidence_run, "delay", _delay)
    result = api.evidence_run(api.EvidenceRunRequest(experiment_id="frozen-exp", date_from=None))
    assert result["v3_run_id"] == 11
    assert result["v4_run_id"] == 22
    assert captured["args"][1] == 11
    assert captured["args"][2] == 22
    assert captured["args"][3] is None
    assert captured["args"][4] is None


def test_map_prospective_does_not_treat_captures_as_observed() -> None:
    mapped = map_prospective_ui(
        {
            "personal_decision_memory": {
                "captures_total": 10,
                "horizons": [
                    {"horizon_sessions": 5, "matured_count": 0, "pending_count": 10, "unavailable_count": 0},
                    {
                        "horizon_sessions": 20,
                        "matured_count": 0,
                        "pending_count": 10,
                        "unavailable_count": 0,
                        "price_return": {"n": 0, "status": "INSUFFICIENT_SAMPLE"},
                    },
                    {"horizon_sessions": 60, "matured_count": 0, "pending_count": 10, "unavailable_count": 0},
                ],
            },
            "forward_predictions": {"freshness": {"matured_count": 0, "pending_count": 0}},
        }
    )
    assert mapped["status"] != "OBSERVED"
    assert mapped["empty"] is False
    assert "n_observations" not in mapped
    blob = str(mapped)
    assert "10 matured" not in blob.lower()
    h20 = next(h for h in mapped["personal_decision_memory"]["horizons"] if h["horizon_sessions"] == 20)
    assert h20["matured_count"] == 0
    assert mapped["personal_decision_memory"]["captures_total"] == 10
